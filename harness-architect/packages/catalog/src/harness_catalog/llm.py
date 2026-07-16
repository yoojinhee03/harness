"""Claude 헬퍼 — 요구사항 추출·랭킹 근거 생성용. 개발: 기술 스택 §2.

ANTHROPIC_API_KEY 가 있을 때만 활성. 없으면 호출부가 휴리스틱으로 폴백한다.
모델은 Claude Sonnet 5 (`claude-sonnet-5`).
"""

from __future__ import annotations

import json
import os
from typing import Any

MODEL = "claude-sonnet-5"


def claude_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client() -> Any:  # pragma: no cover - 네트워크
    try:
        import anthropic
    except ModuleNotFoundError as exc:
        raise RuntimeError("anthropic 미설치: uv sync --extra claude") from exc
    return anthropic.Anthropic()


def complete_json(system: str, user: str, *, model: str = MODEL, max_tokens: int = 1024) -> Any:  # pragma: no cover
    """Claude 에 JSON 응답을 요청하고 파싱해 반환. 실패 시 예외."""
    resp = _client().messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.2,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    return json.loads(text)
