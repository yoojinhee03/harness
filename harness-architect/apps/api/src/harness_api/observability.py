"""관측성 — 요청 ID·구조적 로깅·Prometheus 메트릭·Sentry(선택).

미들웨어는 **순수 ASGI**로 짠다: BaseHTTPMiddleware 는 응답을 버퍼링해 SSE(스트리밍)를 깨므로.
메트릭 경로 라벨은 라우트 템플릿(`/harnesses/{hid}`)을 써서 카디널리티를 묶는다.
"""

from __future__ import annotations

import logging
import os
import time
from contextvars import ContextVar
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_REQUESTS = Counter("harness_http_requests_total", "HTTP 요청 수", ["method", "path", "status"])
_LATENCY = Histogram("harness_http_request_seconds", "HTTP 처리 시간(초)", ["method", "path"])


def _new_id() -> str:
    return os.urandom(6).hex()


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else scope.get("path", "?")


class ObservabilityMiddleware:
    """요청 ID 부여·전파(X-Request-ID) + 요청 수/지연 메트릭. 스트리밍(SSE) 안전."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        rid = headers.get(b"x-request-id", b"").decode() or _new_id()
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = _route_template(scope)
            _LATENCY.labels(scope["method"], path).observe(time.perf_counter() - start)
            _REQUESTS.labels(scope["method"], path, str(status["code"])).inc()
            request_id_var.reset(token)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging() -> None:
    """구조적(요청 ID 포함) 로깅. 핸들러가 없을 때만 설치(테스트·중복 방지)."""
    root = logging.getLogger()
    if any(isinstance(f, _RequestIdFilter) for h in root.handlers for f in h.filters):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
    handler.addFilter(_RequestIdFilter())
    root.handlers = [handler]
    root.setLevel(os.environ.get("HARNESS_LOG_LEVEL", "INFO"))


def init_sentry() -> None:
    """SENTRY_DSN 있으면 에러 트래킹 활성(선택 의존성 [sentry])."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=dsn, traces_sample_rate=float(os.environ.get("SENTRY_TRACES", "0")))
        logging.getLogger("harness_api").info("Sentry 활성")
    except ImportError:
        logging.getLogger("harness_api").warning("SENTRY_DSN 설정됐지만 sentry-sdk 미설치 — uv sync --extra sentry")


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def db_ready(engine: Any) -> bool:
    """DB 연결 확인(readiness). SELECT 1."""
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False
