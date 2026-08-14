"""FastAPI 앱 — AI 하네스 아키텍트 백엔드.

엔드포인트 (화면 대응):
    GET  /health
    GET  /catalog                 카탈로그 목록 (화면 E)  — ?type= ?capability= 필터
    GET  /catalog/{id}            카탈로그 상세 (화면 E)
    POST /recommend               설명 → 요구 능력 + 추천 (화면 A→B)
    POST /resolve                 선택 구성 → 검증 진단 (화면 C, gap 되돌림)
    POST /generate                확정 → harness.yaml 생성 (화면 C→D)
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from harness_catalog import (
    FederatedRegistry,
    LiveRecommender,
    Recommender,
    build_registry,
    load_settings,
    resolve_catalog_dir,
)
from harness_resolver import HarnessConfig, InMemoryRegistry, ResolveResult, resolve
from harness_runtime import AnthropicRunner, available_targets, build_request, emit
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse

from .accounts import AccountStore
from .catalog_store import CatalogStore, DbCatalogSource, sync_catalog
from .observability import (
    ObservabilityMiddleware,
    configure_logging,
    db_ready,
    init_sentry,
    metrics_response,
)
from .schemas import (
    CatalogItem,
    DevLoginBody,
    GenerateResponse,
    HarnessSaveBody,
    MemberBody,
    RecommendRequest,
    ResolveRequest,
    RunRequest,
    TeamCreateBody,
    TokenCreateBody,
)
from .store import (
    HarnessStore,
    SSEBroadcaster,
    VersionConflict,
    event_stream,
    make_broadcaster,
    resolve_store_dir,
    safe_id,
)

log = logging.getLogger("harness_api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 저장소 DB(SQL) + 계정 + SSE 브로드캐스터. DATABASE_URL 없으면 SQLite(store 폴더).
    from .db import make_engine, resolve_database_url

    init_sentry()  # SENTRY_DSN 있으면 에러 트래킹
    engine = make_engine(resolve_database_url(resolve_store_dir()))
    app.state.engine = engine
    app.state.store = HarnessStore(engine)
    app.state.accounts = AccountStore(engine)
    app.state.broadcaster = make_broadcaster()  # REDIS_URL 있으면 Redis(스케일아웃)
    # OAuth CSRF state 임시 저장(state -> 생성 시각). 단일 인스턴스 개발용 — 멀티 인스턴스는 Redis/DB 로.
    app.state.oauth_states = {}
    log.info("저장소 DB: %s · 스코프 격리 · OAuth 인증", engine.url)

    # 카탈로그 — 서빙은 **DB 만** 읽어 즉시 응답한다(네트워크 무의존). 느린 harvest(레지스트리·
    # 마켓플레이스)는 백그라운드 주기 스케줄러가 DB 에 적재한다. 서빙과 harvest 를 DB 로 분리.
    cfg = load_settings()
    try:
        local = build_registry(resolve_catalog_dir())
        log.info("로컬 카탈로그 시드: %s개", len(local.all()))
    except FileNotFoundError as exc:
        log.warning("카탈로그를 찾지 못함 — 빈 레지스트리로 기동: %s", exc)
        local = InMemoryRegistry([])
    catalog_store = CatalogStore(engine)
    app.state.catalog_store = catalog_store
    harvest_on = cfg.use_live_registry or cfg.use_marketplace
    # off 면 로컬 시드만(결정적·오프라인). on 이면 로컬 + DB(harvest 결과)를 합쳐 서빙.
    registry = FederatedRegistry(local, [DbCatalogSource(catalog_store)]) if harvest_on else local
    app.state.registry = registry
    app.state.recommender = LiveRecommender(registry)

    async def _sync_loop() -> None:
        # 주기적으로 하이브리드 harvest→DB(증분 또는 full). 첫 기동엔 상태가 없어 즉시 1회(full),
        # 이후 sync_interval 마다 증분, full_interval(기본 24h)마다 전체 대조. due_for_sync 는 마지막
        # sync 시각(state) 기준이라 다중 레플리카 중복도 완화한다. 서빙은 이 루프와 무관하게 DB 를 읽는다.
        while True:
            try:
                if await asyncio.to_thread(catalog_store.due_for_sync, cfg.catalog_sync_interval):
                    res = await asyncio.to_thread(sync_catalog, engine, cfg)
                    total = await asyncio.to_thread(catalog_store.count)
                    log.info("카탈로그 sync 완료: %s (총 %s개)", res, total)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 실패해도 루프 유지(다음 주기 재시도)
                log.warning("카탈로그 sync 오류(다음 주기 재시도): %s", exc)
            await asyncio.sleep(min(cfg.catalog_sync_interval, 300))

    app.state.sync_task = asyncio.create_task(_sync_loop()) if harvest_on else None
    yield
    # 종료 — 진행 중인 sync 스케줄러 취소.
    task = getattr(app.state, "sync_task", None)
    if task is not None and not task.done():
        task.cancel()


app = FastAPI(
    title="AI 하네스 아키텍트 API",
    version="0.1.0",
    description="자연어 설명 → 하네스 구성요소 추천 → 검증 → harness.yaml 생성.",
    lifespan=lifespan,
)

# 레이트리밋(slowapi) — IP 기준. 계정 스팸·비용 유발 완화. 테스트에선 HARNESS_RATELIMIT=off 로 비활성.
limiter = Limiter(key_func=get_remote_address, enabled=os.environ.get("HARNESS_RATELIMIT", "on") != "off")
app.state.limiter = limiter
# slowapi 핸들러 시그니처(RateLimitExceeded)와 Starlette 기대(Exception)의 타입 불일치 — 런타임 정상.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# 관측성 — 구조적 로깅 + 요청 ID·메트릭 미들웨어(순수 ASGI, SSE 안전).
configure_logging()
app.add_middleware(ObservabilityMiddleware)

# CORS — 기본 거부(빈 allowlist). 웹은 리버스 프록시로 동일 오리진, 확장은 Node fetch(브라우저 CORS
# 무관)라 기본은 필요 없다. 크로스 오리진으로 API 를 직접 노출할 때만 HARNESS_CORS_ORIGINS(쉼표 구분).
_cors_origins = [o.strip() for o in os.environ.get("HARNESS_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count"],  # 페이지네이션 총계 헤더를 크로스오리진에서도 읽게
    )


def _registry(request: Request) -> InMemoryRegistry:
    return cast(InMemoryRegistry, request.app.state.registry)


def _recommender(request: Request) -> Recommender:
    # LiveRecommender.get() — 라이브 내용이 바뀌었으면 재인덱싱(동기 엔드포인트는 스레드풀 실행이라 안전).
    return cast(LiveRecommender, request.app.state.recommender).get()


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    """라이브니스 — 프로세스가 떠 있는지. 라이브 페치를 유발하지 않도록 로컬 카탈로그 크기만 본다."""
    reg = request.app.state.registry
    base = getattr(reg, "local", reg)  # FederatedRegistry 면 로컬만(네트워크 X)
    return {"status": "ok", "catalog_size": len(base.all())}


@app.get("/ready")
def ready(request: Request) -> Response:
    """레디니스 — 트래픽 받을 준비(DB 연결). 실패 시 503(로드밸런서가 제외)."""
    ok = db_ready(request.app.state.engine)
    return JSONResponse({"ready": ok}, status_code=200 if ok else 503)


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus 스크레이프 — 요청 수/지연."""
    return metrics_response()


