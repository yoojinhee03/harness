"""Emitter 프로토콜 + 타깃 공용 헬퍼 — 설계: 진행 플랜 Phase 5 (다중 런타임 컴파일).

`ResolvedHarness`(검증된 IR)를 각 에이전트 런타임의 네이티브 파일 트리로 방출한다.
타깃별 Emitter 는 이 프로토콜만 만족하면 되고, 추가는 가법적이다(dispatch 는 emit/__init__).

MCP `mcpServers` 직렬화는 Claude Code(.mcp.json)·Cursor(.cursor/mcp.json)가 **동일 포맷**을
쓰므로 여기 공용 함수로 둔다(단일 IR → 여러 런타임에서 같은 조립 재사용).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from harness_resolver import ResolvedComponent, ResolvedHarness

# 상대경로 → 파일 내용. 디스크 쓰기(CLI)·아카이브 반환(API)이 모두 이 형태를 소비한다.
FileTree = dict[str, str]


@dataclass(frozen=True)
class Loss:
    """이 타깃으로 방출할 때 잃거나 근사되는 IR 요소(이식 손실). verify 가 정량 리포트한다.

    손실 목록은 이미터가 **자기 자신에 대해 선언**한다(verify 가 하드코딩하지 않는다) — 이미터가
    바뀌면 손실 선언도 같이 바뀌어 리포트가 자동 정합한다.
    """

    feature: str  # IR 필드/기능 (예: "hook_plan.after_request")
    fidelity: str  # "unsupported"(대응 없음) | "approximate"(근사·부분 소실)
    detail: str  # 사람이 읽는 설명


class Emitter(Protocol):
    target: str

    def emit(self, resolved: ResolvedHarness) -> FileTree: ...

    def losses(self, resolved: ResolvedHarness) -> list[Loss]:
        """이 IR 을 target 으로 방출할 때 발생하는 이식 손실(실제 IR 기준으로 트리거된 것만)."""
        ...


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
