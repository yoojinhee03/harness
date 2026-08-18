"""다중 provider 구조화 출력 클라이언트 — Claude(Anthropic) / OpenAI 를 같은 인터페이스로.

키·모델·provider 를 인자로 받아(전역 env 무의존) JSON 을 파싱해 돌려준다. SDK 는 지연 import
(미설치여도 앱은 뜨고, 해당 provider 사용 시에만 필요). packages/catalog/llm.py 의 env 기반 경로와
별개로, 사용자별 키 주입 경로를 담당한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

# 모델 선택 UI 는 제거 — provider 별 기본 모델을 쓴다.
DEFAULT_MODEL = {"anthropic": "claude-sonnet-5", "openai": "gpt-4o-mini"}


def _import_openai() -> Any:
    """지연 import + 가드 — 미설치 시 날것의 ModuleNotFoundError 대신 설치 안내로 감싼다."""
    try:
        import openai
    except ModuleNotFoundError as exc:
        raise RuntimeError("openai provider 는 openai SDK 가 필요합니다: uv sync --all-packages --extra llm") from exc
    return openai


def _import_anthropic() -> Any:
    """지연 import + 가드 — anthropic 미설치 시 설치 안내로 감싼다."""
    try:
        import anthropic
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "anthropic provider 는 anthropic SDK 가 필요합니다: uv sync --all-packages --extra llm"
        ) from exc
    return anthropic


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
    anthropic = _import_anthropic()  # 지연 import — 미설치 시 이 provider 사용할 때만 에러
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, temperature=0.2, system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(_strip_fence(text))


def _openai_json(model: str, api_key: str, system: str, user: str, max_tokens: int) -> Any:
    openai = _import_openai()  # 지연 import
    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=0.2,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    text = resp.choices[0].message.content or ""
    return json.loads(_strip_fence(text))


def stream_text(
    provider: str, model: str, api_key: str, system: str, user: str, *, max_tokens: int = 1024
) -> Iterator[str]:
    """provider 스트리밍 — 어시스턴트 프로즈를 토큰 단위로 흘린다(사람 읽는 텍스트용, JSON 아님).

    구조화 라우팅/저작은 complete_json(버퍼)로 하고, 이 함수는 최종 응답 문장만 스트리밍해 '진짜
    챗봇' 타이핑 느낌을 준다. 동기 제너레이터 — 호출부(SSE)에서 스레드로 브리지한다.
    """
    if provider == "openai":
        yield from _openai_stream(model, api_key, system, user, max_tokens)
    else:
        yield from _anthropic_stream(model, api_key, system, user, max_tokens)


def _openai_stream(model: str, api_key: str, system: str, user: str, max_tokens: int) -> Iterator[str]:
    openai = _import_openai()
    stream = openai.OpenAI(api_key=api_key).chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=0.4, stream=True,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        text = getattr(chunk.choices[0].delta, "content", None)
        if text:
            yield text


def _anthropic_stream(model: str, api_key: str, system: str, user: str, max_tokens: int) -> Iterator[str]:
    anthropic = _import_anthropic()
    with anthropic.Anthropic(api_key=api_key).messages.stream(
        model=model, max_tokens=max_tokens, temperature=0.4, system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for text in stream.text_stream:
            if text:
                yield text


def verify_key(provider: str, model: str, api_key: str) -> None:
    """키·모델로 최소 호출을 시도(성공=예외 없음). JSON 파싱은 하지 않는다 — 인증/도달만 확인."""
    if provider == "openai":
        _import_openai().OpenAI(api_key=api_key).chat.completions.create(
            model=model, max_tokens=1, messages=[{"role": "user", "content": "ping"}]
        )
    else:
        _import_anthropic().Anthropic(api_key=api_key).messages.create(
            model=model, max_tokens=1, messages=[{"role": "user", "content": "ping"}]
        )
