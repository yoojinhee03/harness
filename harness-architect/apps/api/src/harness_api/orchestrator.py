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
from collections.abc import Set as AbstractSet
from typing import Any

from harness_catalog import extract_capabilities_heuristic, facet_for_capability
from harness_resolver import Component, InMemoryRegistry, resolve
from harness_runtime import build_request

from .authoring import COMPONENT_TYPES, author_component
from .harness_build import build_harness_yaml, parse_harness_yaml
from .llm_client import run_tool_loop
from .web_search import web_search

CompleteFn = Callable[[str, str, int], Any]  # (system, user, max_tokens) -> 파싱된 JSON

AGENT_SYSTEM = (
    "너는 '카탈로그 스튜디오'의 대화형 어시스턴트다. 사용자가 자기 AI 에이전트에 넣을 **카탈로그 구성요소**"
    "를 만들도록 돕는 게 유일한 목적이다. 구성요소 4종:\n"
    "- context: 항상 주입되는 배경지식/규칙\n- skill: 작업 절차(how-to)\n"
    "- mcp: 외부 도구/서버 연결\n- hook: 요청 전후 자동 실행되는 검사·동작\n\n"
    "가장 중요한 원칙 — 재사용 우선, 그다음 되묻지 말고 진행(reuse-first, then act):\n"
    "- 무언가 필요하면 **먼저 search_catalog 로 실존 구성요소를 찾는다.** 쓸 만한 게 있으면 재사용하고, "
    "없거나 약하면(gap) 그때 draft_component 로 만든다. 카탈로그엔 실존 MCP 수천 개가 있으니 접근·도구는 "
    "특히 지어내기 전에 반드시 검색하라(발명 금지 — 재사용 > gap > 저작 순).\n"
    "- 만들기로 정했으면 되묻지 말고 곧바로 구체적 v1 초안을 낸다. 세부(전환 스타일·BGM 종류 등)는 합리적으로 "
    "가정해 채우고 한 줄로 알린 뒤 사용자가 고치게 하라. '먼저 ~부터 만들어볼까요?' 처럼 허락을 구걸하지 마라 "
    "— 재사용 확인은 하되, 만들기로 정했으면 그냥 만든다.\n"
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
    "그걸 재사용하라. 'OO API Connector' 같은 이름을 지어내는 것은 절대 금지.\n"
    "5) 실존 도구를 못 찾았을 때 — 그 능력이 **절차·지식**(프롬프트로 표현 가능: 리뷰 기준·작성 규칙·톤 등)이면 "
    "skill/context 로 만들면 된다. 하지만 그 능력이 **실제 실행**을 요구하면(영상 컷·트랜스코딩·오디오 믹싱·"
    "이미지/파일 변환·외부 API 호출 등) skill 이나 hook 으로 '대체'하지 마라 — skill 은 프롬프트라 실제로 "
    "실행하지 못한다(대체하면 '조립해도 실제로 안 돌아가는' 껍데기가 된다). 그런 능력은 **정직하게 gap 으로 "
    "남겨라**: 만들 수 있는 절차 skill 은 만들되, '○○(실행)은 카탈로그에 실행 도구가 없어 지금은 gap 이다. "
    "실존 MCP(예: ffmpeg 기반)를 찾아 연결하거나 이 능력을 카탈로그에 시딩해야 실제로 동작한다'고 사용자에게 "
    "분명히 구분해서 알려라. 없는 실행을 있는 척하지 마라.\n"
    "6) hook 은 요청 전후 **lifecycle 부수효과**(검사·차단·마스킹·알림·로깅)만 한다. 파이프라인 본작업(장면 "
    "감지·편집·요약·분류 등)을 hook 에 넣지 마라 — 그건 skill 의 일이고, hook 에 넣으면 조립 시 검증 실패한다.\n"
    "7) 짧고 자연스러운 한국어로. 메뉴처럼 '1. 2. 3. 어떤 걸 고르시겠어요?' 로 강요하지 마라."
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
    hot_capabilities: AbstractSet[str],
) -> tuple[list[dict[str, Any]], Callable[[str, dict[str, Any]], tuple[str, list[dict[str, Any]]]]]:
    """holder = {"components": [Component...], "harness": {...}|None} — 대화의 초안 세트(가변)."""

    def dispatch(name: str, args: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        if name == "get_catalog_item":
            return _tool_get(registry, str(args.get("query") or ""))
        if name == "search_catalog":
            return _tool_search(recommender, str(args.get("query") or ""), hot_capabilities)
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


def _tool_search(
    recommender: Any, query: str, hot_capabilities: AbstractSet[str] = frozenset()
) -> tuple[str, list[dict[str, Any]]]:
    recs, gaps = _recommend_full(recommender, query, top_k=5)
    event = {"type": "recommendations", "items": recs, "gaps": gaps, "reused": False}
    if not recs and not gaps:
        return ("검색 결과 없음.", [event])
    lines = [
        f"- {r['name']} [{r['type']}] 점수={r['score']:.2f} — {(r.get('summary') or '')[:80]}"
        for r in recs
    ]
    if gaps:
        # 그라운딩: 카탈로그가 못 채우는 능력은 정직하게 gap 으로 알린다 — 지어내지 말고 draft_component 로 만들라.
        # 자주 요청되는(hot) 공백은 만들면 카탈로그에 남아 다른 곳에도 재사용되므로 우선 제안하라.
        def _line(g: dict[str, Any]) -> str:
            hot = " ★자주 요청됨 — 만들면 재사용됨(우선 제안)" if g["capability"] in hot_capabilities else ""
            return f"- {g['capability']} → {g['suggested_type']} (카탈로그에 없음){hot}"

        gl = "\n".join(_line(g) for g in gaps)
        lines.append(f"\n[카탈로그 공백(gap) — 지어내지 말고 draft_component 로 만들 후보]\n{gl}")
    top = float(recs[0].get("score", 0.0)) if recs else 0.0
    weak = "\n(주의: 최고 점수가 낮음 — 관련도 약함. 딱 맞는 게 없을 수 있으니 새로 만들자고 제안하라.)"
    note = "" if top >= 1.0 else weak
    return ("\n".join(lines) + note, [event])


def _hook_misuse_warning(comp: Component) -> str | None:
    """훅이 lifecycle 밖 능력을 provides 하면(파이프라인 본작업 위장) 경고 — 조립 시 리졸버가 검증 실패시킨다."""
    if comp.type != "hook":
        return None
    off = [c for c in comp.provides if facet_for_capability(c) not in (None, "lifecycle")]
    if not off:
        return None
    return (
        f"⚠️ 이 hook 이 lifecycle 밖 능력({', '.join(off)})을 provides 한다 — 파이프라인 본작업을 hook 으로 "
        "위장한 것이라 조립 시 검증 실패한다. 그 작업은 skill 로 옮기고 hook 은 검사·알림 같은 부수효과만 남겨라. "
        "실행이 필요한데 실존 도구가 없으면 gap 으로 남기고 사용자에게 알려라."
    )


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
    warn = _hook_misuse_warning(comp)
    if warn:  # 훅 오용을 draft 단계에서 즉시 피드백(조립까지 가지 않게)
        summary = warn + "\n" + summary
    return (summary, [_drafts_event(comps)])


def _execution_coverage_missing(comps: list[Component]) -> set[str]:
    """선언을 믿지 않는 독립 실행가능성 검사(Fix B) — 조립된 skill/context 텍스트가 실행(access)을
    암시하는데 그 능력을 provides 하는 **mcp** 가 세트에 없으면 그 능력들을 돌려준다.

    access 는 오직 실존 mcp 만 채운다(skill/context 는 프롬프트). Fix A(requires 자동 주입)를 우회하거나
    skill 이 access 를 스스로 provides 한다고 (잘못) 주장해 requires-gap 을 가리는 경우까지 잡는 안전망.
    """
    mcp_provided = {cap for c in comps if c.type == "mcp" for cap in (*c.provides, *c.capability_tags)}
    implied: set[str] = set()
    for c in comps:
        if c.type == "mcp":
            continue
        text = " ".join(x for x in (c.name, c.summary, c.description, c.body) if x)
        implied.update(
            cap for cap in extract_capabilities_heuristic(text) if facet_for_capability(cap) == "access"
        )
    return implied - mcp_provided


def _validate_assembly(comps: list[Component], yaml_text: str) -> dict[str, list[str]]:
    """조립된 에이전트를 초안들만으로 resolve — 미충족 능력(gap)·에러·실행 커버리지 경고(실행가능성 게이트).

    초안 집합만으로 requires 가 안 풀리면 gap 이다: 예) 편집 skill 이 media 접근을 requires 하는데 그 접근을
    제공하는 실존 MCP 를 안 넣었으면 gap → "지어낸 껍데기"가 저장되기 전에 표면화된다(불변식 1: 실행가능성).
    거기에 더해, 선언(requires/provides)을 믿지 않는 텍스트 기반 커버리지 검사(_execution_coverage_missing)로
    requires 를 안 붙였거나 access 를 스스로 provides 한다고 주장해 gap 을 가린 껍데기까지 warnings 로 잡는다.
    """
    missing_exec = _execution_coverage_missing(comps)  # 선언 무관 텍스트 기반 커버리지(Fix B)
    try:
        res = resolve(parse_harness_yaml(yaml_text), InMemoryRegistry(list(comps)))
    except Exception:  # noqa: BLE001 — 검증 실패는 조립 자체를 막지 않는다(정보 제공용)
        gaps, errors = [], []
    else:
        gaps = sorted({g.capability for g in res.diagnostics.gaps if g.capability})
        errors = [e.message for e in res.diagnostics.errors]
    # resolver 가 이미 requires-gap 으로 낸 능력은 중복 경고하지 않는다(넷-신규만).
    net = sorted(missing_exec - set(gaps))
    warnings = (
        [
            f"실행 능력({', '.join(net)})을 제공하는 MCP 가 조립에 없음 — skill/context 는 프롬프트라 "
            "실제 실행(영상 컷·오디오 믹싱·외부 API 호출 등)을 못 한다. 실존 MCP 를 넣거나, 없으면 이 능력을 "
            "gap 으로 사용자에게 정직하게 알려라(있는 척 금지)."
        ]
        if net
        else []
    )
    return {"gaps": gaps, "errors": errors, "warnings": warnings}


def studio_run(
    drafts: list[Component],
    messages: list[dict[str, Any]],
    execute: Callable[[Any, list[dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any]:
    """조립된 에이전트를 대화로 실행(멀티턴 미리보기) — build→run 루프로 스튜디오를 에이전트 빌더로.

    초안들로 resolve → build_request 로 시스템 프롬프트·MCP 서버 합성 → execute(built, messages) 실행.
    execute 는 provider 인지: Anthropic+원격 MCP 면 실제 도구 실행(runtime), 아니면 프롬프트 미리보기.
    반환에 gap/에러·mode(tools|prompt)·선언 MCP 를 실어 "실행하려면 뭘 더 넣어야 하나"를 보여준다.
    messages: [{role, content}] 대화 히스토리(마지막이 새 user).
    """
    if not drafts:
        return {"ok": False, "errors": ["구성요소가 없음 — 먼저 만들어라"], "gaps": [], "output": None, "mode": None}
    yaml_text = build_harness_yaml(drafts, "미리보기")
    res = resolve(parse_harness_yaml(yaml_text), InMemoryRegistry(list(drafts)))
    gaps = sorted({g.capability for g in res.diagnostics.gaps if g.capability})
    errors = [e.message for e in res.diagnostics.errors]
    if not res.ok or res.resolved is None:
        return {"ok": False, "errors": errors, "gaps": gaps, "output": None, "mode": None}
    last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    built = build_request(res.resolved, last_user)
    ex = execute(built, messages)
    mode = ex.get("mode", "prompt")
    note = (
        "실제 원격 MCP 도구를 실행했습니다(runtime)."
        if mode == "tools"
        else "프롬프트·절차 미리보기 — MCP 도구는 실행하지 않음(연결은 eject 후 런타임에서)."
    )
    return {
        "ok": True,
        "errors": [],
        "gaps": gaps,
        "output": ex.get("output", ""),
        "mode": mode,
        "mcp_declared": [m.get("name") for m in built.mcp_servers],
        "note": note,
    }


def _tool_assemble(holder: dict[str, Any], args: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    comps: list[Component] = holder["components"]
    if not comps:
        return ("아직 만든 구성요소가 없음 — 먼저 draft_component 로 하나 이상 만들어라.", [])
    name = str(args.get("name") or "에이전트").strip()
    desc = str(args.get("description") or "").strip()
    yaml_text = build_harness_yaml(comps, name, desc)
    val = _validate_assembly(comps, yaml_text)
    warnings = val.get("warnings", [])
    harness = {
        "name": name, "description": desc, "yaml": yaml_text,
        "component_ids": [c.id for c in comps], "gaps": val["gaps"], "errors": val["errors"],
        "warnings": warnings,
    }
    holder["harness"] = harness
    parts = [f"'{name}' 하네스로 {len(comps)}개 구성요소를 묶었어요(harness.yaml 생성). "]
    if val["errors"]:
        parts.append(f"⚠️ 검증 에러: {'; '.join(val['errors'][:3])}. ")
    if val["gaps"]:
        parts.append(
            f"⚠️ 미충족 능력(gap): {', '.join(val['gaps'])} — 이 능력을 제공하는 **실존 MCP** 를 "
            "search_catalog 로 찾아 넣어야 실제로 동작한다(지어내지 말 것). 사용자에게 이 공백을 알려라. "
        )
    if warnings:
        parts.append("⚠️ " + " ".join(warnings) + " ")
    if not val["errors"] and not val["gaps"] and not warnings:
        parts.append("실행가능성 검증 통과. ")
    parts.append("사용자에게 캔버스에서 확인하고 저장하라고 안내하라.")
    return ("".join(parts), [{"type": "harness", "harness": harness}])


def _dump_list(items: Any) -> list[dict[str, Any]]:
    return [x.model_dump() if hasattr(x, "model_dump") else dict(x) for x in (items or [])]


def _recommend_full(
    recommender: Any, query: str, top_k: int = 5
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """검색 → (재사용 후보 recommendations, 카탈로그 공백 gaps). 둘 다 정직하게 돌려준다."""
    if not query.strip():
        return [], []
    try:
        result = recommender.recommend(query, top_k=top_k)
    except Exception:  # noqa: BLE001 — 빈 카탈로그/임베더 문제는 결과 없음으로
        return [], []
    return _dump_list(result.recommendations), _dump_list(getattr(result, "gaps", []))


def _recommend(recommender: Any, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    return _recommend_full(recommender, query, top_k=top_k)[0]


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
    hot_capabilities: AbstractSet[str] = frozenset(),
) -> Iterator[dict[str, Any]]:
    """한 턴 — tool-use 루프 이벤트를 그대로 흘린다(status/side/token/final).

    초안 세트(구성요소들)와 하네스는 side 이벤트(type=drafts / type=harness)로 나온다.
    hot_capabilities: 자주 요청되는 gap 능력(저작 우선 제안 근거) — 검색 결과 gap 주석에 반영.
    """
    holder: dict[str, Any] = {"components": list(current_components), "harness": current_harness}
    tools, dispatch = _build_tools(
        recommender, registry, complete, holder, forced_type, search_key, hot_capabilities
    )
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
