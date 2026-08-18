"""스튜디오 대화 에이전트 — 미션 고정 tool-use 챗봇.

'버킷 분류 → 기계적 덤프'(구버전)를 버리고, LLM 이 매 턴 도구를 자율 호출하며 자연스럽게 대화하되
**항상 카탈로그 구성요소 생성으로 수렴**하도록 한다:

    get_catalog_item(query)   특정 항목을 정확히 조회해 설명(“X가 뭐야?”에 실제로 답)
    search_catalog(query)     관련 기존 구성요소 시맨틱 검색(점수 낮으면 '없다'고 정직하게)
    draft_component(type,…)   요구를 파악하면 초안 생성/수정

루프는 llm_client.run_tool_loop 가 돌리고, 여기선 도구 구현 + 미션 시스템 프롬프트만 조립한다.
초안 생성은 authoring.author_component 재사용(타입은 자동, forced_type 으로 덮어쓰기 가능).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

from harness_resolver import Component

from .authoring import COMPONENT_TYPES, author_component
from .harness_build import build_harness_yaml
from .llm_client import run_tool_loop
from .web_search import web_search

CompleteFn = Callable[[str, str, int], Any]  # (system, user, max_tokens) -> 파싱된 JSON

AGENT_SYSTEM = (
    "너는 '카탈로그 스튜디오'의 대화형 어시스턴트다. 사용자가 자기 AI 에이전트에 넣을 **카탈로그 구성요소**"
    "를 만들도록 돕는 게 유일한 목적이다. 구성요소 4종:\n"
    "- context: 항상 주입되는 배경지식/규칙\n- skill: 작업 절차(how-to)\n"
    "- mcp: 외부 도구/서버 연결\n- hook: 요청 전후 자동 실행되는 검사·동작\n\n"
    "가장 중요한 원칙 — 되묻지 말고 만들어라(draft-first):\n"
    "- 사용자가 대략의 목표만 말해도 곧바로 draft_component 로 구체적인 v1 초안을 만들어 보여줘라. 세부(전환 "
    "스타일·BGM 종류·이모지 소스 등)는 네가 합리적으로 가정해 채우고, 어떻게 가정했는지 한 줄로 알린 뒤 사용자가 "
    "고치게 하라.\n"
    "- '먼저 ~부터 만들어볼까요?', '어떤 걸 포함할지 말씀해 주세요' 처럼 허락·정보를 구걸하지 마라. 그냥 만든다.\n"
    "- 이미 답한 걸 또 묻지 마라. 질문은 방향 자체를 정말 못 정할 때만 딱 1개.\n\n"
    "그 밖의 원칙:\n"
    "1) 특정 카탈로그 항목명을 대며 '뭐야?' 라고 하면 반드시 get_catalog_item 으로 조회해서 설명하라"
    "(추측·엉뚱한 나열 금지).\n"
    "2) 기존에 쓸 만한 게 있는지 궁금하면 search_catalog 로 확인하라. 점수가 낮으면 솔직히 '없다' 하고 새로 "
    "만들어라 — 무관한 목록을 주르륵 나열하지 마라.\n"
    "3) 에이전트에 여러 구성요소(skill·context·mcp·hook)가 필요하면 draft_component 를 여러 번 불러 각각 만들어라 "
    "— 서로 덮어쓰지 않고 세트로 쌓인다. 사용자가 '전부/다/구성해줘' 라고 하면 필요한 것들을 차례로 만든 뒤 "
    "assemble_harness 로 하나의 에이전트(하네스)로 묶어라.\n"
    "4) mcp 를 만들기 전 반드시 search_catalog(그리고 가능하면 web_search)로 **실존 서버**를 먼저 찾아라. "
    "mcp 는 찾은 실존 서버만 기술한다(그 서버의 실제 id·이름·실행 스펙 그대로). 카탈로그에 관련 mcp 가 있으면 "
    "그걸 재사용하라. **찾지 못하면 mcp 를 만들지 말고** skill/hook 으로 대체하라 — 'OO API Connector' 같은 "
    "이름을 지어내는 것은 절대 금지. 대체했으면 '실존 mcp 를 못 찾아 skill 로 대체했다'고 한 줄로 알려라.\n"
    "5) 짧고 자연스러운 한국어로. 메뉴처럼 '1. 2. 3. 어떤 걸 고르시겠어요?' 로 강요하지 마라."
)


def _history_to_messages(history: list[dict[str, Any]], user_msg: str) -> list[dict[str, Any]]:
    """저장된 턴 이력 + 현재 메시지를 LLM 대화로. 연속 동일 role 은 합친다(Anthropic 교대 규칙 대비)."""
    msgs: list[dict[str, Any]] = []
    for m in history:
        role = "assistant" if m.get("role") == "assistant" else "user"
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + content
        else:
            msgs.append({"role": role, "content": content})
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] += "\n" + user_msg
    else:
        msgs.append({"role": "user", "content": user_msg})
    return msgs


# ─────────────────────────── 도구 구현 ───────────────────────────

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_catalog_item",
        "description": "이름 또는 id 로 특정 카탈로그 항목을 조회해 설명(summary/description/능력)을 얻는다. "
        "사용자가 특정 항목명을 언급하며 '뭐야?/설명해줘' 라고 하면 반드시 이걸로 조회해 답하라.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "항목 이름 또는 id"}},
            "required": ["query"],
        },
    },
    {
        "name": "search_catalog",
        "description": "카탈로그에서 관련 구성요소를 시맨틱 검색. 사용자가 만들려는 것에 쓸 만한 기존 항목이 "
        "있는지 확인용. 결과 점수가 낮으면 관련도가 약한 것이니 솔직히 '없다'고 판단하라.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "검색어(무엇이 필요한지)"}},
            "required": ["query"],
        },
    },
    {
        "name": "draft_component",
        "description": "카탈로그 구성요소 초안을 하나 만들거나 수정한다(초안 세트에 추가/갱신 — 기존 것을 "
        "덮어쓰지 않음). 에이전트에 여러 구성요소가 필요하면 여러 번 호출하라. type 은 요구에 맞게 고른다.",
        "parameters": {
            "type": "object",
            "properties": {
                "component_type": {"type": "string", "enum": list(COMPONENT_TYPES)},
                "instruction": {"type": "string", "description": "만들/고칠 구성요소의 구체 설명(한국어)"},
            },
            "required": ["component_type", "instruction"],
        },
    },
    {
        "name": "assemble_harness",
        "description": "지금까지 만든 초안 구성요소들을 하나의 실행 가능한 에이전트(하네스)로 묶는다. "
        "사용자가 '구성해줘/조립해줘/에이전트로 만들어줘' 라고 하거나 필요한 구성요소가 갖춰졌을 때 호출. "
        "먼저 draft_component 로 구성요소를 만들어 둔 뒤 호출하라.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "에이전트(하네스) 이름"},
                "description": {"type": "string", "description": "에이전트 설명(선택)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "web_search",
        "description": "웹에서 실존하는 도구/API/MCP 서버/리소스를 검색한다. mcp 나 skill 을 만들 때 진짜 존재하는 "
        "것에 근거하려면 먼저 이걸로 확인하라(예: '영상 편집 API', 'MCP server video', '무료 상업용 BGM'). "
        "지어내지 말고 검색 결과에 근거해 구체적으로 만들어라.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "검색어"}},
            "required": ["query"],
        },
    },
]


def _build_tools(
    recommender: Any,
    registry: Any,
    complete: CompleteFn,
    holder: dict[str, Any],
    forced_type: str | None,
    search_key: str,
) -> tuple[list[dict[str, Any]], Callable[[str, dict[str, Any]], tuple[str, list[dict[str, Any]]]]]:
    """holder = {"components": [Component...], "harness": {...}|None} — 대화의 초안 세트(가변)."""

    def dispatch(name: str, args: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        if name == "get_catalog_item":
            return _tool_get(registry, str(args.get("query") or ""))
        if name == "search_catalog":
            return _tool_search(recommender, str(args.get("query") or ""))
        if name == "draft_component":
            return _tool_draft(complete, holder, forced_type, args)
        if name == "assemble_harness":
            return _tool_assemble(holder, args)
        if name == "web_search":
            return (web_search(search_key, str(args.get("query") or "")), [])
        return (f"알 수 없는 도구: {name}", [])

    return _TOOLS, dispatch


def _drafts_event(components: list[Component]) -> dict[str, Any]:
    return {"type": "drafts", "components": [c.model_dump() for c in components]}


def _tool_get(registry: Any, query: str) -> tuple[str, list[dict[str, Any]]]:
    q = query.strip().lower()
    if not q:
        return ("(빈 조회)", [])
    hit = registry.get(query)
    if hit is None:
        comps = registry.all()
        exact = [c for c in comps if c.name.lower() == q or c.id.lower() == q]
        if exact:
            hit = exact[0]
        else:
            sub = [c for c in comps if q in c.name.lower() or q in c.id.lower()]
            if len(sub) == 1:
                hit = sub[0]
            elif len(sub) > 1:
                names = ", ".join(f"{c.name}[{c.type}]" for c in sub[:5])
                return (f"'{query}' 후보 여러 개: {names}. 어느 것인지 사용자에게 되물어라.", [])
    if hit is None:
        return (f"'{query}' 을(를) 카탈로그에서 찾지 못함. 존재하지 않는 항목일 수 있음.", [])
    info = {
        "id": hit.id, "name": hit.name, "type": hit.type, "summary": hit.summary,
        "description": (hit.description or "")[:600], "provides": hit.provides, "requires": hit.requires,
    }
    return (json.dumps(info, ensure_ascii=False), [])


def _tool_search(recommender: Any, query: str) -> tuple[str, list[dict[str, Any]]]:
    recs = _recommend(recommender, query, top_k=5)
    if not recs:
        return ("검색 결과 없음.", [{"type": "recommendations", "items": [], "reused": False}])
    lines = [
        f"- {r['name']} [{r['type']}] 점수={r['score']:.2f} — {(r.get('summary') or '')[:80]}"
        for r in recs
    ]
    top = float(recs[0].get("score", 0.0))
    weak = "\n(주의: 최고 점수가 낮음 — 관련도 약함. 딱 맞는 게 없을 수 있으니 새로 만들자고 제안하라.)"
    note = "" if top >= 1.0 else weak
    return ("\n".join(lines) + note, [{"type": "recommendations", "items": recs, "reused": False}])


def _tool_draft(
    complete: CompleteFn, holder: dict[str, Any], forced_type: str | None, args: dict[str, Any]
) -> tuple[str, list[dict[str, Any]]]:
    if forced_type in COMPONENT_TYPES:
        ctype = forced_type
    else:
        raw = args.get("component_type")
        ctype = raw if raw in COMPONENT_TYPES else "context"
    instruction = str(args.get("instruction") or "").strip()
    comps: list[Component] = holder["components"]
    # 같은 id(=이름) 초안이 이미 있으면 그걸 prior 로 리파인 후 교체, 없으면 세트에 추가(멀티 초안).
    comp = author_component(instruction, ctype, None, complete=complete)
    replaced = False
    for i, existing in enumerate(comps):
        if existing.id == comp.id:
            comps[i] = author_component(instruction, ctype, existing, complete=complete)
            comp = comps[i]
            replaced = True
            break
    if not replaced:
        comps.append(comp)
    listing = ", ".join(f"[{c.type}] {c.name}" for c in comps)
    summary = (
        f"초안 '{comp.name}' [{comp.type}] {'수정' if replaced else '추가'}됨. "
        f"현재 초안 세트({len(comps)}개): {listing}."
    )
    return (summary, [_drafts_event(comps)])


def _tool_assemble(holder: dict[str, Any], args: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    comps: list[Component] = holder["components"]
    if not comps:
        return ("아직 만든 구성요소가 없음 — 먼저 draft_component 로 하나 이상 만들어라.", [])
    name = str(args.get("name") or "에이전트").strip()
    desc = str(args.get("description") or "").strip()
    yaml_text = build_harness_yaml(comps, name, desc)
    harness = {"name": name, "description": desc, "yaml": yaml_text, "component_ids": [c.id for c in comps]}
    holder["harness"] = harness
    summary = (
        f"'{name}' 하네스로 {len(comps)}개 구성요소를 묶었어요(harness.yaml 생성). "
        "사용자에게 캔버스에서 확인하고 저장하라고 안내하라."
    )
    return (summary, [{"type": "harness", "harness": harness}])


def _recommend(recommender: Any, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    try:
        result = recommender.recommend(query, top_k=top_k)
    except Exception:  # noqa: BLE001 — 빈 카탈로그/임베더 문제는 결과 없음으로
        return []
    return [r.model_dump() if hasattr(r, "model_dump") else dict(r) for r in result.recommendations]


# ─────────────────────────── 에이전트 실행 ───────────────────────────


def run_agent(
    history: list[dict[str, Any]],
    user_msg: str,
    current_components: list[Component],
    current_harness: dict[str, Any] | None,
    *,
    provider: str,
    model: str,
    api_key: str,
    complete: CompleteFn,
    recommender: Any,
    registry: Any,
    forced_type: str | None = None,
    search_key: str = "",
) -> Iterator[dict[str, Any]]:
    """한 턴 — tool-use 루프 이벤트를 그대로 흘린다(status/side/token/final).

    초안 세트(구성요소들)와 하네스는 side 이벤트(type=drafts / type=harness)로 나온다.
    """
    holder: dict[str, Any] = {"components": list(current_components), "harness": current_harness}
    tools, dispatch = _build_tools(recommender, registry, complete, holder, forced_type, search_key)
    messages = _history_to_messages(history, user_msg)
    yield from run_tool_loop(provider, model, api_key, AGENT_SYSTEM, messages, tools, dispatch)


def suggest_title(complete: CompleteFn, first_user: str, reply: str) -> str | None:
    """첫 턴 대화 제목 자동 생성(8자 내외). 실패하면 None(제목 없음 유지)."""
    try:
        data = complete(
            '대화 제목을 8자 내외 한국어 한 개로. JSON 으로만: {"title":"..."}.',
            json.dumps({"user": first_user[:200], "assistant": reply[:200]}, ensure_ascii=False),
            60,
        )
        if isinstance(data, dict):
            return (str(data.get("title") or "").strip() or None)
    except Exception:  # noqa: BLE001 — 제목 실패는 치명적 아님
        return None
    return None
