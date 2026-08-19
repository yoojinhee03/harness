"""LLM 헬퍼 — 요구사항 추출·랭킹 근거·능력 태깅용. provider(anthropic|openai) + 키 주입 지원.

키는 명시 주입(api_key) 우선, 없으면 env 폴백. 앱 등록 키(DB, 암호화)는 호출부(API)가 복호해 주입한다.
provider 는 anthropic|openai. 모델 미지정 시 provider 기본 모델을 쓴다.
"""

from __future__ import annotations

import json
import os
from typing import Any

MODEL = "claude-sonnet-5"  # 하위호환 기본(anthropic)
DEFAULT_MODEL = {"anthropic": "claude-sonnet-5", "openai": "gpt-4o-mini"}
_ENV_KEY = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def default_model(provider: str) -> str:
    return DEFAULT_MODEL.get(provider, MODEL)


def available(provider: str = "anthropic", api_key: str | None = None) -> bool:
    """해당 provider 로 호출 가능한가 — 명시 키가 있거나 env 키가 있으면 True."""
    return bool(api_key or os.environ.get(_ENV_KEY.get(provider, "ANTHROPIC_API_KEY")))


def claude_available() -> bool:  # 하위호환(anthropic env)
    return available("anthropic")


def complete_json(
    system: str,
    user: str,
    *,
    model: str = MODEL,
    max_tokens: int = 1024,
    provider: str = "anthropic",
    api_key: str | None = None,
) -> Any:
    """LLM 에 JSON 응답을 요청하고 파싱해 반환. 실패 시 예외. provider 로 anthropic|openai 분기."""
    if provider == "openai":
        return _openai_json(system, user, model=model, max_tokens=max_tokens, api_key=api_key)
    return _anthropic_json(system, user, model=model, max_tokens=max_tokens, api_key=api_key)


def _parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    return json.loads(text)


def _anthropic_json(
    system: str, user: str, *, model: str, max_tokens: int, api_key: str | None
) -> Any:  # pragma: no cover - 네트워크
    try:
        import anthropic
    except ModuleNotFoundError as exc:
        raise RuntimeError("anthropic 미설치: uv sync --all-packages --extra llm") from exc
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.2,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    return _parse_json(text)


def _openai_json(
    system: str, user: str, *, model: str, max_tokens: int, api_key: str | None
) -> Any:  # pragma: no cover - 네트워크
    try:
        import openai
    except ModuleNotFoundError as exc:
        raise RuntimeError("openai 미설치: uv sync --all-packages --extra llm") from exc
    client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return _parse_json(resp.choices[0].message.content or "")
