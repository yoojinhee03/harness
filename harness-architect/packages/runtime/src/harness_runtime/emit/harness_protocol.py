"""HarnessProtocolEmitter — ResolvedHarness → Harness Protocol v1 `harness.yaml` (상호운용).

우리 IR 을 외부 표준 **Harness Protocol v1**(harnessprotocol.io) 포맷으로 방출한다. 같은 파일명
충돌(TASK 4)을 '거부'를 넘어 '상호운용'으로 바꾼다 — 우리 IR 을 HP 생태계(harness-kit)로 내보낸다.
손실 없는 것만 매핑하고 나머지는 losses() 로 정직 선언(환각 금지).

매핑(schema 2026-07-27 기준):
- `$schema` / `version:"1"` / `metadata{name,description}`  ← 손실 없음
- `mcp-servers{id: {transport, command/args/env | url}}`  ← McpServerSpec 그대로(stdio | streamable-http)
- `instructions.operational`  ← 합성 시스템 프롬프트(system_text)
losses: model(HP 필드 없음)·hook_plan(HP 라이프사이클 훅 없음)·skill 본문(HP skills 는 외부 ref)·
permissions scope·실행스펙 없는 mcp.
"""

from __future__ import annotations

import yaml
from harness_resolver import ResolvedHarness

from .base import FileTree, Loss

HP_SCHEMA = "https://harnessprotocol.io/schema/v1/harness.schema.json"


class HarnessProtocolEmitter:
    target = "harness-protocol"

    def emit(self, resolved: ResolvedHarness) -> FileTree:
        doc: dict[str, object] = {
            "$schema": HP_SCHEMA,
            "version": "1",
            "metadata": {"name": resolved.metadata.id, "description": resolved.metadata.name},
        }
        servers: dict[str, object] = {}
        for c in resolved.components:
            if c.type != "mcp" or c.mcp is None:
                continue  # 실행 스펙 없는 mcp 는 방출 불가(losses 로 선언)
            spec = c.mcp
            if spec.transport == "stdio":
                entry: dict[str, object] = {
                    "transport": "stdio",
                    "command": spec.command,
                    "args": list(spec.args),
                }
                if spec.env:  # 값은 카탈로그 스펙(${VAR} 권장) — 이미터는 스펙을 그대로 반영
                    entry["env"] = dict(spec.env)
            else:  # http / sse → HP 의 canonical remote transport
                entry = {"transport": "streamable-http", "url": spec.url}
            servers[c.id] = entry
        if servers:
            doc["mcp-servers"] = servers
        if resolved.prompt is not None and resolved.prompt.system_text.strip():
            doc["instructions"] = {
                "operational": resolved.prompt.system_text,
                "import-mode": "merge",
            }
        return {"harness.yaml": yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)}

    def losses(self, resolved: ResolvedHarness) -> list[Loss]:
        out: list[Loss] = []
        if resolved.model.name:
            out.append(Loss("model", "unsupported", "Harness Protocol v1 에 모델 지정 필드가 없음"))
        if resolved.hook_plan:
            out.append(
                Loss(
                    "hook_plan",
                    "unsupported",
                    "HP v1 에 실행 라이프사이클 훅이 없음(policy/permissions 는 선언적) → 훅 방출 생략",
                )
            )
        if any(c.type == "skill" for c in resolved.components):
            out.append(
                Loss(
                    "skill.body",
                    "approximate",
                    "HP skills 는 외부 SKILL.md ref(source) — 우리 인라인 스킬 본문은 방출 생략",
                )
            )
        if resolved.permissions:
            out.append(
                Loss("permissions.scope", "approximate", "HP permissions 형태가 달라 scope 매핑 생략")
            )
        if any(c.type == "mcp" and c.mcp is None for c in resolved.components):
            out.append(
                Loss("mcp.exec-spec", "unsupported", "실행 스펙 없는 mcp 는 HP mcp-servers 로 방출 불가(생략)")
            )
        return out