# ─────────── 설정: LLM 키 상태 (배포 env 전용 · 읽기전용) ───────────
# 키는 배포 환경변수(ANTHROPIC_API_KEY·VOYAGE_API_KEY)로만 주입한다. 런타임에 사용자별로 바꾸지
# 않는다 — LLM 키는 서비스가 소유하는 운영 시크릿이라, 사용자 변조는 멀티테넌시 누수(전역 os.environ)를
# 낳는다(구설계의 결함). 화면엔 마스킹된 '설정 여부'만 노출한다.


def _mask(key: str) -> str:
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "****"


def _provider_status(env_var: str) -> dict[str, Any]:
    key = os.environ.get(env_var)
    return {"set": bool(key), "masked": _mask(key) if key else None}


@app.get("/settings/keys")
def get_keys() -> dict[str, Any]:
    """LLM 키 상태(배포 구성) — 읽기전용. 값 설정은 배포 env 로만."""
    from harness_catalog import load_settings

    s = load_settings()
    return {
        "anthropic": _provider_status("ANTHROPIC_API_KEY"),
        "voyage": _provider_status("VOYAGE_API_KEY"),
        "quality_mode": {
            "embedder": "voyage" if s.use_voyage else "local",
            "ranker": "claude" if s.use_claude else "heuristic",
        },
    }


