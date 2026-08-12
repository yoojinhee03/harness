"""실행 트레이싱 (선택적) — 하네스 실행을 관측 가능하게(Observation 축).

오픈소스 **OpenTelemetry** 로 하네스 실행/eval 에 스팬을 남긴다. OTLP 로 Langfuse·Phoenix·
Traceloop(OpenLLMetry) 등 어떤 백엔드로도 보낼 수 있고, 서버 없이 InMemory/Console
exporter 로도 확인된다. 실사용 신호(대리지표 eval 과 별개)를 피드백 루프로 흘리는 통로.

opentelemetry 는 선택적 — 미설치면 `harness_span` 은 **완전 no-op**(비용 없음, 폴백 불변).
설치: `pip install opentelemetry-sdk`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


def _tracer() -> Any | None:
    try:
        from opentelemetry import trace
    except ModuleNotFoundError:  # pragma: no cover - 선택적 의존성
        return None
    return trace.get_tracer("harness-architect")


@contextmanager
def harness_span(name: str, **attributes: Any) -> Iterator[Any]:
    """하네스 실행 구간 스팬. OTel 미설치 시 no-op(같은 인터페이스로 yield None).

        with harness_span("eval", harness_id=hid, mean_score=report.mean_score):
            ...
    """
    tracer = _tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(f"harness.{key}", value)
        yield span
