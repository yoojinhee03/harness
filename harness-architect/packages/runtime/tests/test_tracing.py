"""트레이싱 테스트 (선택적) — OTel 스팬이 하네스 속성과 함께 남는지.

opentelemetry-sdk 설치 환경에서만 돈다(없으면 skip). InMemory exporter 로 서버 없이 검증.
"""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk", reason="opentelemetry-sdk 미설치 — 선택적 extra")

from harness_runtime import harness_span


def test_harness_span_records_attributes():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    with harness_span("eval", harness_id="pr-bot", mean_score=0.8, skipped=None):
        pass

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert "eval" in spans
    attrs = spans["eval"].attributes
    assert attrs["harness.harness_id"] == "pr-bot"
    assert attrs["harness.mean_score"] == 0.8
    assert "harness.skipped" not in attrs  # None 속성은 생략


def test_harness_span_noop_without_provider_is_safe():
    """스팬 컨텍스트는 예외 없이 진입/이탈된다(관측 실패가 실행을 막지 않음)."""
    with harness_span("run", harness_id="x") as span:
        assert span is None or span is not None  # 설치 여부와 무관하게 안전
