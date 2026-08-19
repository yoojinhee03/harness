"""저작 컴포넌트 공유 카탈로그 승격 — 리뷰 게이트(Phase 14 후속). 인메모리 엔진으로 관통."""

from __future__ import annotations

import pytest
from harness_api.catalog_store import CatalogStore
from harness_api.component_store import ComponentStore
from harness_api.db import make_engine, metadata
from harness_api.promotion import PROMOTED_ORIGIN, promote_component
from harness_resolver import Component


@pytest.fixture
def stores():
    engine = make_engine("sqlite://")  # 인메모리
    metadata.create_all(engine)
    return ComponentStore(engine), CatalogStore(engine)


def _put(cstore: ComponentStore, comp: Component, status: str) -> None:
    doc = cstore.put(
        "personal:u1", comp.id, "u1", comp.name, comp.summary, comp.model_dump_json(),
        type_=comp.type, status="draft",
    )
    if status != "draft":
        cstore.set_status(doc["scope"], doc["id"], status)


def _skill(cid: str) -> Component:
    return Component(
        id=cid, type="skill", name=cid, version="1.0.0", summary="s",
        provides=["review.code"], capability_tags=["review.code"], body="step 1",
        entrypoint=f"skills/{cid}/SKILL.md",
    )


def test_promote_ready_component_lands_in_shared_catalog(stores):
    cstore, catalog = stores
    comp = _skill("u-reviewer")
    _put(cstore, comp, status="ready")

    result = promote_component(cstore, catalog, "personal:u1", "u-reviewer")
    assert result["ok"] is True
    assert result["promoted"]["origin"] == PROMOTED_ORIGIN
    # 공유 카탈로그에 실제로 올라가 모든 유저가 조회 가능
    assert catalog.get("u-reviewer") is not None
    assert catalog.origins_for(["u-reviewer"]) == {"u-reviewer": PROMOTED_ORIGIN}


def test_promote_rejects_non_ready(stores):
    cstore, catalog = stores
    comp = _skill("u-draft")
    _put(cstore, comp, status="valid")  # ready 아님
    result = promote_component(cstore, catalog, "personal:u1", "u-draft")
    assert result["ok"] is False
    assert catalog.get("u-draft") is None


def test_promote_rejects_failing_validation(stores):
    cstore, catalog = stores
    # body 없는 skill → validate_component 실패(본문 비어 있음)
    bad = Component(id="u-bad", type="skill", name="bad", version="1.0.0",
                    provides=["review.code"], capability_tags=["review.code"])
    _put(cstore, bad, status="ready")
    result = promote_component(cstore, catalog, "personal:u1", "u-bad")
    assert result["ok"] is False
    assert catalog.get("u-bad") is None


def test_promote_missing_component(stores):
    cstore, catalog = stores
    result = promote_component(cstore, catalog, "personal:u1", "nope")
    assert result["ok"] is False and result["promoted"] is None
