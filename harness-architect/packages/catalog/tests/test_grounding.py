"""그라운딩 수용 기준 (작업 1·2) — 세 종류 입력으로 관통.

A) 카탈로그가 잘 커버하는 도메인 → 실재 컴포넌트 반환, gap 적음.
B) 부분 커버 도메인 → 컴포넌트와 gap 이 섞여 나온다(실패 아님).
C) 의도적으로 시딩하지 않은 도메인 → 컴포넌트를 발명하지 않고 거의 전부 gap.

공통: 반환된 모든 컴포넌트 id 가 카탈로그에 실재(자동 대조), 요구사항 추출은 도메인 무관(형태만 계약).
LocalEmbedder + 휴리스틱/주입 Reasoner 로 네트워크 없이 검증한다.
"""

from __future__ import annotations

import pytest
from harness_catalog import CapabilityGap, Recommender, build_registry
from harness_catalog.recommender import _valid_caps


@pytest.fixture(scope="module")
def registry():
    return build_registry()


@pytest.fixture(scope="module")
def catalog_ids(registry):
    return {c.id for c in registry.all()}


class MediaReasoner:
    """미시딩 도메인(media.*)을 내는 품질-모드 스텁 — LLM 추출 경로 모사(네트워크 없음)."""

    name = "claude"

    def extract_requirements(self, description: str):
        return ["media.transcode", "media.subtitle", "media.thumbnail"]

    def rank_reasons(self, description, items):
        return None


def _assert_all_ids_in_catalog(result, catalog_ids):
    """수용 공통 — 추천된 모든 id 는 카탈로그에 실재해야 한다(발명 금지)."""
    for r in result.recommendations:
        assert r.id in catalog_ids, f"카탈로그에 없는 id 추천됨(발명): {r.id}"


# ── A) 잘 커버되는 도메인 ──


def test_A_well_covered_returns_real_components_few_gaps(registry, catalog_ids):
    rec = Recommender(registry)
    result = rec.recommend("PR 자동 리뷰 봇, 코드 리뷰, 보안 스캔", top_k=6)

    ids = {r.id for r in result.recommendations}
    assert {"github-mcp", "pr-review-skill", "secret-scan-hook"} <= ids
    assert result.gaps == []  # 추출 능력이 전부 카탈로그로 커버됨
    _assert_all_ids_in_catalog(result, catalog_ids)


# ── B) 부분 커버 — 컴포넌트 + gap 혼재(실패 아님) ──


def test_B_partial_coverage_mixes_components_and_gaps(registry, catalog_ids):
    rec = Recommender(registry)
    result = rec.recommend(
        "PR 을 리뷰하고 결과를 이메일로 보내며 관계형 데이터베이스에 기록하는 봇", top_k=6
    )

    ids = {r.id for r in result.recommendations}
    gap_caps = {g.capability for g in result.gaps}

    # 커버된 능력 → 실재 컴포넌트, 없는 능력 → gap. 둘 다 비어있지 않다(= 부분 커버가 정상 결과).
    assert ids, "커버된 능력이 있으면 추천이 비면 안 된다"
    assert "pr-review-skill" in ids
    assert {"comms.email", "data.relational"} <= gap_caps
    assert result.recommendations and result.gaps  # 실패가 아니라 유효 응답(둘 다 존재)
    _assert_all_ids_in_catalog(result, catalog_ids)


# ── C) 의도적으로 시딩하지 않은 도메인 — 발명 금지, 거의 전부 gap ──


def test_C_unseeded_domain_invents_nothing_all_gaps(registry, catalog_ids):
    rec = Recommender(registry, reasoner=MediaReasoner())
    result = rec.recommend("유튜브 쇼츠 자동 편집: 영상 트랜스코딩·자막·썸네일", top_k=6)

    # 발명 없음: media 컴포넌트가 카탈로그에 없으므로 추천은 없거나(잡음 floor 로 걸러짐) 전부 실재 id.
    _assert_all_ids_in_catalog(result, catalog_ids)
    assert not result.recommendations  # 관련 컴포넌트 없음 → floor 가 잡음 카드 제거
    # 요구 능력은 전부 gap 으로(발명 대신 정직한 결핍).
    assert {g.capability for g in result.gaps} == {"media.transcode", "media.subtitle", "media.thumbnail"}
    # gap 은 '무엇으로 채우나'를 담는다(콜드스타트 시딩 입력).
    for g in result.gaps:
        assert isinstance(g, CapabilityGap)
        assert g.suggested_type in {"skill", "mcp", "context", "hook"}


# ── 그라운딩 게이트: 반환 직전 id 대조 ──


