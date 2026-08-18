"""다중 provider 구조화 출력 클라이언트 — Claude(Anthropic) / OpenAI 를 같은 인터페이스로.

키·모델·provider 를 인자로 받아(전역 env 무의존) JSON 을 파싱해 돌려준다. SDK 는 지연 import
(미설치여도 앱은 뜨고, 해당 provider 사용 시에만 필요). packages/catalog/llm.py 의 env 기반 경로와
별개로, 사용자별 키 주입 경로를 담당한다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
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


# dispatch(tool_name, args) -> (LLM 에게 돌려줄 결과 문자열, [부수효과 이벤트...])
type ToolDispatch = Callable[[str, dict[str, Any]], tuple[str, list[dict[str, Any]]]]


def run_tool_loop(
    provider: str,
    model: str,
    api_key: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    dispatch: ToolDispatch,
    *,
    max_rounds: int = 5,
    max_tokens: int = 1500,
) -> Iterator[dict[str, Any]]:
    """provider 무관 tool-use 루프(동기 제너레이터) — '진짜 대화' 에이전트의 심장.

    LLM 이 tool(search_catalog/get_catalog_item/draft_component 등)을 자율 호출하면 dispatch 로 실행하고
    결과를 되먹여 다시 부른다. 도구 호출이 없어지면 그 응답이 최종 답. 이벤트를 yield:
      {"type":"status","label"}  — 도구 실행 알림(프런트 상태줄)
      {"type":"side","event":{}} — 도구 부수효과(초안·추천 등, 엔드포인트가 SSE 로 중계)
      {"type":"token","text"}    — 최종 응답 청크(타이핑 느낌)
      {"type":"final","text"}    — 최종 응답 전문(영속용)
    tools 는 provider 무관 스펙: [{"name","description","parameters":{json schema}}].
    """
    if provider == "openai":
        yield from _openai_tool_loop(model, api_key, system, messages, tools, dispatch, max_rounds, max_tokens)
    else:
        yield from _anthropic_tool_loop(model, api_key, system, messages, tools, dispatch, max_rounds, max_tokens)


def _chunk_text(text: str, size: int = 3) -> Iterator[dict[str, Any]]:
    for i in range(0, len(text), size):
        yield {"type": "token", "text": text[i : i + size]}


def _tool_label(name: str, args: dict[str, Any]) -> str:
    q = str(args.get("query") or args.get("instruction") or "")[:30]
    return {
        "get_catalog_item": f"'{q}' 조회 중…",
        "search_catalog": f"카탈로그 검색 중… ({q})",
        "web_search": f"웹 검색 중… ({q})",
        "draft_component": "초안 작성 중…",
        "assemble_harness": "에이전트 조립 중…",
    }.get(name, "처리 중…")


def _openai_tool_loop(
    model: str, api_key: str, system: str, messages: list[dict[str, Any]],
    tools: list[dict[str, Any]], dispatch: ToolDispatch, max_rounds: int, max_tokens: int,
) -> Iterator[dict[str, Any]]:
    openai = _import_openai()
    client = openai.OpenAI(api_key=api_key)
    oai_tools = [
        {"type": "function", "function": {"name": t["name"], "description": t["description"],
                                          "parameters": t["parameters"]}}
        for t in tools
    ]
    convo: list[dict[str, Any]] = [{"role": "system", "content": system}, *messages]
    for _ in range(max_rounds):
        resp = client.chat.completions.create(
            model=model, max_tokens=max_tokens, temperature=0.3, tools=oai_tools, messages=convo
        )
        msg = resp.choices[0].message
        if msg.tool_calls:
            convo.append({
                "role": "assistant", "content": msg.content,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield {"type": "status", "label": _tool_label(tc.function.name, args)}
                result, side = dispatch(tc.function.name, args)
                for ev in side:
                    yield {"type": "side", "event": ev}
                convo.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            continue
        text = msg.content or ""
        yield from _chunk_text(text)
        yield {"type": "final", "text": text}
        return
    # 도구만 계속 부르면 강제 종료 — 도구 없이 한 번 더 답하게 한다.
    resp = client.chat.completions.create(model=model, max_tokens=max_tokens, temperature=0.3, messages=convo)
    text = resp.choices[0].message.content or ""
    yield from _chunk_text(text)
    yield {"type": "final", "text": text}


def _anthropic_tool_loop(
    model: str, api_key: str, system: str, messages: list[dict[str, Any]],
    tools: list[dict[str, Any]], dispatch: ToolDispatch, max_rounds: int, max_tokens: int,
) -> Iterator[dict[str, Any]]:
    anthropic = _import_anthropic()
    client = anthropic.Anthropic(api_key=api_key)
    a_tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
    convo: list[dict[str, Any]] = list(messages)
    for _ in range(max_rounds):
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, tools=a_tools, messages=convo
        )
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        text = "".join(b.text for b in resp.content if b.type == "text")
        if tool_uses:
            convo.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
            results: list[dict[str, Any]] = []
            for tu in tool_uses:
                args = dict(tu.input) if isinstance(tu.input, dict) else {}
                yield {"type": "status", "label": _tool_label(tu.name, args)}
                result, side = dispatch(tu.name, args)
                for ev in side:
                    yield {"type": "side", "event": ev}
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": result})
            convo.append({"role": "user", "content": results})
            continue
        yield from _chunk_text(text)
        yield {"type": "final", "text": text}
        return
    resp = client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=convo)
    text = "".join(b.text for b in resp.content if b.type == "text")
    yield from _chunk_text(text)
    yield {"type": "final", "text": text}


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
