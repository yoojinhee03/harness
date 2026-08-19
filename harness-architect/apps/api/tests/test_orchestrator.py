"""스튜디오 오케스트레이터 가드레일 — 조립 실행가능성 검증 + 훅 오용 경고(Phase 14).

순수 함수 단위 테스트(네트워크·LLM 없음). 그라운딩 불변식: 실행 안 되는 조립을 저장 전에 표면화.
"""

from __future__ import annotations

from harness_api.orchestrator import _hook_misuse_warning, _tool_assemble, _validate_assembly
from harness_resolver import Component


def _skill(cid: str, provides: list[str], requires: list[str]) -> Component:
    return Component(
        id=cid, type="skill", name=cid, version="1.0.0",
        provides=provides, capability_tags=provides, requires=requires,
        body="step 1", entrypoint=f"skills/{cid}/SKILL.md",
    )


def _mcp(cid: str, provides: list[str]) -> Component:
    from harness_resolver.models import McpServerSpec

    return Component(
        id=cid, type="mcp", name=cid, version="1.0.0",
        provides=provides, capability_tags=provides,
        mcp=McpServerSpec(transport="stdio", command="npx", args=["-y", "srv"]),
    )


def test_validate_assembly_flags_unmet_requires_as_gap():
    """편집 skill 이 media 접근을 requires 하는데 그 MCP 를 안 넣으면 gap(hollow 조립)."""
    from harness_api.harness_build import build_harness_yaml

    comps = [_skill("edit-skill", ["media.edit"], ["media.video"])]
    val = _validate_assembly(comps, build_harness_yaml(comps, "편집봇"))
    assert val["gaps"] == ["media.video"]
    assert val["errors"] == []


def test_validate_assembly_passes_when_requires_satisfied():
    from harness_api.harness_build import build_harness_yaml

    comps = [_skill("edit-skill", ["media.edit"], ["media.video"]), _mcp("video-mcp", ["media.video"])]
    val = _validate_assembly(comps, build_harness_yaml(comps, "편집봇"))
    assert val["gaps"] == [] and val["errors"] == []


def test_tool_assemble_surfaces_gap_in_summary_and_harness():
    holder = {"components": [_skill("edit-skill", ["media.edit"], ["media.video"])], "harness": None}
    summary, events = _tool_assemble(holder, {"name": "편집봇"})
    assert "gap" in summary and "media.video" in summary
    assert "실존 MCP" in summary  # 지어내지 말고 실존 도구 찾으라는 안내
    harness = events[0]["harness"]
    assert harness["gaps"] == ["media.video"]


def test_tool_assemble_clean_when_executable():
    holder = {
        "components": [_skill("s", ["media.edit"], ["media.video"]), _mcp("m", ["media.video"])],
        "harness": None,
    }
    summary, events = _tool_assemble(holder, {"name": "봇"})
    assert "실행가능성 검증 통과" in summary
    assert events[0]["harness"]["gaps"] == []


def test_hook_misuse_warning_on_non_lifecycle_provides():
    hook = Component(
        id="fake-hook", type="hook", name="가짜훅", version="1.0.0",
        provides=["review.code"], events=["before_tool_call"], failure="fail_open", timeout_ms=500,
    )
    warn = _hook_misuse_warning(hook)
    assert warn is not None and "review.code" in warn
    # lifecycle 능력만 provides 하는 정상 훅은 경고 없음
    ok = Component(
        id="ok-hook", type="hook", name="정상훅", version="1.0.0",
        provides=["lifecycle.guardrail"], events=["before_tool_call"], failure="fail_closed", timeout_ms=500,
    )
    assert _hook_misuse_warning(ok) is None
