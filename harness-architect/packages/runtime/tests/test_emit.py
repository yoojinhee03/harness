"""eject 테스트 (Phase 5) — ResolvedHarness → Claude Code 트리 골든 스냅샷.

파일 트리 계약을 고정한다: 어떤 파일이 나오고, model/permissions/hooks/mcp 가 어떻게
매핑되며, 합성 프롬프트가 CLAUDE.md 로 가는지. 순수 함수라 동일 IR → 동일 트리.
"""

from __future__ import annotations

import json

import pytest
from harness_resolver.models import (
    CostTotals,
    HarnessMetadata,
    HookStep,
    ModelConfig,
    ResolvedComponent,
    ResolvedHarness,
    ResolvedPrompt,
)
from harness_runtime import ClaudeCodeEmitter, available_targets, emit


def make_resolved() -> ResolvedHarness:
    return ResolvedHarness(
        metadata=HarnessMetadata(id="pr-bot"),
        model=ModelConfig(name="claude-sonnet-5"),
        permissions={"vcs.code-hosting": "read-only"},
        components=[
            ResolvedComponent(id="github-mcp", type="mcp", version="1.4.0", name="GitHub", config={"repo_filter": "*"}),
        ],
        provided={},
        hook_plan={
            "before_tool_call": [
                HookStep(
                    id="secret-scan-hook", event="before_tool_call", blocking=True,
                    can_modify_request=False, can_modify_response=False,
                    sandbox="restricted", failure="fail_closed", timeout_ms=2000,
                )
            ],
            # after_request 는 Claude Code 대응이 없어 방출에서 생략돼야 한다.
            "after_request": [
                HookStep(
                    id="audit-hook", event="after_request", blocking=False,
                    can_modify_request=False, can_modify_response=False,
                    sandbox="none", failure="fail_open", timeout_ms=None,
                )
            ],
        },
        auth_needs=[],
        cost=CostTotals(),
        prompt=ResolvedPrompt(system_text="너는 시니어 리뷰어다.\n\n## 컨텍스트: 컨벤션", hash="sha256:abc"),
    )


def test_emit_claude_code_file_set() -> None:
    tree = emit(make_resolved(), "claude-code")
    assert set(tree) == {"CLAUDE.md", ".mcp.json", ".claude/settings.json"}


def test_claude_md_is_composed_prompt() -> None:
    tree = emit(make_resolved(), "claude-code")
    md = tree["CLAUDE.md"]
    assert "harness-architect 생성" in md  # 헤더
    assert "너는 시니어 리뷰어다." in md and "## 컨텍스트: 컨벤션" in md


def test_settings_model_permissions_hooks() -> None:
    settings = json.loads(emit(make_resolved(), "claude-code")[".claude/settings.json"])
    assert settings["model"] == "claude-sonnet-5"
    assert settings["permissions"]["allow"] == ["mcp__github-mcp"]
    # before_tool_call → PreToolUse ; after_request 는 미대응이라 방출 안 됨
    assert "PreToolUse" in settings["hooks"]
    assert "Stop" not in settings["hooks"] and "PostToolUse" not in settings["hooks"]
    entry = settings["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "*"
    assert "secret-scan-hook" in entry["hooks"][0]["command"]


def test_mcp_json_lists_servers() -> None:
    mcp = json.loads(emit(make_resolved(), "claude-code")[".mcp.json"])
    assert "github-mcp" in mcp["mcpServers"]


def test_no_mcp_omits_mcp_json() -> None:
    r = make_resolved()
    r.components = []  # MCP 없음
    tree = emit(r, "claude-code")
    assert ".mcp.json" not in tree
    assert "CLAUDE.md" in tree and ".claude/settings.json" in tree


def test_emit_is_deterministic() -> None:
    assert emit(make_resolved(), "claude-code") == emit(make_resolved(), "claude-code")


def test_unknown_target_raises() -> None:
    with pytest.raises(ValueError):
        emit(make_resolved(), "cursor")  # 아직 미지원


def test_available_targets() -> None:
    assert "claude-code" in available_targets()
    assert ClaudeCodeEmitter.target == "claude-code"
