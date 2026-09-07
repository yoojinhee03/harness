"""저작 컴포넌트의 공유 카탈로그 승격 — 리뷰 게이트 경유(Phase 14 후속).

스코프 격리된 유저 저작 컴포넌트(`user_components`)를 검증 게이트를 통과할 때만 공유 카탈로그
(`catalog_components`, origin='promoted')로 올린다 → 모든 유저가 검색·재사용(gap 을 남의 것까지 닫음).

게이트(공급망 신뢰, CONTRIBUTING §3 — 자동 승격 금지, 명시 액션 + 검증):
  1. status='ready' — 스튜디오에서 결정적 검증 + LLM 안전심사를 통과한 것만.
  2. `validate_component` 결정적 재검증(hook 계약·config 스키마·능력 어휘·실행가능성) 통과.
승격분은 origin='promoted' 로 프로비넌스가 남아 추천 신뢰등급에 반영된다(curated/official 아님 → community).
"""

from __future__ import annotations

from typing import Any

from harness_resolver import Component

from .authoring import validate_component
from .catalog_store import CatalogStore
from .component_store import ComponentStore

PROMOTED_ORIGIN = "promoted"


def promote_component(
    cstore: ComponentStore,
    catalog_store: CatalogStore,
    scope: str,
    cid: str,
    *,
    allow_unsandboxed: bool = False,
    approvals: list[dict[str, Any]] | None = None,
    min_approvals: int = 0,
) -> dict[str, Any]:
    """저작 컴포넌트를 공유 카탈로그로 승격. 게이트 실패 시 ok=False + 사유.

    거버넌스 게이트(CONTRIBUTING §3): ready 상태 + validate 재검증에 더해, **sandbox=none 훅**은
    무격리 실행이라 공유 카탈로그(전 유저 노출)로 올릴 때 공급망 위험이 크다 → 추가 심사(명시
    `allow_unsandboxed`)가 없으면 차단한다.

    **다인 승인**(`min_approvals` > 0): 승격은 전 유저에게 퍼지므로 단독 행위로 두지 않는다.
    이 함수는 **순수하게** 유지하려고 승인 목록을 인자로 받는다(DB 조회는 호출부). 정족수 판정은
    두 규칙으로 좁힌다:
      · **자기 승인은 안 센다** — 작성자가 자기 것을 승인해 통과시키면 "다인 승인"이 이름만 남는다.
      · **현재 버전의 승인만 센다** — 심사한 내용과 올라가는 내용이 다르면 심사가 무의미하다.
    `min_approvals=0`(기본)이면 이 게이트는 없는 것과 같다 → 기존 동작 완전 불변.
    """
    doc = cstore.get(scope, cid)
    if doc is None:
        return {"ok": False, "errors": [f"컴포넌트 '{cid}' 없음(scope={scope})"], "promoted": None}
    if doc.get("status") != "ready":
        return {
            "ok": False,
            "errors": ["ready 상태(검증+안전심사 통과)만 승격 가능 — 먼저 검증·테스트를 통과시켜라"],
            "promoted": None,
        }
    comp = Component.model_validate_json(doc["data"])
    v = validate_component(comp)
    if not v["ok"]:
        return {"ok": False, "errors": v["errors"], "promoted": None}
    if comp.type == "hook" and comp.sandbox == "none" and not allow_unsandboxed:
        return {
            "ok": False,
            "errors": [
                "sandbox=none 훅은 무격리로 실행돼 공유 카탈로그 승격 시 공급망 위험이 큽니다 — "
                "추가 심사 후 allow_unsandboxed 로 명시 승인하세요."
            ],
            "promoted": None,
        }
    if min_approvals > 0:
        valid, reason = _approval_status(doc, approvals or [], min_approvals, scope)
        if not valid:
            return {"ok": False, "errors": [reason], "promoted": None}

    catalog_store.upsert(PROMOTED_ORIGIN, [comp])
    return {
        "ok": True,
        "errors": [],
        "warnings": v.get("warnings", []),
        "promoted": {"id": comp.id, "version": comp.version, "origin": PROMOTED_ORIGIN},
    }


def approval_progress(
    doc: dict[str, Any], approvals: list[dict[str, Any]], min_approvals: int
) -> dict[str, Any]:
    """정족수 진행 상황 — 화면·API 가 "몇 명 더 필요한가"를 보여줄 수 있게.

    유효 승인 = 작성자가 아니고 + 현재 버전을 승인한 것. 무효 사유도 갈라 돌려준다(왜 안 세는지
    보여주지 않으면 사용자는 승인했는데 카운트가 안 오르는 이유를 알 수 없다).
    """
    author = str(doc.get("owner_id") or "")
    current = int(doc.get("version") or 0)
    valid: list[str] = []
    self_approved = False
    stale: list[str] = []
    for a in approvals:
        approver = str(a.get("approver_id") or "")
        if approver == author:
            self_approved = True
            continue
        if int(a.get("component_version") or 0) != current:
            stale.append(approver)
            continue
        valid.append(approver)
    return {
        "required": min_approvals,
        "approved_by": sorted(set(valid)),
        "count": len(set(valid)),
        "satisfied": len(set(valid)) >= min_approvals,
        "self_approved_ignored": self_approved,
        "stale_ignored": sorted(set(stale)),
        "component_version": current,
    }


def _approval_status(
    doc: dict[str, Any], approvals: list[dict[str, Any]], min_approvals: int, scope_key: str = ""
) -> tuple[bool, str]:
    p = approval_progress(doc, approvals, min_approvals)
    if p["satisfied"]:
        return True, ""
    parts = [
        f"승격에는 작성자 외 승인 {min_approvals}명이 필요합니다(현재 {p['count']}명)",
    ]
    if str(scope_key).startswith("personal:"):
        # 개인 스코프엔 다른 사람이 접근할 수 없어 정족수를 **영원히** 못 채운다. 막다른 길을
        # 그냥 "승인 부족"으로만 알리면 사용자는 무엇을 해야 하는지 알 수 없다.
        parts.append(
            "개인 스코프에는 다른 승인자가 접근할 수 없습니다 — 팀 스코프로 옮긴 뒤 검토를 받으세요"
        )
    if p["self_approved_ignored"]:
        parts.append("작성자 본인의 승인은 정족수에 포함되지 않습니다")
    if p["stale_ignored"]:
        parts.append(
            f"컴포넌트가 변경돼 무효가 된 승인 {len(p['stale_ignored'])}건(v{p['component_version']} 재승인 필요)"
        )
    return False, " — ".join(parts)
