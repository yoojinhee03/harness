"""스코프 인지 추천 — 유저 저작 컴포넌트가 검색에 편입되고 gap 을 닫는지(Phase 14 피드백 루프).

네트워크 없이 로컬 임베더로 관통. 전역(시드) + 유저 저작(email MCP) 병합 → email gap 이 닫힌다.
"""

from __future__ import annotations

from harness_api.scoped_recommender import ScopedRecommender
from harness_catalog import Recommender, build_registry
from harness_resolver import Component

EMAIL_Q = "고객 이메일에 자동으로 답장을 보내는 봇"


def _base() -> Recommender:
    return Recommender(build_registry())  # 시드 13 — comms.email 제공 컴포넌트 없음


def test_base_reports_email_gap():
    r = _base().recommend(EMAIL_Q, top_k=5)
    assert "comms.email" in {g.capability for g in r.gaps}


def test_scoped_fills_gap_with_authored_component():
    base = _base()
    authored = [
        Component(id="u-mail", type="mcp", name="내 메일 서버", version="1.0.0",
                  provides=["comms.email"], capability_tags=["comms.email"])
    ]
    scoped = ScopedRecommender(base, authored)
    r = scoped.recommend(EMAIL_Q, top_k=6)

    # 저작 컴포넌트가 검색에 등장(재사용) + 그 능력이 더는 gap 아님(gap 닫힘)
    assert "u-mail" in {rec.id for rec in r.recommendations}
    assert "comms.email" not in {g.capability for g in r.gaps}


def test_scoped_without_user_components_is_identity():
    base = _base()
    plain = base.recommend(EMAIL_Q, top_k=6)
    scoped = ScopedRecommender(base, []).recommend(EMAIL_Q, top_k=6)
    assert {r.id for r in scoped.recommendations} == {r.id for r in plain.recommendations}
    assert {g.capability for g in scoped.gaps} == {g.capability for g in plain.gaps}
