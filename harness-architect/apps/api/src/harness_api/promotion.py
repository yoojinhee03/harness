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
    cstore: ComponentStore, catalog_store: CatalogStore, scope: str, cid: str
) -> dict[str, Any]:
    """저작 컴포넌트를 공유 카탈로그로 승격. 게이트 실패 시 ok=False + 사유."""
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
    catalog_store.upsert(PROMOTED_ORIGIN, [comp])
    return {
        "ok": True,
        "errors": [],
        "warnings": v.get("warnings", []),
        "promoted": {"id": comp.id, "version": comp.version, "origin": PROMOTED_ORIGIN},
    }
