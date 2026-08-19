"""스튜디오 오케스트레이터 가드레일 — 조립 실행가능성 검증 + 훅 오용 경고(Phase 14).

순수 함수 단위 테스트(네트워크·LLM 없음). 그라운딩 불변식: 실행 안 되는 조립을 저장 전에 표면화.
"""

from __future__ import annotations

from harness_api.orchestrator import _hook_misuse_warning, _tool_assemble, _validate_assembly, studio_run
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


def test_validate_assembly_warns_when_execution_uncovered_by_mcp():
    """Fix B — skill 이 access 를 스스로 provides 한다고 주장(requires 없음)해 resolver gap 은 안 뜨지만,
    실제 실행 mcp 가 없으므로 텍스트 기반 커버리지 검사가 경고해야 한다(gap 가리기 방지)."""
    from harness_api.harness_build import build_harness_yaml

    sk = Component(
        id="vlog-skill", type="skill", name="브이로그 편집 절차", version="1.0.0",
        provides=["media.edit"], capability_tags=["media.edit"],  # 스스로 provides(잘못된 주장)
        body="1. 영상 컷 2. 전환 추가 3. bgm 삽입", entrypoint="skills/vlog/SKILL.md",
    )
    val = _validate_assembly([sk], build_harness_yaml([sk], "브이로그봇"))
    assert val["gaps"] == []  # requires 없음 → resolver gap 안 뜸
    assert val["warnings"] and "MCP" in val["warnings"][0]  # 그러나 실행 커버리지 경고


def test_validate_assembly_no_exec_warning_when_mcp_covers():
    """Fix B — 절차가 요구하는 실행 능력을 실존 mcp 가 provides 하면 경고 없음(정상 조립)."""
    from harness_api.harness_build import build_harness_yaml

    sk = Component(
        id="vlog-skill", type="skill", name="브이로그 편집 절차", version="1.0.0",
        provides=[], capability_tags=[], requires=["media.edit", "media.video", "media.audio"],
        body="1. 영상 컷 2. 전환 3. bgm", entrypoint="skills/vlog/SKILL.md",
    )
    mcp = _mcp("ffmpeg-mcp", ["media.edit", "media.video", "media.audio"])
    val = _validate_assembly([sk, mcp], build_harness_yaml([sk, mcp], "브이로그봇"))
    assert val["gaps"] == [] and val["errors"] == [] and val["warnings"] == []


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


def _echo_execute(built, messages):
    """프롬프트 미리보기 executor — built.system 을 관찰하고 마지막 user 를 에코."""
    _echo_execute.seen = built.system  # type: ignore[attr-defined]
    return {"output": f"에코: {messages[-1]['content']}", "mode": "prompt"}


def test_studio_run_composes_prompt_and_runs_multiturn():
    """멀티턴 — 합성 시스템 프롬프트로 대화 히스토리를 돌린다(build→run)."""
    ctx = Component(
        id="reviewer-ctx", type="context", name="리뷰어", version="1.0.0",
        provides=["prompt.role"], capability_tags=["prompt.role"], source="inline",
        body="너는 신중한 시니어 코드 리뷰어다.",
    )
    msgs = [{"role": "user", "content": "안녕"}, {"role": "assistant", "content": "네"},
            {"role": "user", "content": "이 PR 봐줘"}]
    result = studio_run([ctx], msgs, _echo_execute)
    assert result["ok"] is True
    assert result["output"] == "에코: 이 PR 봐줘"  # 마지막 user 턴
    assert "리뷰어" in _echo_execute.seen  # type: ignore[attr-defined]
    assert result["gaps"] == [] and result["mode"] == "prompt"


def test_studio_run_reports_gap_but_still_runs():
    """실행 능력 gap 이 있어도 미리보기는 돌린다 — '무엇을 더 넣어야 하나'를 보여줌."""
    skill = Component(
        id="edit-skill", type="skill", name="편집", version="1.0.0",
        provides=["media.edit"], capability_tags=["media.edit"], requires=["media.video"],
        body="1. 컷 2. 전환", entrypoint="skills/edit/SKILL.md",
    )
    result = studio_run([skill], [{"role": "user", "content": "편집해줘"}],
                        lambda _b, _m: {"output": "ok", "mode": "prompt"})
    assert result["ok"] is True
    assert result["gaps"] == ["media.video"]
    assert result["output"] == "ok"


def test_studio_run_tool_mode_note():
    """executor 가 mode=tools 를 내면 '실제 도구 실행' 노트로 반영된다."""
    ctx = Component(id="c", type="context", name="c", version="1.0.0",
                    provides=["prompt.role"], capability_tags=["prompt.role"], source="inline", body="x")
    result = studio_run([ctx], [{"role": "user", "content": "hi"}],
                        lambda _b, _m: {"output": "done", "mode": "tools"})
    assert result["mode"] == "tools"
    assert "실제" in result["note"]


def test_studio_run_empty_drafts():
    assert studio_run([], [{"role": "user", "content": "hi"}], lambda _b, _m: {"output": "x"})["ok"] is False


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
