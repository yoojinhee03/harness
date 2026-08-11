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
    # 시드 10 + 프롬프트 조각 3 = 13. 원래 PR 봇 시드 4개는 그대로 포함.
    assert {"github-mcp", "pr-review-skill", "coding-convention-ctx", "secret-scan-hook"} <= ids
    assert len(ids) == 13


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


def test_issue_triage_scenario_surfaces_triage_skill(registry):
    """회귀: 이슈 분류 설명이 issue-triage-skill 을 능력 매칭으로 상위에 올린다.

    이전엔 스킬이 transform.extract(추출)를 provide 하는데 vocab 이 '분류/라벨'을 그 능력으로
    추출하지 못해 score 가 바닥이었다 → transform.classify 로 택소노미 정합화한 뒤 상위 진입.
    """
    rec = Recommender(registry)
    result = rec.recommend("깃허브에 새 이슈가 등록되면 내용을 읽고 라벨을 자동으로 분류해 붙이는 에이전트", top_k=4)
    ids = {r.id for r in result.recommendations}
    assert "issue-triage-skill" in ids
    triage = next(r for r in result.recommendations if r.id == "issue-triage-skill")
    assert "transform.classify" in triage.matched_capabilities


def test_guardrail_extracted_from_bimil_phrasing():
    """회귀: '비밀키' 표현도 lifecycle.guardrail 로 추출된다(이전엔 시크릿/스캔만 매칭)."""
    caps = set(extract_capabilities_heuristic("비밀키가 섞였는지 검사한 뒤 슬랙으로 보내는 봇"))
    assert "lifecycle.guardrail" in caps


def test_recommends_prompt_fragment_for_role_description(registry):
    """프롬프트 조각도 RAG 로 발견된다 (Phase 10) — '페르소나·톤' 설명에 role 조각이 능력 매칭으로 뜬다."""
    rec = Recommender(registry)
    result = rec.recommend("리뷰어 페르소나와 톤을 잡아주는 시스템 프롬프트가 필요해", top_k=6)
    frag = next((r for r in result.recommendations if r.id == "prompt-role-reviewer"), None)
    assert frag is not None
    assert "prompt.role" in frag.matched_capabilities
    assert frag.type == "context"