@app.post("/settings/keys/verify")
def verify_keys() -> dict[str, str]:
    """배포 env 키로 최소 호출을 시도해 실제 연동 여부를 확인(원본 키는 반환 안 함)."""
    out: dict[str, str] = {}
    ak = os.environ.get("ANTHROPIC_API_KEY")
    if not ak:
        out["anthropic"] = "unset"
    else:
        try:
            import anthropic

            anthropic.Anthropic(api_key=ak).messages.create(
                model="claude-sonnet-5", max_tokens=1, messages=[{"role": "user", "content": "ping"}]
            )
            out["anthropic"] = "ok"
        except Exception as exc:  # noqa: BLE001 - 네트워크/인증 오류를 사용자에게 요약 전달
            out["anthropic"] = f"error: {type(exc).__name__}"
    vk = os.environ.get("VOYAGE_API_KEY")
    if not vk:
        out["voyage"] = "unset"
    else:
        try:
            import voyageai

            voyageai.Client(api_key=vk).embed(["ping"], model="voyage-3.5", input_type="document")
            out["voyage"] = "ok"
        except Exception as exc:  # noqa: BLE001
            out["voyage"] = f"error: {type(exc).__name__}"
    return out


@app.get("/catalog", response_model=list[CatalogItem])
def catalog(
    request: Request,
    response: Response,
    type: str | None = Query(default=None, description="skill|mcp|context|hook"),
    capability: str | None = Query(default=None, description="provides/capability_tags 로 필터"),
    q: str | None = Query(default=None, description="id·name·summary·태그 부분일치 검색"),
    limit: int | None = Query(default=None, ge=1, le=200, description="페이지 크기(미지정=전체)"),
    offset: int = Query(default=0, ge=0, description="페이지 시작 오프셋"),
) -> list[CatalogItem]:
    """카탈로그 목록 — type·capability·q 로 필터/검색하고 limit·offset 으로 페이지네이션.

    총 개수(필터 적용 후)는 `X-Total-Count` 헤더로 준다(본문은 현재 페이지만). 카탈로그가
    수천 개로 커져도 서버에서 잘라 보내므로 페이로드·렌더가 가볍다. 필터·검색·정렬은 서버가 하므로
    검색이 현재 페이지가 아니라 전체에 걸린다.
    """
    comps = _registry(request).all()
    if type:
        comps = [c for c in comps if c.type == type]
    if capability:
        comps = [c for c in comps if capability in c.provides or capability in c.capability_tags]
    if q:
        ql = q.lower()
        comps = [
            c
            for c in comps
            if ql in f"{c.id} {c.name} {c.summary} {' '.join(c.capability_tags)}".lower()
        ]
    total = len(comps)
    # 안정적 페이지 경계 — 타입·이름·id 순 정렬 후 슬라이스.
    comps.sort(key=lambda c: (c.type, c.name.lower(), c.id))
    page = comps[offset : offset + limit] if limit is not None else comps[offset:]
    response.headers["X-Total-Count"] = str(total)
    return [CatalogItem.from_component(c) for c in page]


@app.get("/catalog/{component_id}")
def catalog_detail(request: Request, component_id: str) -> dict[str, Any]:
    c = _registry(request).get(component_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"컴포넌트 '{component_id}' 없음")
    return c.model_dump()


