"""통제 어휘 헬퍼 — 도메인 척추, facet→타입 매핑, 형태 검증(작업 2·3)."""

from __future__ import annotations

from harness_catalog import DOMAIN_VOCAB, facet_for_capability, suggested_component_type
from harness_catalog.vocabulary import (
    CAPABILITY_VOCAB,
    DOMAIN_DEFAULT_FACET,
    capability_domain,
    extract_capabilities_heuristic,
    is_valid_capability,
)


def test_capability_shape_validation():
    assert is_valid_capability("vcs.code-hosting")
    assert is_valid_capability("media.transcode")  # 신규 도메인도 형태만 맞으면 통과
    assert not is_valid_capability("NoDot")
    assert not is_valid_capability("too.many.dots")
    assert not is_valid_capability("Upper.Case")
    assert not is_valid_capability("1bad.start")


def test_domain_vocab_is_superset_of_seeded_domains():
    """도메인 척추는 카탈로그 능력의 도메인을 모두 포함해야 한다(요구가 카탈로그보다 넓게 잡히도록)."""
    seeded = {capability_domain(cap) for cap in CAPABILITY_VOCAB}
    assert seeded <= set(DOMAIN_VOCAB)
    # 명백히 빠졌던 도메인이 등재됨(컴포넌트는 아직 없어도 gap 으로 표면화됨)
    assert {"media", "dataproc"} <= set(DOMAIN_VOCAB)


def test_known_capability_facet_and_type():
    assert facet_for_capability("vcs.code-hosting") == "access"
    assert suggested_component_type("vcs.code-hosting") == "mcp"
    assert suggested_component_type("review.code") == "skill"
    assert suggested_component_type("convention.coding") == "context"
    assert suggested_component_type("lifecycle.guardrail") == "hook"


def test_new_capability_type_inferred_from_domain():
    """카탈로그/vocab 에 없는 신규 능력도 도메인 기본 facet 으로 타입을 추정한다."""
    assert suggested_component_type("media.transcode") == "mcp"  # media → access → mcp(실존 서버 연결)
    assert suggested_component_type("comms.webhook") == "mcp"  # comms → access → mcp
    # dataproc 은 아직 capability 없음 → 도메인 기본 facet(task→skill)
    assert suggested_component_type("dataproc.etl") == "skill"
    # 완전 미상 도메인은 안전한 기본값(skill)
    assert suggested_component_type("totallyunknown.thing") == "skill"


def test_domain_default_facet_derived_from_vocab():
    assert DOMAIN_DEFAULT_FACET["vcs"] == "access"
    assert DOMAIN_DEFAULT_FACET["review"] == "task"
    assert DOMAIN_DEFAULT_FACET["lifecycle"] == "lifecycle"
    assert DOMAIN_DEFAULT_FACET["media"] == "access"  # media 캡들이 access 라 귀납됨


def test_heuristic_boundary_avoids_substring_false_positives():
    """라틴 단어경계 — 'ci'/'pr' 이 큰 단어 속에서 오탐하지 않는다(수확 태그 오염의 주범)."""
    assert extract_capabilities_heuristic("A decision engine that provides products") == []
    # 미디어 서버는 media.* 로 태깅(어휘 확장)
    caps = extract_capabilities_heuristic("AI video editing tool with BGM music generator")
    assert "media.video" in caps
    assert {"media.edit", "media.audio"} & set(caps)
    # 한국어는 조사 붙어도 매칭 유지
    assert "vcs.code-review" in extract_capabilities_heuristic("PR을 리뷰하는 봇")
