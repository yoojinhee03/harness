"""프롬프트 합성 테스트 (Phase 10) — 자체 완결형(카탈로그 자산 비의존).

합성·변수 치환·dedup/충돌·예산·provenance·hash 와, prompt 블록이 없을 때 기존 컴포넌트
조립과 동치임을 고정한다. 설계: docs/plan/10-prompt-management.md.
"""

from __future__ import annotations

import pytest
from harness_resolver import (
    Component,
    ComponentSelection,
    Cost,
    HarnessConfig,
    HarnessMetadata,
    InMemoryRegistry,
    PromptCompose,
    PromptLayer,
    PromptSpec,
    PromptVariable,
    ResolvedComponent,
    component_segment_text,
    estimate_tokens,
    merge_harness_configs,
    resolve,
)
from pydantic import ValidationError

# ─────────────────────────── 픽스처 ───────────────────────────


def ctx_component() -> Component:
    return Component(
        id="conv", type="context", name="컨벤션", version="1.0.0",
        cost=Cost(context_tokens=1200), provides=["convention.coding"],
        source="file", refresh="static",
    )


def skill_component() -> Component:
    return Component(
        id="pr", type="skill", name="PR 리뷰", version="2.1.0",
        provides=["review.code"], entrypoint="skills/pr/SKILL.md", injection_mode="context",
    )


def role_fragment() -> Component:
    """prompt.system[].ref 로 주입되는 프롬프트 조각 — context facet + body 텍스트."""
    return Component(
        id="role-reviewer", type="context", name="시니어 리뷰어 역할", version="1.0.0",
        capability_tags=["prompt.role"], source="inline", refresh="static",
        body="너는 신중한 시니어 코드 리뷰어다.",
    )


@pytest.fixture
def registry() -> InMemoryRegistry:
    return InMemoryRegistry([ctx_component(), skill_component(), role_fragment()])


def cfg(*, refs: list[str] | None = None, prompt: PromptSpec | None = None) -> HarnessConfig:
    return HarnessConfig(
        metadata=HarnessMetadata(id="t"),
        components=[ComponentSelection(ref=r) for r in (refs or [])],
        prompt=prompt,
    )


# ─────────────────────────── 동치: prompt 블록 없음 ───────────────────────────


def test_no_prompt_block_equivalent_to_component_assembly(registry: InMemoryRegistry) -> None:
    """prompt 블록이 없으면 컴포넌트(context→skill) 기여만 합성 — 기존 조립과 글자까지 동치."""
    result = resolve(cfg(refs=["conv@1.0.0", "pr@2.1.0"]), registry)
    assert result.ok
    assert result.resolved is not None
    rp = result.resolved.prompt
    assert rp is not None

    expected = (
        "## 컨텍스트: 컨벤션 (conv)\n[주입된 컨텍스트 — config={}]"
        "\n\n"
        "## 스킬 절차: PR 리뷰 (pr)\n[주입된 절차 — config={}]"
    )
    assert rp.system_text == expected
    assert [s.source for s in rp.segments] == ["component:conv", "component:pr"]
    assert rp.hash.startswith("sha256:")


# ─────────────────────────── authored 레이어 순서·provenance ───────────────────────────


def test_inline_layers_precede_components(registry: InMemoryRegistry) -> None:
    spec = PromptSpec(system=[PromptLayer(inline="너는 리뷰어다.")])
    result = resolve(cfg(refs=["conv@1.0.0"], prompt=spec), registry)
    rp = result.resolved.prompt  # type: ignore[union-attr]
    assert rp is not None
    assert rp.segments[0].source == "inline" and rp.segments[0].layer == 0
    assert rp.segments[1].source == "component:conv" and rp.segments[1].layer == 1
    assert rp.system_text.index("너는 리뷰어다.") < rp.system_text.index("컨벤션")


# ─────────────────────────── 변수 치환 + 미해결 ───────────────────────────


