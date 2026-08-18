"""스튜디오 대화 오케스트레이터 — 매 유저 턴의 의도를 분류하고 분기 실행한다.

Cursor/Windsurf 식 라우터 + GPT Builder 식 되묻기 + RAG recommend-first 를 합쳤다:

    유저 메시지 ─▶ classify(라우터, 구조화 JSON): intent + component_type(자동) + confidence + title
                  ├─ clarify   요구가 모호 → 되묻는 질문
                  ├─ recommend 카탈로그 RAG → 기존 매칭 제안
                  ├─ author    RAG 먼저 → 高매칭이면 재사용 제안, 아니면 authoring.py 로 초안
                  ├─ refine    현재 초안을 대화 맥락으로 수정
                  └─ chitchat  잡담/안내

프로즈(사람이 읽는 최종 응답)는 여기서 만들지 않고 (prose_system, prose_user)만 넘긴다 — 엔드포인트가
llm_client.stream_text 로 토큰 스트리밍한다(타이핑 느낌). 타입은 절대 사용자가 고르지 않는다(자동 추론).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from harness_resolver import Component

from .authoring import COMPONENT_TYPES, author_component

CompleteFn = Callable[[str, str, int], Any]  # (system, user, max_tokens) -> 파싱된 JSON

INTENTS = ("clarify", "recommend", "author", "refine", "chitchat")

# author 인데 이 점수 이상의 기존 매칭이 있으면 새로 만들기 전에 '재사용'을 먼저 제안한다(카탈로그 비대화 방지).
# ranking.py 점수는 정규화되진 않지만 능력 일치(가중 2.5)가 지배적 — 1.2 면 최소 한 능력이 맞는 수준.
HIGH_MATCH_SCORE = 1.2

# 타입 자동 분류용 정의(authoring.py 도크스트링과 일치). 라우터에 주입해 요구에서 타입을 '추론'하게 한다.
TYPE_MEANINGS = {
    "context": "항상 주입되는 배경지식/규칙/프롬프트 조각(사실·정책·톤). 절차가 아니라 '지식'.",
    "skill": "에이전트가 따를 작업 절차(단계별 how-to). 도구 접근은 requires 로 MCP 에 위임.",
    "mcp": "실존하는 외부 도구/서버 연결(깃허브·슬랙·DB 등 API·명령 접근). '무엇에 연결'.",
    "hook": "요청 전/후 자동 실행되는 검사·차단·기록(예: 커밋 전 린트, PR 시 알림). '자동 트리거'.",
}


@dataclass
class Decision:
    """라우터 판정 — 의도 + (자동 추론된)타입 + 확신도 + 근거 + (필요 시)대화 제목."""

    intent: str
    type: str | None
    confidence: float
    rationale: str
    title: str | None = None


@dataclass
class TurnResult:
    """분기 실행 산출물 — 추천 목록/초안/재사용 여부 + 프로즈 스트리밍 입력."""

    decision: Decision
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    draft: Component | None = None
    reused: bool = False  # author 였지만 기존 재사용 제안으로 전환
    prose_system: str = ""
    prose_user: str = ""


# ─────────────────────────── 1) 분류(라우터) ───────────────────────────

_ROUTER_SYSTEM = (
    "너는 '카탈로그 스튜디오'의 대화 라우터다. 사용자가 카탈로그 구성요소를 채팅으로 만들거나 추천받는다.\n"
    "매 턴의 의도를 하나로 분류하고, 만들/고칠 것이면 타입을 **자동 추론**한다(사용자는 타입을 고르지 않는다).\n\n"
    "의도(intent):\n"
    "- clarify: 무엇을 만들지 너무 모호해 1~2개 되물어야 함\n"
    "- recommend: 이미 있는 걸 찾아달라/추천해달라(만들자는 게 아님)\n"
    "- author: 새 구성요소를 만들자(현재 초안이 없거나 다른 걸 새로)\n"
    "- refine: 현재 초안을 고치자/바꾸자(초안이 있을 때)\n"
    "- chitchat: 인사·잡담·사용법 질문\n\n"
    "타입(type, author/refine 일 때만 의미):\n<types>\n\n"
    'JSON 으로만: {"intent","type"(넷 중 하나 또는 null),"type_rationale"(한 줄),'
    '"confidence"(0~1),"title"(대화 제목, <need_title> 일 때만 8자 내외 한국어, 아니면 "")}.'
)


def _types_block() -> str:
    return "\n".join(f"- {t}: {d}" for t, d in TYPE_MEANINGS.items())


def _compact_history(history: list[dict[str, Any]], limit: int = 8) -> str:
    tail = history[-limit:]
    lines = [f'{m.get("role", "user")}: {str(m.get("content", ""))[:400]}' for m in tail]
    return "\n".join(lines) or "(없음)"


def classify(
    history: list[dict[str, Any]],
    user_msg: str,
    *,
    has_draft: bool,
    draft_type: str,
    has_title: bool,
    complete: CompleteFn,
) -> Decision:
    """라우터 호출 → Decision. 실패 시 안전 폴백(author/context)."""
    system = _ROUTER_SYSTEM.replace("<types>", _types_block()).replace(
        "<need_title>", "제목이 아직 없음" if not has_title else "제목이 이미 있음"
    )
    payload = {
        "history": _compact_history(history),
        "user_message": user_msg,
        "current_draft": {"exists": has_draft, "type": draft_type or None},
        "need_title": not has_title,
    }
    try:
        data = complete(system, json.dumps(payload, ensure_ascii=False), 400)
        if not isinstance(data, dict):
            raise ValueError("router 응답이 JSON 오브젝트가 아님")
        intent = str(data.get("intent") or "").strip()
        if intent not in INTENTS:
            intent = "refine" if has_draft else "author"
        ctype = data.get("type")
        ctype = ctype if ctype in COMPONENT_TYPES else (draft_type or "context")
        title = str(data.get("title") or "").strip() or None
        return Decision(
            intent=intent,
            type=ctype,
            confidence=float(data.get("confidence") or 0.0),
            rationale=str(data.get("type_rationale") or "")[:200],
            title=title if not has_title else None,
        )
    except Exception:  # noqa: BLE001 — 라우터 실패는 안전 폴백(계속 진행)
        return Decision(
            intent="refine" if has_draft else "author",
            type=draft_type or "context",
            confidence=0.0,
            rationale="자동 분류 실패 — 기본값 적용",
            title=None,
        )


# ─────────────────────────── 2) 분기 실행 ───────────────────────────


def execute(
    decision: Decision,
    history: list[dict[str, Any]],
    user_msg: str,
    current_draft: Component | None,
    *,
    complete: CompleteFn,
    recommender: Any,
    forced_type: str | None = None,
) -> TurnResult:
    """판정에 따라 추천/저작/리파인을 실행하고 프로즈 스트리밍 입력을 채운다."""
    ctype = forced_type if forced_type in COMPONENT_TYPES else decision.type
    if forced_type in COMPONENT_TYPES:
        decision.type = forced_type

    if decision.intent == "recommend":
        recs = _recommend(recommender, user_msg)
        return TurnResult(decision, recommendations=recs, prose_system=_PROSE_SYSTEM,
                          prose_user=_prose("recommend", recs=recs, user_msg=user_msg))

    if decision.intent == "clarify":
        return TurnResult(decision, prose_system=_PROSE_SYSTEM,
                          prose_user=_prose("clarify", user_msg=user_msg, rationale=decision.rationale))

    if decision.intent == "chitchat":
        return TurnResult(decision, prose_system=_PROSE_SYSTEM, prose_user=_prose("chitchat", user_msg=user_msg))

    if decision.intent == "refine" and current_draft is not None:
        draft = author_component(user_msg, current_draft.type, current_draft, complete=complete)
        return TurnResult(decision, draft=draft, prose_system=_PROSE_SYSTEM,
                          prose_user=_prose("refine", draft=draft, user_msg=user_msg))

    # author (refine 인데 초안이 없으면 여기로 폴백)
    recs = _recommend(recommender, user_msg, top_k=4)
    # 재사용 제안은 '같은 타입'의 강한 매칭일 때만 — 훅을 원했는데 mcp 를 권하는 오탐을 막는다.
    # (능력 일치가 랭킹을 지배해 타입이 달라도 점수가 높게 나오므로 타입 일치를 필수 조건으로 둔다.)
    strong = [r for r in recs if r.get("type") == ctype and float(r.get("score", 0.0)) >= HIGH_MATCH_SCORE]
    if strong and not _wants_new(user_msg):
        # 高매칭 → 새로 만들기 전에 재사용 제안(카탈로그 비대화 방지). 초안은 만들지 않는다.
        return TurnResult(decision, recommendations=strong, reused=True, prose_system=_PROSE_SYSTEM,
                          prose_user=_prose("reuse", recs=strong, user_msg=user_msg, ctype=ctype))
    draft = author_component(user_msg, ctype or "context", None, complete=complete)
    related = [r for r in recs if float(r.get("score", 0.0)) >= 0.6][:3]
    return TurnResult(decision, draft=draft, recommendations=related, prose_system=_PROSE_SYSTEM,
                      prose_user=_prose("author", draft=draft, user_msg=user_msg, related=related))


def _wants_new(user_msg: str) -> bool:
    """사용자가 '새로/직접 만들기'를 명시하면 재사용 제안을 건너뛰고 바로 저작한다."""
    m = user_msg.lower()
    return any(k in m for k in ("새로", "그래도 만들", "직접 만들", "무시하고"))


def _recommend(recommender: Any, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    try:
        result = recommender.recommend(query, top_k=top_k)
    except Exception:  # noqa: BLE001 — 빈 카탈로그/임베더 문제는 추천 없음으로
        return []
    out: list[dict[str, Any]] = []
    for r in result.recommendations:
        d = r.model_dump() if hasattr(r, "model_dump") else dict(r)
        out.append(d)
    return out


# ─────────────────────────── 3) 프로즈(스트리밍) 입력 ───────────────────────────

_PROSE_SYSTEM = (
    "너는 '카탈로그 스튜디오'의 친절한 어시스턴트다. 방금 처리한 결과를 바탕으로 사용자에게 한국어로 "
    "자연스럽게 답한다(2~4문장, 마크다운 최소, JSON 금지).\n"
    "- author/refine: 무슨 타입으로 무엇을 만들었/고쳤는지 한 줄로 요약하고, 오른쪽 캔버스에서 확인하고 "
    "'저장'하거나 더 고쳐달라 하라고 안내한다.\n"
    "- reuse: 이미 비슷한 게 있음을 알리고, 그걸 쓸지 아니면 '새로 만들기'라고 말할지 물어본다.\n"
    "- recommend: 찾은 후보를 짧게 소개하고 고르라고 안내한다.\n"
    "- clarify: 만들 대상을 좁히는 질문 1~2개를 던진다.\n"
    "- chitchat: 짧게 답하고 무엇을 만들고 싶은지 유도한다.\n"
    "과장·불필요한 사족 없이."
)


def _prose(kind: str, **kw: Any) -> str:
    """프로즈 스트리밍 호출의 user 페이로드 — 무슨 일이 있었는지 압축 전달."""
    data: dict[str, Any] = {"kind": kind, "user_message": kw.get("user_msg", "")}
    if kw.get("rationale"):
        data["missing"] = kw["rationale"]
    if kw.get("ctype"):
        data["type"] = kw["ctype"]
    draft = kw.get("draft")
    if draft is not None:
        data["draft"] = {
            "type": draft.type, "name": draft.name, "summary": draft.summary,
            "provides": draft.provides,
        }
    recs = kw.get("recs") or kw.get("related")
    if recs:
        data["matches"] = [
            {"name": r.get("name"), "type": r.get("type"), "summary": r.get("summary"),
             "score": round(float(r.get("score", 0.0)), 2)}
            for r in recs[:5]
        ]
    return json.dumps(data, ensure_ascii=False, default=str)
