"""CursorEmitter — ResolvedHarness → Cursor `.cursor/` 트리 (Phase 5 / 이식성).

같은 IR 을 Cursor 네이티브 포맷으로 방출해 "단일 IR → 여러 런타임" 을 실증한다.

방출물:
- `.cursor/rules/harness.mdc` ← 합성 시스템 프롬프트(`resolved.prompt.system_text`).
  Cursor 규칙 파일(.mdc)은 frontmatter 로 적용 범위를 정한다 — `alwaysApply: true` 로 항상 주입.
- `.cursor/mcp.json`         ← MCP 컴포넌트(Claude Code 와 동일 `mcpServers` 포맷, 공용 헬퍼 재사용).

손실 지점(MAPPING.md): Cursor 는 훅(라이프사이클 커맨드)·모델 지정·권한 스코프의 네이티브
대응이 없다 → 훅/model/permissions 는 방출을 생략한다(자유 생성 아님, 명시적 소실).
순수 함수(동일 IR → 동일 트리)라 골든 스냅샷으로 계약을 고정한다.
"""

from __future__ import annotations

from harness_resolver import ResolvedHarness

from .base import FileTree, Loss, mcp_servers_json


class CursorEmitter:
    target = "cursor"

    def emit(self, resolved: ResolvedHarness) -> FileTree:
        tree: FileTree = {".cursor/rules/harness.mdc": self._rule(resolved)}
        mcp = mcp_servers_json(resolved)  # Claude Code 와 동일 포맷 — 공용 헬퍼
        if mcp is not None:
            tree[".cursor/mcp.json"] = mcp
        return tree

    def losses(self, resolved: ResolvedHarness) -> list[Loss]:
        """Cursor 방출 손실 — 훅·모델·권한의 네이티브 대응이 없다(MAPPING.md, IR 기준 트리거)."""
        out: list[Loss] = []
        if resolved.hook_plan:
            n = sum(len(v) for v in resolved.hook_plan.values())
            out.append(
                Loss(
                    "hook_plan",
                    "unsupported",
                    f"Cursor 라이프사이클 훅 네이티브 대응 없음 → 훅 {n}개 전부 생략(가드레일 소실)",
                )
            )
        if resolved.model.name:
            out.append(
                Loss("model.name", "unsupported", "Cursor 는 모델을 UI 에서 선택 → settings 필드 아님")
            )
        if resolved.permissions:
            out.append(
                Loss("permissions", "unsupported", "Cursor 도구 단위 허용 대응 없음 → 생략")
            )
        return out

    def _rule(self, resolved: ResolvedHarness) -> str:
        system = resolved.prompt.system_text if resolved.prompt is not None else ""
        # .mdc frontmatter — alwaysApply 로 세션 내내 규칙을 주입한다(Claude Code 의 CLAUDE.md 대응).
        frontmatter = "\n".join(
            [
                "---",
                f"description: harness-architect 생성 · id={resolved.metadata.id} (편집 시 재-eject 로 덮어씀)",
                "alwaysApply: true",
                "---",
            ]
        )
        return f"{frontmatter}\n\n{system}\n"
