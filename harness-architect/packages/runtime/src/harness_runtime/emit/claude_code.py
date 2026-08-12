"""ClaudeCodeEmitter — ResolvedHarness → Claude Code `.claude/` 프로젝트 트리.

방출물:
- `CLAUDE.md`             ← 시스템 레이어(context·authored) + MCP Capabilities(usage_note). skill 본문은 제외.
- `.claude/skills/<id>/SKILL.md` ← skill 컴포넌트마다 네이티브 Agent Skill(frontmatter + body)로 분리 방출
- `.mcp.json`            ← MCP 컴포넌트 → mcpServers (실행 스펙 있으면 그대로 도는 형태, 없으면 자리표시 — MAPPING.md)
- `.claude/settings.json` ← model · permissions(allow) · hooks(이벤트 매핑)

손실/근사 지점은 MAPPING.md 에 표로 정리한다. 순수 함수(동일 IR → 동일 트리)라 골든
스냅샷으로 계약을 고정한다.
"""

from __future__ import annotations

import json

from harness_resolver import ResolvedHarness
from harness_resolver.models import HookStep, ResolvedComponent, ResolvedSubAgent

from .base import FileTree, mcp_servers_json

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
        mcp = mcp_servers_json(resolved)  # 공용 헬퍼(Cursor 와 동일 포맷)
        if mcp is not None:
            tree[".mcp.json"] = mcp
        tree[".claude/settings.json"] = self._settings_json(resolved)
        # 멀티에이전트 팀 → Claude Code 서브에이전트 파일(.claude/agents/<name>.md)
        for sub in resolved.subagents:
            tree[f".claude/agents/{sub.name}.md"] = self._agent_md(sub)
        # skill 컴포넌트 → 네이티브 Agent Skill 파일(.claude/skills/<id>/SKILL.md).
        # 본문은 CLAUDE.md 에 합치지 않고 각 스킬 파일로 분리한다(모델이 필요 시 로드).
        for comp in resolved.components:
            if comp.type == "skill":
                tree[f".claude/skills/{comp.id}/SKILL.md"] = self._skill_md(comp)
        return tree

    # ── .claude/skills/<id>/SKILL.md ← skill 본문(네이티브 Agent Skill) ──
    def _skill_md(self, comp: ResolvedComponent) -> str:
        desc = (comp.summary or comp.name).replace("\n", " ").strip()
        frontmatter = "\n".join(["---", f"name: {comp.id}", f"description: {desc}", "---"])
        body = (comp.body or "").strip()
        return f"{frontmatter}\n\n# {comp.name}\n\n{body}\n" if body else f"{frontmatter}\n\n# {comp.name}\n"

    def _agent_md(self, sub: ResolvedSubAgent) -> str:
        system = sub.prompt.system_text if sub.prompt is not None else ""
        frontmatter = "\n".join(["---", f"name: {sub.name}", f"description: {sub.description}", "---"])
        return f"{frontmatter}\n\n{system}\n"

    # ── CLAUDE.md ← 시스템 레이어(context·authored) + MCP Capabilities ──
    # skill 본문은 여기 합치지 않고 각자 SKILL.md 로 분리한다(위 emit 참조).
    def _claude_md(self, resolved: ResolvedHarness) -> str:
        header = f"<!-- harness-architect 생성 · id={resolved.metadata.id} · 편집 시 재-eject 로 덮어씀 -->"
        parts = [header, self._system_layer(resolved), self._capabilities_section(resolved)]
        return "\n\n".join(p for p in parts if p) + "\n"

    def _system_layer(self, resolved: ResolvedHarness) -> str:
        """합성 프롬프트에서 skill 기여 세그먼트를 뺀 시스템 레이어(context·authored).

        skill 분리는 provenance(segments)로 판단한다. segments 가 없으면(직접 조립된 프롬프트)
        필터할 근거가 없으므로 system_text 를 통째로 쓴다(하위호환). 실제 resolve() 는 항상 채운다.
        """
        prompt = resolved.prompt
        if prompt is None:
            return ""
        if not prompt.segments:
            return prompt.system_text
        skill_sources = {f"component:{c.id}" for c in resolved.components if c.type == "skill"}
        return "\n\n".join(seg.text for seg in prompt.segments if seg.source not in skill_sources)

    def _capabilities_section(self, resolved: ResolvedHarness) -> str:
        """MCP 상위 사용 지침(usage_note) → 'Capabilities' 절. 도구별 description 은 서버 몫."""
        notes = [c for c in resolved.components if c.type == "mcp" and c.usage_note]
        if not notes:
            return ""
        lines = ["## Capabilities — 연결된 MCP 사용 지침"]
        lines += [f"- **{c.name}** (`{c.id}`): {(c.usage_note or '').strip()}" for c in notes]
        return "\n".join(lines)

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
            entries = [{"type": "command", "command": self._hook_command(s)} for s in steps]
            out[cc_event] = [{"matcher": "*", "hooks": entries}]
        return out

    def _hook_command(self, s: HookStep) -> str:
        """훅의 셸 명령. 카탈로그에 emit_command 가 있으면 그걸, 없으면 정직한 자리표시."""
        if s.emit_command:
            return s.emit_command
        # 셸 명령 스펙이 없는 훅(인프로세스 핸들러) → 자리표시(교체 필요, MAPPING.md).
        return (
            f"echo '[harness] {s.id} (blocking={s.blocking}, sandbox={s.sandbox}, "
            f"timeout={s.timeout_ms}ms) — 실제 명령/핸들러로 교체'"
        )
