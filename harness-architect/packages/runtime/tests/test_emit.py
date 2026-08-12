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
    McpServerSpec,
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
            ResolvedComponent(
                id="github-mcp", type="mcp", version="1.4.0", name="GitHub", config={"repo_filter": "*"},
                mcp=McpServerSpec(
                    transport="stdio",
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-github"],
                    env={"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"},
                ),
            ),
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


def test_mcp_json_emits_real_stdio_spec() -> None:
    """실행 스펙이 있으면 자리표시가 아니라 그대로 도는 stdio 엔트리를 방출한다."""
    entry = json.loads(emit(make_resolved(), "claude-code")[".mcp.json"])["mcpServers"]["github-mcp"]
    assert entry["command"] == "npx"
    assert entry["args"] == ["-y", "@modelcontextprotocol/server-github"]
    assert entry["env"] == {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"}
    assert "TODO" not in json.dumps(entry)  # 자리표시가 남아있지 않음


def test_mcp_json_http_transport() -> None:
    """http/sse transport 는 type+url 형태로 방출한다."""
    r = make_resolved()
    r.components = [
        ResolvedComponent(
            id="remote-mcp", type="mcp", version="1.0.0", name="Remote",
            mcp=McpServerSpec(transport="http", url="https://example.com/mcp"),
        )
    ]
    entry = json.loads(emit(r, "claude-code")[".mcp.json"])["mcpServers"]["remote-mcp"]
    assert entry == {"type": "http", "url": "https://example.com/mcp"}


def test_mcp_json_missing_spec_is_honest_placeholder() -> None:
    """실행 스펙이 없는 컴포넌트는 (환각 대신) 정직한 TODO 자리표시로 남는다."""
    r = make_resolved()
    r.components = [ResolvedComponent(id="mystery-mcp", type="mcp", version="0.1.0", name="Mystery")]
    entry = json.loads(emit(r, "claude-code")[".mcp.json"])["mcpServers"]["mystery-mcp"]
    assert "TODO" in entry["command"]


def test_hook_emit_command_used_when_present() -> None:
    """훅에 emit_command 가 있으면 자리표시 대신 그 실제 명령을 방출한다."""
    r = make_resolved()
    r.hook_plan["before_tool_call"][0].emit_command = "grep -qiE 'secret' && exit 2 || exit 0"
    settings = json.loads(emit(r, "claude-code")[".claude/settings.json"])
    cmd = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert cmd == "grep -qiE 'secret' && exit 2 || exit 0"
    assert "echo '[harness]" not in cmd  # 자리표시가 아님


def test_hook_placeholder_when_no_emit_command() -> None:
    """emit_command 가 없는 훅(인프로세스 핸들러)은 정직한 자리표시로 남는다."""
    settings = json.loads(emit(make_resolved(), "claude-code")[".claude/settings.json"])
    cmd = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "[harness]" in cmd and "secret-scan-hook" in cmd


def test_no_mcp_omits_mcp_json() -> None:
    r = make_resolved()
    r.components = []  # MCP 없음
    tree = emit(r, "claude-code")
    assert ".mcp.json" not in tree
    assert "CLAUDE.md" in tree and ".claude/settings.json" in tree


def test_emit_subagent_files() -> None:
    """멀티에이전트 팀 → Claude Code 서브에이전트 파일(.claude/agents/<name>.md)."""
    from harness_resolver.models import ResolvedPrompt, ResolvedSubAgent

    r = make_resolved()
    r.subagents = [
        ResolvedSubAgent(
            name="reviewer", description="코드 리뷰 역할",
            prompt=ResolvedPrompt(system_text="너는 리뷰어다.", hash="sha256:x"),
        )
    ]
    tree = emit(r, "claude-code")
    assert ".claude/agents/reviewer.md" in tree
    md = tree[".claude/agents/reviewer.md"]
    assert md.startswith("---\nname: reviewer")
    assert "코드 리뷰 역할" in md and "너는 리뷰어다." in md


def test_emit_is_deterministic() -> None:
    assert emit(make_resolved(), "claude-code") == emit(make_resolved(), "claude-code")


def test_unknown_target_raises() -> None:
    with pytest.raises(ValueError):
        emit(make_resolved(), "does-not-exist")  # 미등록 타깃


def test_available_targets() -> None:
    targets = available_targets()
    assert "claude-code" in targets and "cursor" in targets
    assert ClaudeCodeEmitter.target == "claude-code"


# ─────────────────────────── Cursor 타깃 (이식성) ───────────────────────────


def test_cursor_file_set() -> None:
    tree = emit(make_resolved(), "cursor")
    assert set(tree) == {".cursor/rules/harness.mdc", ".cursor/mcp.json"}


def test_cursor_rule_has_frontmatter_and_prompt() -> None:
    mdc = emit(make_resolved(), "cursor")[".cursor/rules/harness.mdc"]
    assert mdc.startswith("---\n") and "alwaysApply: true" in mdc
    assert "너는 시니어 리뷰어다." in mdc  # 합성 프롬프트가 그대로 들어감


def test_cursor_mcp_matches_claude_code_format() -> None:
    """단일 IR → 두 런타임의 mcpServers 는 동일 포맷(공용 헬퍼)."""
    cursor_mcp = json.loads(emit(make_resolved(), "cursor")[".cursor/mcp.json"])
    claude_mcp = json.loads(emit(make_resolved(), "claude-code")[".mcp.json"])
    assert cursor_mcp == claude_mcp
    assert cursor_mcp["mcpServers"]["github-mcp"]["command"] == "npx"


def test_cursor_omits_mcp_when_none() -> None:
    r = make_resolved()
    r.components = []
    tree = emit(r, "cursor")
    assert ".cursor/mcp.json" not in tree
    assert ".cursor/rules/harness.mdc" in tree
