"""요청 빌더 — 기획 §3.2.

ResolvedHarness(실행 명세)를 받아 Anthropic Messages API 요청 형태로 조립한다:
system(컨텍스트·스킬 주입) + tools + mcp_servers + model 파라미터.

MCP: Messages API 의 MCP 커넥터는 **원격(URL) 서버만** 지원한다. 따라서 http/sse 스펙만
요청 `mcp_servers` 에 싣고(러너가 그대로 전송), stdio 서버는 로컬 프로세스라 API 로 못 띄운다
→ eject(클라이언트 런타임)에서 소비한다. tools 는 카탈로그에 도구 정의가 없어 현재 비어있다
(도구는 MCP 서버가 노출).
"""

from __future__ import annotations

from typing import Any

from harness_resolver import ResolvedComponent, ResolvedHarness
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
    """리졸브된 하네스로부터 요청을 조립한다.

    시스템 프롬프트는 리졸버가 합성한 `resolved.prompt.system_text`(Phase 10, 단일 원본)를
    쓴다. `prompt` 가 없는 경우(예: 직접 생성한 ResolvedHarness)엔 폴백으로 동일 형식으로 조립.
    """
    mcp_servers: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []

    for comp in resolved.components:
        if comp.type != "mcp":
            continue
        spec = comp.mcp
        if spec is not None and spec.transport in ("http", "sse"):
            # Messages API MCP 커넥터 형태(원격 URL 서버) — 러너가 그대로 전송한다.
            mcp_servers.append({"type": "url", "url": spec.url, "name": comp.id})
        # stdio(또는 스펙 없음) 서버는 API 로 못 띄움(로컬 프로세스) → eject 로 클라이언트에서 소비.

    if resolved.prompt is not None:
        system = resolved.prompt.system_text
    else:
        system = _assemble_system_fallback(resolved.components)

    hook_plan = {event: [s.id for s in steps] for event, steps in resolved.hook_plan.items()}

    return BuiltRequest(
        model=resolved.model.name,
        max_tokens=resolved.model.max_tokens,
        temperature=resolved.model.temperature,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
        tools=tools,
        mcp_servers=mcp_servers,
        hook_plan=hook_plan,
        permissions=resolved.permissions,
    )


def _assemble_system_fallback(components: list[ResolvedComponent]) -> str:
    """prompt 합성이 없을 때의 폴백 조립.

    NOTE: `harness_resolver.prompt._component_segment_text` 와 **글자까지 동일**해야 한다
    (동치 회귀 테스트로 고정). 한쪽을 바꾸면 다른 쪽도 함께 갱신할 것.
    """
    parts: list[str] = []
    for comp in components:
        if comp.type == "context":
            parts.append(f"## 컨텍스트: {comp.name} ({comp.id})\n[주입된 컨텍스트 — config={comp.config}]")
        elif comp.type == "skill":
            parts.append(f"## 스킬 절차: {comp.name} ({comp.id})\n[주입된 절차 — config={comp.config}]")
    return "\n\n".join(parts)