def test_catalog_verification_drops_phantom_ids(registry):
    """레지스트리 드리프트로 회수 목록에 유령 id 가 섞여도 반환 직전 게이트가 제거한다."""
    from harness_catalog.ranking import RankedComponent

    rec = Recommender(registry)
    kept, phantom = registry.all()[0], registry.all()[1]
    ranked = [
        RankedComponent(component=kept, score=1.0, embed_score=0.9, matched_capabilities=[], reason="x"),
        RankedComponent(component=phantom, score=0.9, embed_score=0.9, matched_capabilities=[], reason="y"),
    ]
    # phantom 을 인덱스에서 제거해 '카탈로그에 없는 id' 를 모사 → 게이트가 그것만 떨궈야 한다.
    rec._by_id.pop(phantom.id)
    verified = rec._catalog_verified(ranked)
    assert [r.component.id for r in verified] == [kept.id]


# ── 요구사항 추출 도메인 무관성(작업 2) ──


def test_extraction_is_domain_independent_shape_only(registry):
    """추출은 카탈로그/vocab 멤버십이 아니라 형태(domain.capability)만 계약 — 신규 도메인도 통과."""

    class MixedReasoner:
        name = "claude"

        def extract_requirements(self, description):
            # 유효 신규 도메인 · 유효 기존 · 무효(형태 위반) 섞어서 반환
            return ["media.transcode", "review.code", "NotACap", "too.many.dots.here", "x"]

        def rank_reasons(self, description, items):
            return None

    rec = Recommender(registry, reasoner=MixedReasoner())
    result = rec.recommend("아무 설명", top_k=6)
    assert result.requirements == ["media.transcode", "review.code"]  # 무효 형태는 제거
    # media.* 는 카탈로그에 없음 → gap, review.code 는 커버 → gap 아님
    assert "media.transcode" in {g.capability for g in result.gaps}
    assert "review.code" not in {g.capability for g in result.gaps}


def test_valid_caps_filters_shape_and_dedupes():
    assert _valid_caps(["a.b", "a.b", "Bad", "c.d", "no-dot", "e.f.g"]) == ["a.b", "c.d"]


# ── 랭킹 방어: 과다 부여된(잡음) 능력 다운웨이트 (Lever 3) ──


def test_cap_weight_idf_downweights_over_assigned_caps():
    """전역 df 가 큰 능력(수확 오탐이 몰린 태그)은 신뢰 가중치가 낮다. df=1/미존재 → 1.0."""
    from harness_resolver import Component, InMemoryRegistry

    comps = [
        Component(id=f"m{i}", type="mcp", name="m", version="1.0.0", provides=["over.used"])
        for i in range(10)
    ]
    comps.append(Component(id="u", type="mcp", name="u", version="1.0.0", provides=["uniq.cap"]))
    rec = Recommender(InMemoryRegistry(comps))
    w = rec._cap_weight(["over.used", "uniq.cap", "absent.cap"])
    assert w["uniq.cap"] == 1.0 and w["absent.cap"] == 1.0
    assert w["over.used"] < 0.5  # df=10 → 1/(1+ln10) ≈ 0.30


def test_rank_components_scores_external_set_with_grounding(registry):
    """전역 인덱스 밖 소규모 집합(유저 저작)을 같은 그라운딩으로 점수화(스코프 검색 피드백 루프)."""
    from harness_resolver import Component

    rec = Recommender(registry)
    ext = [
        Component(id="my-mail", type="mcp", name="Mail", version="1.0.0",
                  provides=["comms.email"], capability_tags=["comms.email"])
    ]
    recs = rec.rank_components(ext, ["comms.email"], "이메일 보내기", top_k=3)
    assert [r.id for r in recs] == ["my-mail"]
    assert "comms.email" in recs[0].matched_capabilities
    # 무관 요구엔 relevance floor 로 안 나옴(발명 방지 동일 적용)
    assert rec.rank_components(ext, ["vcs.code-hosting"], "코드 호스팅", top_k=3) == []


def test_rank_prefers_rare_capability_over_spurious_common():
    """임베딩 동률일 때, 희귀(고신뢰) 능력 매칭이 과다부여(잡음) 능력 매칭을 이긴다."""
    from harness_catalog.ranking import rank
    from harness_resolver import Component

    spurious = Component(id="spurious", type="mcp", name="s", version="1.0.0",
                         provides=["over.used"], capability_tags=["over.used"])
    genuine = Component(id="genuine", type="mcp", name="g", version="1.0.0",
                        provides=["uniq.cap"], capability_tags=["uniq.cap"])
    ranked = rank(
        [(spurious, 0.1), (genuine, 0.1)],
        ["over.used", "uniq.cap"],
        cap_weight={"over.used": 0.13, "uniq.cap": 1.0},
    )
    assert ranked[0].component.id == "genuine"
