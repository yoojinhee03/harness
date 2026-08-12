"""Phase 2 확장 — OpenHarness 런타임 임베드 테스트 (선택적 의존성).

openharness-ai 가 설치된 환경에서만 돈다(없으면 skip). 키 없이 fake 스트리밍 클라이언트로
QueryEngine 루프를 구동해 우리 IR → 실제 에이전트 루프가 관통하는지 검증한다.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openharness", reason="openharness-ai 미설치 — 선택적 extra")

from harness_resolver.models import CostTotals, HarnessMetadata, ModelConfig, ResolvedHarness, ResolvedPrompt
from harness_runtime import OpenHarnessRunner


def make_resolved() -> ResolvedHarness:
    return ResolvedHarness(
        metadata=HarnessMetadata(id="t"),
        model=ModelConfig(name="claude-sonnet-5", max_tokens=1024),
        permissions={},
        components=[],
        provided={},
        hook_plan={},
        auth_needs=[],
        cost=CostTotals(),
        prompt=ResolvedPrompt(system_text="너는 시니어 코드 리뷰어다.", hash="sha256:x"),
    )


def fake_streaming_client(text: str) -> object:
    from openharness.api.client import ApiMessageCompleteEvent, ApiTextDeltaEvent, ConversationMessage, UsageSnapshot

    class FakeApiClient:
        async def stream_message(self, request):  # SupportsStreamingMessages 프로토콜
            yield ApiTextDeltaEvent(text=text)
            msg = ConversationMessage(role="assistant", content=text)
            yield ApiMessageCompleteEvent(
                message=msg, usage=UsageSnapshot(input_tokens=5, output_tokens=5), stop_reason="end_turn"
            )

    return FakeApiClient()


def test_openharness_loop_runs_offline_with_fake_client():
    """우리 ResolvedHarness → QueryEngine 루프가 키 없이 fake 클라이언트로 관통, 출력 수집."""
    runner = OpenHarnessRunner(client=fake_streaming_client("리뷰 결과: 타입 힌트 추가 권장."), max_turns=1)
    result = runner.run(make_resolved(), "이 diff 리뷰해줘: def add(a,b): return a+b")
    assert result.dry_run is False
    assert result.model == "claude-sonnet-5"
    assert "타입 힌트" in (result.text or "")


def test_openharness_dry_run_without_key(monkeypatch):
    """클라이언트/키 없으면 루프 미실행 dry_run(폴백 안전)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = OpenHarnessRunner(client=None).run(make_resolved(), "hi")
    assert result.dry_run is True and result.text is None
