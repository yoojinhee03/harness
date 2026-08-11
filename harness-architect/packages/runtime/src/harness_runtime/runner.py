"""Anthropic 러너 — 조립된 요청을 실제 API 로 전송. 기획 §3.2.

클라이언트 주입 가능(테스트는 fake). `ANTHROPIC_API_KEY` 가 없으면 네트워크 호출 없이
`dry_run` 결과를 돌려준다(로컬에서 안전하게 관통).
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from .builder import BuiltRequest


class RunResult(BaseModel):
    dry_run: bool
    model: str
    text: str | None = None
    stop_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


class AnthropicRunner:
    def __init__(self, client: Any | None = None, api_key: str | None = None) -> None:
        self._client = client
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def _resolve_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if not self._api_key:
            return None
        import anthropic  # pragma: no cover - 네트워크 경로

        return anthropic.Anthropic(api_key=self._api_key)

    def run(self, built: BuiltRequest) -> RunResult:
        client = self._resolve_client()
        if client is None:
            return RunResult(
                dry_run=True,
                model=built.model,
                notes=["ANTHROPIC_API_KEY 없음 — dry_run(요청은 조립됨, 전송 안 함)"],
            )

        common: dict[str, Any] = {
            "model": built.model,
            "max_tokens": built.max_tokens,
            "temperature": built.temperature,
            "system": built.system,
            "messages": built.messages,
        }
        if built.tools:
            common["tools"] = built.tools

        if built.mcp_servers:
            # 조립된 MCP 서버(원격 URL)를 실제로 요청에 싣는다 — 더 이상 드롭하지 않는다.
            # MCP 커넥터는 베타라 beta 엔드포인트 + betas 플래그가 필요하다.
            resp = client.beta.messages.create(
                **common, mcp_servers=built.mcp_servers, betas=["mcp-client-2025-04-04"]
            )
        else:
            resp = client.messages.create(**common)
        text = _extract_text(resp)
        return RunResult(
            dry_run=False,
            model=built.model,
            text=text,
            stop_reason=getattr(resp, "stop_reason", None),
        )


def _extract_text(resp: Any) -> str:
    """Anthropic 응답(또는 fake)에서 텍스트 블록을 이어붙인다."""
    parts: list[str] = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text" or hasattr(block, "text"):
            parts.append(getattr(block, "text", ""))
    return "".join(parts)
