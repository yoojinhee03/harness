"""Emitter 프로토콜 + 타깃 공용 헬퍼 — 설계: 진행 플랜 Phase 5 (다중 런타임 컴파일).

`ResolvedHarness`(검증된 IR)를 각 에이전트 런타임의 네이티브 파일 트리로 방출한다.
타깃별 Emitter 는 이 프로토콜만 만족하면 되고, 추가는 가법적이다(dispatch 는 emit/__init__).

MCP `mcpServers` 직렬화는 Claude Code(.mcp.json)·Cursor(.cursor/mcp.json)가 **동일 포맷**을
쓰므로 여기 공용 함수로 둔다(단일 IR → 여러 런타임에서 같은 조립 재사용).
"""

from __future__ import annotations

import json
from typing import Protocol

from harness_resolver import ResolvedComponent, ResolvedHarness

# 상대경로 → 파일 내용. 디스크 쓰기(CLI)·아카이브 반환(API)이 모두 이 형태를 소비한다.
FileTree = dict[str, str]


class Emitter(Protocol):
    target: str

    def emit(self, resolved: ResolvedHarness) -> FileTree: ...


def mcp_entry(c: ResolvedComponent) -> dict[str, object]:
    """단일 MCP 서버 엔트리 — 실행 스펙(transport)에 맞는 표준 `.mcp.json` 형태."""
    spec = c.mcp
    if spec is None:
        # 실행 스펙이 없는 컴포넌트 — 정직한 자리표시(교체 필요, MAPPING.md).
        return {"command": f"TODO: {c.id} 실행 스펙을 카탈로그에 추가하세요", "args": []}
    if spec.transport == "stdio":
        entry: dict[str, object] = {"command": spec.command, "args": list(spec.args)}
        if spec.env:
            entry["env"] = dict(spec.env)
        return entry
    # http / sse — 원격 엔드포인트
    return {"type": spec.transport, "url": spec.url}


def mcp_servers_json(resolved: ResolvedHarness) -> str | None:
    """`{"mcpServers": {...}}` JSON 문자열(MCP 컴포넌트 없으면 None). Claude Code·Cursor 공용."""
    servers: dict[str, object] = {c.id: mcp_entry(c) for c in resolved.components if c.type == "mcp"}
    if not servers:
        return None
    return json.dumps({"mcpServers": servers}, indent=2, ensure_ascii=False) + "\n"
