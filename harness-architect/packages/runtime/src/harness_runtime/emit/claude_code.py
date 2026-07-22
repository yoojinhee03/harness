"""ClaudeCodeEmitter — ResolvedHarness → Claude Code `.claude/` 프로젝트 트리.

방출물:
- `CLAUDE.md`             ← 합성된 시스템 프롬프트(`resolved.prompt.system_text`, Phase 10)
- `.mcp.json`            ← MCP 컴포넌트 → mcpServers (실행 스펙은 자리표시 — MAPPING.md)
- `.claude/settings.json` ← model · permissions(allow) · hooks(이벤트 매핑)

손실/근사 지점은 MAPPING.md 에 표로 정리한다. 순수 함수(동일 IR → 동일 트리)라 골든
스냅샷으로 계약을 고정한다.
"""

from __future__ import annotations

import json

from harness_resolver import ResolvedHarness

from .base import FileTree

# 하네스 훅 이벤트 → Claude Code 훅 이벤트 (근사; MAPPING.md 참조).
# after_request 는 Claude Code 대응이 없어 방출을 생략한다.
_HOOK_EVENT_MAP = {
    "before_tool_call": "PreToolUse",
    "after_tool_call": "PostToolUse",
    "before_request": "UserPromptSubmit",
    "after_response": "Stop",
}


class ClaudeCodeEmitter:
    target = "claude-code"

    def emit(self, resolved: ResolvedHarness) -> FileTree:
        tree: FileTree = {"CLAUDE.md": self._claude_md(resolved)}
        mcp = self._mcp_json(resolved)
        if mcp is not None:
            tree[".mcp.json"] = mcp
        tree[".claude/settings.json"] = self._settings_json(resolved)
        return tree

    # ── CLAUDE.md ← 합성 시스템 프롬프트 (context·skill·authored 레이어를 모두 담는다) ──
    def _claude_md(self, resolved: ResolvedHarness) -> str:
        system = resolved.prompt.system_text if resolved.prompt is not None else ""
        header = f"<!-- harness-architect 생성 · id={resolved.metadata.id} · 편집 시 재-eject 로 덮어씀 -->"
        return f"{header}\n\n{system}\n"

    # ── .mcp.json ← MCP 컴포넌트 ──
    def _mcp_json(self, resolved: ResolvedHarness) -> str | None:
        servers: dict[str, object] = {}
        for c in resolved.components:
            if c.type == "mcp":
                servers[c.id] = {
                    # 카탈로그엔 실행 스펙(command/url)이 없어 자리표시 — 채워야 함(MAPPING.md).
                    "command": f"TODO: {c.id} 실행 명령/URL",
                    "args": [],
                }
        if not servers:
            return None
        return json.dumps({"mcpServers": servers}, indent=2, ensure_ascii=False) + "\n"

    # ── .claude/settings.json ← model · permissions · hooks ──
    def _settings_json(self, resolved: ResolvedHarness) -> str:
        allow = [f"mcp__{c.id}" for c in resolved.components if c.type == "mcp"]
        settings: dict[str, object] = {
            "model": resolved.model.name,
            # 하네스 permissions 는 capability→scope(예: read-only). Claude Code 는 도구 단위라
            # 스코프는 근사 소실되고, MCP 서버 허용으로만 표현한다(MAPPING.md).
            "permissions": {"allow": allow, "deny": []},
        }
        hooks = self._hooks(resolved)
        if hooks:
            settings["hooks"] = hooks
        return json.dumps(settings, indent=2, ensure_ascii=False) + "\n"

    def _hooks(self, resolved: ResolvedHarness) -> dict[str, object]:
        out: dict[str, object] = {}
        for event, steps in resolved.hook_plan.items():
            cc_event = _HOOK_EVENT_MAP.get(event)
            if cc_event is None:
                continue  # after_request 등 미대응 이벤트는 생략(MAPPING.md)
            entries = [
                {
                    "type": "command",
                    # 하네스 훅은 샌드박스 핸들러라 셸 명령이 없다 → 자리표시(교체 필요).
                    "command": (
                        f"echo '[harness] {s.id} "
                        f"(blocking={s.blocking}, sandbox={s.sandbox}, timeout={s.timeout_ms}ms) "
                        f"— 실제 명령으로 교체'"
                    ),
                }
                for s in steps
            ]
            out[cc_event] = [{"matcher": "*", "hooks": entries}]
        return out