@app.post("/recommend")
@limiter.limit("60/minute")
def recommend(request: Request, body: RecommendRequest) -> dict[str, Any]:
    result = _recommender(request).recommend(body.description, top_k=body.top_k)
    return result.model_dump()


@app.post("/resolve", response_model=ResolveResult)
def resolve_endpoint(request: Request, body: ResolveRequest) -> ResolveResult:
    config = body.to_config()
    return resolve(config, _registry(request))


@app.post("/generate", response_model=GenerateResponse)
def generate(request: Request, body: ResolveRequest) -> GenerateResponse:
    config = body.to_config()
    result = resolve(config, _registry(request))
    return GenerateResponse(
        yaml=to_harness_yaml(config),
        ok=result.ok,
        gaps=len(result.diagnostics.gaps),
        warnings=len(result.diagnostics.warnings),
        errors=len(result.diagnostics.errors),
    )


@app.post("/run")
@limiter.limit("30/minute")
def run_endpoint(request: Request, body: RunRequest) -> dict[str, Any]:
    """resolve → build_request → (키 있으면) Anthropic 전송, 없으면 dry_run. 런타임 관통."""
    config = body.to_config()
    result = resolve(config, _registry(request))
    if not result.ok or result.resolved is None:
        return {"ok": False, "diagnostics": result.diagnostics.model_dump(), "built": None, "run": None}
    built = build_request(result.resolved, body.message)
    run = AnthropicRunner().run(built)
    return {
        "ok": True,
        "built": {
            "model": built.model,
            "system_chars": len(built.system),
            # API 로 전송되는 MCP 서버(원격 URL 만). stdio 서버는 eject 몫이라 여기 안 실린다.
            "mcp_servers": [m["name"] for m in built.mcp_servers],
            "hook_plan": built.hook_plan,
            "permissions": built.permissions,
        },
        "run": run.model_dump(),
    }


@app.get("/eject/targets")
def eject_targets() -> list[str]:
    """지원하는 eject 타깃 목록(프론트 타깃 셀렉터용)."""
    return available_targets()


@app.post("/eject")
def eject_endpoint(
    request: Request, body: ResolveRequest, target: str = Query("claude-code")
) -> dict[str, Any]:
    """resolve → emit(target). ResolvedHarness IR 을 런타임 네이티브 파일 트리로 컴파일 (Phase 5)."""
    if target not in available_targets():
        raise HTTPException(status_code=400, detail=f"지원하지 않는 타깃: {target} (가능: {available_targets()})")
    result = resolve(body.to_config(), _registry(request))
    if not result.ok or result.resolved is None:
        return {"ok": False, "target": target, "diagnostics": result.diagnostics.model_dump(), "files": None}
    return {"ok": True, "target": target, "files": emit(result.resolved, target)}


# ─────────────── 멀티테넌시: 인증(Bearer) + 팀(자가서브) + 스코프 격리 저장소 ───────────────


def _store(request: Request) -> HarnessStore:
    return cast(HarnessStore, request.app.state.store)


def _broadcaster(request: Request) -> SSEBroadcaster:
    return cast(SSEBroadcaster, request.app.state.broadcaster)


def _accounts(request: Request) -> AccountStore:
    return cast(AccountStore, request.app.state.accounts)


