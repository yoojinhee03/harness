"""가드레일 실물 테스트 (선택적) — Presidio 로 pii-redact 훅이 실제로 마스킹하는지.

presidio 설치 환경에서만 돈다(없으면 skip). 훅 엔진에 등록해 응답 페이로드의 PII 가
end-to-end 로 마스킹되는지 검증 — "가드레일이 진짜 막는다".
"""

from __future__ import annotations

import pytest

pytest.importorskip("presidio_analyzer", reason="presidio 미설치 — 선택적 extra")

from harness_resolver.models import (
    CostTotals,
    HarnessMetadata,
    HookStep,
    ModelConfig,
    ResolvedHarness,
)
from harness_runtime import HookEngine, pii_redact_handler, presidio_redact


def test_presidio_redacts_pii():
    out = presidio_redact("Contact John Doe at john.doe@example.com.")
    assert "john.doe@example.com" not in out
    assert "<EMAIL_ADDRESS>" in out


def _resolved_with_pii_hook() -> ResolvedHarness:
    step = HookStep(
        id="pii-redact-hook", event="after_response", blocking=False,
        can_modify_request=False, can_modify_response=True,
        sandbox="restricted", failure="fail_closed", timeout_ms=1500,
    )
    return ResolvedHarness(
        metadata=HarnessMetadata(id="t"), model=ModelConfig(), permissions={},
        components=[], provided={}, hook_plan={"after_response": [step]},
        auth_needs=[], cost=CostTotals(),
    )


def test_pii_hook_masks_response_through_engine():
    """훅 엔진 관통 — pii-redact-hook 이 응답 페이로드의 PII 를 실제로 마스킹."""
    engine = HookEngine(_resolved_with_pii_hook())
    engine.register("pii-redact-hook", pii_redact_handler())
    out = engine.run("after_response", "고객 이메일은 jane@example.com 입니다.")
    assert out.allowed is True
    assert "jane@example.com" not in str(out.payload)
    assert "<EMAIL_ADDRESS>" in str(out.payload)