def test_variable_substitution_and_unresolved(registry: InMemoryRegistry) -> None:
    spec = PromptSpec(
        system=[PromptLayer(inline="프로젝트 {{project}}, 스타일 {{style}}")],
        variables={"style": PromptVariable(default="google"), "project": PromptVariable(required=True)},
    )
    result = resolve(cfg(prompt=spec), registry)
    rp = result.resolved.prompt  # type: ignore[union-attr]
    assert rp is not None
    assert "스타일 google" in rp.system_text
    assert "{{project}}" in rp.system_text  # 값 없는 참조는 placeholder 유지
    assert rp.variables_resolved == {"style": "google"}

    unresolved = [d for d in result.diagnostics.warnings if d.code == "unresolved_variable"]
    assert [d.detail["variable"] for d in unresolved] == ["project"]


def test_component_segment_uses_body_when_present() -> None:
    """body 가 있으면 실제 텍스트를, 없으면 자리표시를 쓴다(CLAUDE.md 본문 실화)."""
    ctx = ResolvedComponent(id="conv", type="context", version="1.0.0", name="컨벤션", body="네이밍은 snake_case")
    assert component_segment_text(ctx) == "## 컨텍스트: 컨벤션 (conv)\n네이밍은 snake_case"

    skill_no_body = ResolvedComponent(id="pr", type="skill", version="2.1.0", name="리뷰")
    seg = component_segment_text(skill_no_body)
    assert seg is not None and "[주입된 절차" in seg  # 자리표시 폴백

    mcp = ResolvedComponent(id="gh", type="mcp", version="1.0.0", name="GitHub")
    assert component_segment_text(mcp) is None  # skill/context 만 프롬프트 기여


def test_required_variable_without_value_warns(registry: InMemoryRegistry) -> None:
    """required=True 인데 값이 없으면 경고(required_variable_unset) — 필드가 실제로 동작."""
    spec = PromptSpec(
        system=[PromptLayer(inline="고정 지시")],  # project 를 참조하지 않아도 required 는 검사됨
        variables={"project": PromptVariable(required=True)},
    )
    result = resolve(cfg(prompt=spec), registry)
    codes = {d.code for d in result.diagnostics.warnings}
    assert "required_variable_unset" in codes


def test_variable_type_mismatch_warns(registry: InMemoryRegistry) -> None:
    """default 값이 선언 타입과 다르면 경고(variable_type_mismatch)."""
    spec = PromptSpec(
        system=[PromptLayer(inline="n={{n}}")],
        variables={"n": PromptVariable(type="number", default="not-a-number")},
    )
    result = resolve(cfg(prompt=spec), registry)
    warn = [d for d in result.diagnostics.warnings if d.code == "variable_type_mismatch"]
    assert [d.detail["variable"] for d in warn] == ["n"]


def test_valid_typed_variable_no_warning(registry: InMemoryRegistry) -> None:
    """타입이 맞으면 type 경고가 없다(오탐 방지)."""
    spec = PromptSpec(
        system=[PromptLayer(inline="n={{n}}, ok={{ok}}")],
        variables={
            "n": PromptVariable(type="number", default=3),
            "ok": PromptVariable(type="boolean", default=True),
        },
    )
    result = resolve(cfg(prompt=spec), registry)
    assert not [d for d in result.diagnostics.warnings if d.code == "variable_type_mismatch"]


# ─────────────────────────── dedup / 충돌 정책 ───────────────────────────


def test_dedup_keeps_first_and_warns(registry: InMemoryRegistry) -> None:
    spec = PromptSpec(system=[PromptLayer(inline="같은 지시"), PromptLayer(inline="같은 지시")])
    result = resolve(cfg(prompt=spec), registry)
    rp = result.resolved.prompt  # type: ignore[union-attr]
    assert rp is not None
    assert rp.system_text == "같은 지시"
    assert len(rp.segments) == 1
    assert any(d.code == "duplicate_prompt_segment" for d in result.diagnostics.warnings)


def test_dedup_on_conflict_error_blocks(registry: InMemoryRegistry) -> None:
    spec = PromptSpec(
        system=[PromptLayer(inline="x"), PromptLayer(inline="x")],
        compose=PromptCompose(on_conflict="error"),
    )
    result = resolve(cfg(prompt=spec), registry)
    assert result.ok is False
    assert any(d.code == "duplicate_prompt_segment" for d in result.diagnostics.errors)