def _bearer(authorization: str | None, token: str | None) -> str:
    """Authorization: Bearer <t> 또는 ?token=<t> 에서 원문 토큰을 뽑는다(SSE 는 헤더 불가라 쿼리 허용)."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return (token or "").strip()


async def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    """Bearer 토큰(세션 또는 PAT)으로 사용자 신원 확인. SSE(EventSource)는 ?token= 도 허용."""
    user = _accounts(request).user_by_token(_bearer(authorization, token))
    if user is None:
        raise HTTPException(status_code=401, detail="인증 필요 — 로그인하세요")
    return user


# ─────────────── OAuth 로그인 (사람=이메일 신원) ───────────────
# 사람은 OAuth 로 로그인해 웹 세션 토큰을 받고, 기계(VSCode)는 설정에서 PAT 를 발급받아 붙인다.
# 공급자 앱 자격증명은 배포 env 로만 주입한다.

_GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
_GITHUB_USER = "https://api.github.com/user"
_GITHUB_EMAILS = "https://api.github.com/user/emails"
_SESSION_TTL_DAYS = 30


def _dev_auth() -> bool:
    return os.environ.get("HARNESS_DEV_AUTH", "") == "on"


def _github_client() -> tuple[str, str]:
    return os.environ.get("GITHUB_OAUTH_CLIENT_ID", ""), os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "")


def _redirect_base() -> str:
    # GitHub 앱에 등록하는 콜백의 베이스. 개발은 웹 오리진(:5173)의 /api 프록시를 거쳐 백엔드로.
    return os.environ.get("OAUTH_REDIRECT_BASE", "http://localhost:5173/api").rstrip("/")


def _web_base() -> str:
    return os.environ.get("WEB_BASE_URL", "http://localhost:5173").rstrip("/")


@app.get("/auth/config")
def auth_config() -> dict[str, Any]:
    """로그인 화면이 어떤 방법을 띄울지 — 구성된 OAuth 공급자 + 개발 로그인 가용 여부."""
    providers = ["github"] if _github_client()[0] else []
    return {"providers": providers, "dev_auth": _dev_auth()}


@app.get("/auth/oauth/{provider}/start")
def oauth_start(request: Request, provider: str) -> Response:
    """공급자 인증 페이지로 리다이렉트(state 로 CSRF 방지)."""
    if provider != "github":
        raise HTTPException(status_code=404, detail=f"지원하지 않는 공급자: {provider}")
    client_id, _ = _github_client()
    if not client_id:
        raise HTTPException(status_code=400, detail="GitHub OAuth 미구성 — GITHUB_OAUTH_CLIENT_ID 필요")
    state = secrets.token_urlsafe(24)
    request.app.state.oauth_states[state] = time.time()
    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": f"{_redirect_base()}/auth/oauth/github/callback",
            "scope": "read:user user:email",
            "state": state,
            "allow_signup": "true",
        }
    )
    return RedirectResponse(f"{_GITHUB_AUTHORIZE}?{params}")


def _pop_state(request: Request, state: str) -> bool:
    states: dict[str, float] = request.app.state.oauth_states
    ts = states.pop(state, None)
    # 만료(10분) 청소 + 유효성
    for k, v in list(states.items()):
        if time.time() - v > 600:
            states.pop(k, None)
    return ts is not None and time.time() - ts <= 600


@app.get("/auth/oauth/{provider}/callback")
def oauth_callback(
    request: Request, provider: str, code: str = Query(...), state: str = Query(...)
) -> Response:
    """공급자 콜백 — code 교환 → 프로필 조회 → 유저 upsert → 세션 발급 → 웹으로 리다이렉트."""
    if provider != "github" or not _pop_state(request, state):
        return RedirectResponse(f"{_web_base()}/?auth_error=invalid_state")
    client_id, client_secret = _github_client()
    try:
        with httpx.Client(timeout=10.0) as c:
            tok = c.post(
                _GITHUB_TOKEN,
                headers={"Accept": "application/json"},
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": f"{_redirect_base()}/auth/oauth/github/callback",
                },
            ).json()
            access = tok.get("access_token")
            if not access:
                return RedirectResponse(f"{_web_base()}/?auth_error=token_exchange")
            gh_headers = {"Authorization": f"token {access}", "Accept": "application/vnd.github+json"}
            gh = c.get(_GITHUB_USER, headers=gh_headers).json()
            email = gh.get("email")
            if not email:  # 공개 이메일이 없으면 primary·verified 이메일을 별도 조회
                emails = c.get(_GITHUB_EMAILS, headers=gh_headers).json()
                email = next(
                    (e["email"] for e in emails if e.get("primary") and e.get("verified")),
                    next((e["email"] for e in emails if e.get("verified")), None),
                )
            if not email:
                return RedirectResponse(f"{_web_base()}/?auth_error=no_email")
    except httpx.HTTPError:
        return RedirectResponse(f"{_web_base()}/?auth_error=provider_unreachable")

    user = _accounts(request).upsert_oauth_user(
        "github", str(gh.get("id")), email, gh.get("name") or gh.get("login") or "", gh.get("avatar_url") or ""
    )
    session = _accounts(request).create_token(user["id"], "session", name="web", ttl_days=_SESSION_TTL_DAYS)
    return RedirectResponse(f"{_web_base()}/?session={session['token']}")


@app.post("/auth/dev-login")
def dev_login(request: Request, body: DevLoginBody) -> dict[str, Any]:
    """개발 전용 로그인(HARNESS_DEV_AUTH=on) — 실제 OAuth 앱 없이 이메일로 세션 발급."""
    if not _dev_auth():
        raise HTTPException(status_code=404, detail="dev-login 비활성 (HARNESS_DEV_AUTH=on 필요)")
    email = body.email.strip().lower()
    user = _accounts(request).upsert_oauth_user("dev", email, email, email.split("@")[0], "")
    session = _accounts(request).create_token(user["id"], "session", name="dev", ttl_days=_SESSION_TTL_DAYS)
    return {"token": session["token"], "user": user}


@app.post("/auth/logout")
def logout(
    request: Request,
    authorization: str | None = Header(default=None),
    _user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    """현재 세션 토큰만 폐기(PAT·다른 기기 세션은 유지)."""
    return {"ok": _accounts(request).revoke_by_token(_bearer(authorization, None))}


# ── PAT(개인 액세스 토큰) — VSCode·기계 연결용, 설정 화면에서 관리 ──


@app.get("/auth/tokens")
def list_tokens(request: Request, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return _accounts(request).list_tokens(user["id"], kind="pat")


@app.post("/auth/tokens")
def create_pat(
    request: Request, body: TokenCreateBody, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    """PAT 발급 — 원문은 이 응답에서만 노출. 이후 목록엔 이름·발급일만 보인다."""
    name = body.name.strip() or "VSCode"
    return _accounts(request).create_token(user["id"], "pat", name=name)


@app.delete("/auth/tokens/{tid}")
def revoke_pat(
    request: Request, tid: str, user: dict[str, Any] = Depends(current_user)
) -> dict[str, bool]:
    if not _accounts(request).revoke_token(user["id"], tid):
        raise HTTPException(status_code=404, detail="토큰 없음")
    return {"ok": True}


def _resolve_scope(request: Request, user: dict[str, Any], scope: str, write: bool = False) -> str:
    """쿼리 scope('personal'|'team:<tid>')를 스코프 키로. 팀은 멤버십·역할을 검사.

    write=True(저장·삭제)면 owner/editor 만 허용(viewer 는 읽기 전용). 격리는 항상.
    """
    if scope in ("", "personal"):
        return f"personal:{user['id']}"
    if scope.startswith("team:"):
        tid = scope[len("team:") :]
        role = _accounts(request).member_role(tid, user["id"])
        if role is None:
            raise HTTPException(status_code=403, detail="이 팀의 멤버가 아닙니다")
        if write and role not in ("owner", "editor"):
            raise HTTPException(status_code=403, detail="뷰어는 쓰기 권한이 없습니다(읽기 전용)")
        return f"team:{tid}"
    raise HTTPException(status_code=400, detail=f"잘못된 scope: {scope} (personal|team:<id>)")


# ── 팀 ──


@app.get("/me")
def whoami(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {**user, "teams": _accounts(request).teams_of(user["id"])}


@app.post("/teams")
def create_team(
    request: Request, body: TeamCreateBody, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    return _accounts(request).create_team(body.name, user["id"])


@app.get("/teams")
def list_teams(request: Request, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return _accounts(request).teams_of(user["id"])


@app.post("/teams/{tid}/members")
def add_team_member(
    request: Request, tid: str, body: MemberBody, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    try:
        return _accounts(request).add_member(tid, user["id"], body.email, body.role)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── 스코프 격리 하네스 저장소 (웹 ↔ VSCode 확장 양방향 동기화) ──


@app.get("/harnesses")
def list_harnesses(
    request: Request,
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(current_user),
) -> list[dict[str, Any]]:
    """내 가시 스코프(personal + 내 팀들)의 하네스 요약 목록(최신순). limit/offset 으로 페이지네이션."""
    scopes = sorted(_accounts(request).visible_scope_keys(user["id"]))
    return _store(request).list_scopes(scopes, limit=limit, offset=offset)


# ⚠ 라우트 순서: 고정 경로(/harnesses/events)를 {hid} 보다 먼저 선언해야 매칭이 가로채이지 않는다.
@app.get("/harnesses/events")
async def harness_events(
    request: Request, user: dict[str, Any] = Depends(current_user)
) -> EventSourceResponse:
    """SSE — 내 가시 스코프의 변경만 실시간 푸시. 연결 시 현재 목록을 ready 로 먼저 보낸다."""
    scopes = _accounts(request).visible_scope_keys(user["id"])
    return EventSourceResponse(event_stream(_store(request), _broadcaster(request), scopes))


@app.get("/harnesses/{hid}/versions")
def harness_versions(
    request: Request,
    hid: str,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> list[dict[str, Any]]:
    """현재 + 이전 버전들(최신순). 웹이 버전 간 diff 를 그린다."""
    sk = _resolve_scope(request, user, scope)
    v = _store(request).versions(sk, hid)
    if v is None:
        raise HTTPException(status_code=404, detail=f"하네스 '{hid}' 없음(scope={scope})")
    return v


@app.get("/harnesses/{hid}")
def get_harness(
    request: Request,
    hid: str,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    sk = _resolve_scope(request, user, scope)
    doc = _store(request).get(sk, hid)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"하네스 '{hid}' 없음(scope={scope})")
    return doc


@app.put("/harnesses/{hid}")
async def put_harness(
    request: Request,
    hid: str,
    body: HarnessSaveBody,
    scope: str = Query("personal"),
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """하네스 저장(upsert). 스코프 안에 저장하고 SSE 푸시. If-Match(버전)를 주면 낙관적 잠금 → 409."""
    sk = _resolve_scope(request, user, scope, write=True)
    store = _store(request)
    expected = int(if_match) if if_match and if_match.isdigit() else None
    try:
        doc = store.put(sk, hid, user["id"], body.name, body.description, body.yaml, expected_version=expected)
    except VersionConflict as exc:
        raise HTTPException(
            status_code=409, detail=f"버전 충돌 — 현재 v{exc.current}. 최신을 다시 불러온 뒤 저장하세요."
        ) from exc
    await _broadcaster(request).publish(
        {"type": "upsert", "id": doc["id"], "scope": sk, "harness": store.summary(doc)}
    )
    return doc


@app.delete("/harnesses/{hid}")
async def delete_harness(
    request: Request,
    hid: str,
    scope: str = Query("personal"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    sk = _resolve_scope(request, user, scope, write=True)
    if not _store(request).delete(sk, hid):
        raise HTTPException(status_code=404, detail=f"하네스 '{hid}' 없음(scope={scope})")
    await _broadcaster(request).publish({"type": "delete", "id": safe_id(hid), "scope": sk})
    return {"ok": True, "id": safe_id(hid), "scope": sk}


def to_harness_yaml(config: HarnessConfig) -> str:
    """HarnessConfig → harness.yaml 텍스트 (스펙 §2 구조)."""
    doc: dict[str, Any] = {
        "apiVersion": config.apiVersion,
        "kind": config.kind,
        "metadata": config.metadata.model_dump(exclude_defaults=False),
    }
    if config.extends:
        doc["extends"] = config.extends
    doc["model"] = config.model.model_dump()
    if config.prompt is not None:
        # 최소 표현 — 기본값/None 필드는 생략해 authored 입력에 가깝게 직렬화.
        doc["prompt"] = config.prompt.model_dump(exclude_defaults=True, exclude_none=True)
    if config.permissions:
        doc["permissions"] = config.permissions
    doc["components"] = [
        ({"ref": s.ref, "config": s.config} if s.config else {"ref": s.ref})
        for s in config.components
    ]
    if config.budget:
        doc["budget"] = config.budget.model_dump()
    return cast(str, yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
