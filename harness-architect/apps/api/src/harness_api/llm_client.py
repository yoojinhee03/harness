"""다중 provider 구조화 출력 클라이언트 — Claude(Anthropic) / OpenAI 를 같은 인터페이스로.

키·모델·provider 를 인자로 받아(전역 env 무의존) JSON 을 파싱해 돌려준다. SDK 는 지연 import
(미설치여도 앱은 뜨고, 해당 provider 사용 시에만 필요). packages/catalog/llm.py 의 env 기반 경로와
별개로, 사용자별 키 주입 경로를 담당한다.
"""

from __future__ import annotations

import json
from typing import Any

# 모델 선택 UI 는 제거 — provider 별 기본 모델을 쓴다.
DEFAULT_MODEL = {"anthropic": "claude-sonnet-5", "openai": "gpt-4o-mini"}


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    return text


def complete_json(
    provider: str, model: str, api_key: str, system: str, user: str, *, max_tokens: int = 1024
) -> Any:
    """provider 에 맞는 클라이언트로 JSON 응답을 받아 파싱. 실패 시 예외(호출부가 폴백)."""
    if provider == "openai":
        return _openai_json(model, api_key, system, user, max_tokens)
    return _anthropic_json(model, api_key, system, user, max_tokens)


def _anthropic_json(model: str, api_key: str, system: str, user: str, max_tokens: int) -> Any:
    import anthropic  # 지연 import — 미설치 시 이 provider 사용할 때만 에러

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, temperature=0.2, system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(_strip_fence(text))


def _openai_json(model: str, api_key: str, system: str, user: str, max_tokens: int) -> Any:
    import openai  # 지연 import

    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=0.2,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    text = resp.choices[0].message.content or ""
    return json.loads(_strip_fence(text))