def test_dedup_last_wins_reorders(registry: InMemoryRegistry) -> None:
    spec = PromptSpec(
        system=[PromptLayer(inline="dup"), PromptLayer(ref="role-reviewer@1.0.0"), PromptLayer(inline="dup")],
        compose=PromptCompose(on_conflict="last_wins"),
    )
    result = resolve(cfg(prompt=spec), registry)
    rp = result.resolved.prompt  # type: ignore[union-attr]
    assert rp is not None
    # 첫 dup 제거 후 끝에 재배치 → [role fragment, dup]
    assert [s.source for s in rp.segments] == ["prompt:role-reviewer@1.0.0", "inline"]
    assert rp.system_text == "너는 신중한 시니어 코드 리뷰어다.\n\ndup"


# ─────────────────────────── 예산 ───────────────────────────


def test_budget_exceeded_warns(registry: InMemoryRegistry) -> None:
    spec = PromptSpec(system=[PromptLayer(inline="가" * 100)], compose=PromptCompose(budget_tokens=5))
    result = resolve(cfg(prompt=spec), registry)
    assert any(d.code == "prompt_budget_exceeded" for d in result.diagnostics.warnings)


# ─────────────────────────── ref 조각 / 미지 ───────────────────────────


def test_ref_fragment_body_and_unknown(registry: InMemoryRegistry) -> None:
    spec = PromptSpec(system=[PromptLayer(ref="role-reviewer@1.0.0"), PromptLayer(ref="missing@1.0.0")])
    result = resolve(cfg(prompt=spec), registry)
    rp = result.resolved.prompt  # type: ignore[union-attr]
    assert rp is not None
    assert "너는 신중한 시니어 코드 리뷰어다." in rp.system_text
    assert [s.source for s in rp.segments] == ["prompt:role-reviewer@1.0.0"]  # missing 은 스킵
    assert any(d.code == "unknown_prompt_fragment" for d in result.diagnostics.warnings)


# ─────────────────────────── hash 결정성 ───────────────────────────


def test_hash_is_deterministic_and_content_addressed(registry: InMemoryRegistry) -> None:
    r1 = resolve(cfg(prompt=PromptSpec(system=[PromptLayer(inline="안정")])), registry)
    r2 = resolve(cfg(prompt=PromptSpec(system=[PromptLayer(inline="안정")])), registry)
    r3 = resolve(cfg(prompt=PromptSpec(system=[PromptLayer(inline="변경")])), registry)
    h1 = r1.resolved.prompt.hash  # type: ignore[union-attr]
    assert h1 == r2.resolved.prompt.hash  # type: ignore[union-attr]
    assert h1 != r3.resolved.prompt.hash  # type: ignore[union-attr]


# ─────────────────────────── 모델 검증 / 유틸 ───────────────────────────


def test_prompt_layer_requires_exactly_one_of_ref_inline() -> None:
    with pytest.raises(ValidationError):
        PromptLayer()  # 둘 다 없음
    with pytest.raises(ValidationError):
        PromptLayer(ref="a@1.0.0", inline="b")  # 둘 다 있음


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 10) == 3  # (10+3)//4


# ─────────────────────────── extends 병합에서 prompt 전달 ───────────────────────────


def test_extends_passes_prompt_through_merge() -> None:
    base = HarnessConfig(
        metadata=HarnessMetadata(id="base"),
        prompt=PromptSpec(system=[PromptLayer(inline="base 지시")]),
    )
    # 자식에 prompt 없음 → base 의 prompt 를 물려받는다.
    merged = merge_harness_configs(base, HarnessConfig(metadata=HarnessMetadata(id="c1")))
    assert merged.prompt is not None
    assert merged.prompt.system[0].inline == "base 지시"

    # 자식에 prompt 있음 → 자식이 이긴다(전체 교체).
    child = HarnessConfig(
        metadata=HarnessMetadata(id="c2"),
        prompt=PromptSpec(system=[PromptLayer(inline="child 지시")]),
    )
    merged2 = merge_harness_configs(base, child)
    assert merged2.prompt is not None
    assert merged2.prompt.system[0].inline == "child 지시"
