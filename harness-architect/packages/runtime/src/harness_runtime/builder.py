"""요청 빌더 (스켈레톤) — 기획 §3.2.

ResolvedHarness(실행 명세)를 받아 Anthropic API 요청 형태로 조립한다:
system(컨텍스트·스킬 주입) + tools + mcp_servers + model 파라미터. 실제 MCP 도구 스펙
회수와 API 호출은 🚧 (다음 단계).
"""

from __future__ import annotations

from typing import Any

from harness_resolver import ResolvedHarness
from pydantic import BaseModel, Field


class BuiltRequest(BaseModel):
    """Anthropic Messages API 요청의 조립 결과(스켈레톤)."""

    model: str
    max_tokens: int
    temperature: float
    system: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    # 훅 엔진이 소비할 계획 (event → hook id 순서)
    hook_plan: dict[str, list[str]] = Field(default_factory=dict)
    permissions: dict[str, str] = Field(default_factory=dict)


def build_request(resolved: ResolvedHarness, user_prompt: str) -> BuiltRequest:
    """리졸브된 하네스로부터 요청을 조립한다."""
    system_parts: list[str] = []
    mcp_servers: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []

    for comp in resolved.components:
        if comp.type == "context":
            system_parts.append(f"## 컨텍스트: {comp.name} ({comp.id})\n[주입된 컨텍스트 — config={comp.config}]")
        elif comp.type == "skill":
            system_parts.append(f"## 스킬 절차: {comp.name} ({comp.id})\n[주입된 절차 — config={comp.config}]")
        elif comp.type == "mcp":
            # 🚧 실제로는 MCP 서버에 접속해 도구 스펙을 회수한다.
            mcp_servers.append({"id": comp.id, "version": comp.version, "config": comp.config})

    hook_plan = {event: [s.id for s in steps] for event, steps in resolved.hook_plan.items()}

    return BuiltRequest(
        model=resolved.model.name,
        max_tokens=resolved.model.max_tokens,
        temperature=resolved.model.temperature,
        system="\n\n".join(system_parts),
        messages=[{"role": "user", "content": user_prompt}],
        tools=tools,
        mcp_servers=mcp_servers,
        hook_plan=hook_plan,
        permissions=resolved.permissions,
    )
