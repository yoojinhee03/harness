"""카탈로그 + RAG 추천 테스트 — 실제 시드 데이터(harness-catalog) 위에서 관통.

로컬 폴백(키 없음)으로 추출 → 검색 → 랭킹이 도는지, PR 리뷰 봇 시나리오가
기대 컴포넌트를 추천하는지 확인한다.
"""

from __future__ import annotations

import pytest
from harness_catalog import Recommender, build_registry, extract_capabilities_heuristic

PR_BOT = (
    "PR 자동 리뷰 봇을 만들고 싶어. 코드 리뷰 코멘트를 자동으로 달고, "
    "팀 코딩 컨벤션을 지키고, 보안 시크릿이 새지 않게 스캔해야 해."
)


@pytest.fixture(scope="module")
def registry():
    return build_registry()  # 옆 폴더 harness-catalog/components 자동 탐색


def test_seed_catalog_loads(registry):
    ids = {c.id for c in registry.all()}
    # 확장 후 10개 — 원래 PR 봇 시드 4개는 그대로 포함.
    assert {"github-mcp", "pr-review-skill", "coding-convention-ctx", "secret-scan-hook"} <= ids
    assert len(ids) == 10


def test_heuristic_extraction_finds_core_capabilities():
    caps = set(extract_capabilities_heuristic(PR_BOT))
    assert "review.code" in caps
    assert "lifecycle.guardrail" in caps
    assert "convention.coding" in caps
    assert caps & {"vcs.code-review", "vcs.code-hosting"}


def test_recommend_pipeline_local_fallback(registry):
    rec = Recommender(registry)
    result = rec.recommend(PR_BOT, top_k=4)

    assert result.extraction_mode == "heuristic"
    assert result.ranking_mode == "heuristic"

    ids = {r.id for r in result.recommendations}
    # PR 리뷰 봇 4-컴포넌트가 모두 상위 추천에 들어와야 한다.
    assert {"github-mcp", "pr-review-skill", "secret-scan-hook"} <= ids

    # 타입별 그룹(화면 B 탭)
    assert "mcp" in result.groups
    assert "skill" in result.groups

    # 근거·능력·비용이 카드에 실려 있는지
    skill = next(r for r in result.recommendations if r.id == "pr-review-skill")
    assert skill.requires == ["vcs.code-hosting", "vcs.code-review"]
    assert skill.context_tokens == 1800
    assert skill.reason


def test_ranking_orders_matches_first(registry):
    rec = Recommender(registry)
    result = rec.recommend("코드 리뷰와 PR 자동화", top_k=4)
    # 최상위는 요구 능력이 매칭된 컴포넌트여야 한다(임베딩만이 아니라 능력 매칭 가중).
    assert result.recommendations[0].matched_capabilities
