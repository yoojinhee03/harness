"""SkillsMP 소스 — non-mcp(skill) 타입 보완. 네트워크 없이 fake fetcher 로 검증.

**백로그의 전제를 실측으로 정정했다.** "skillsmp 가 SKILL.md 를 REST 로 열어"는 부분적으로 틀렸다 —
API 는 메타데이터만 준다(2026-09-07 확인: `id·name·author·description·contentLanguage·githubUrl·
skillUrl·stars·updatedAt`). **본문은 응답에 없다.** 그래서 여기서 만든 컴포넌트는 body 가 비고,
그 상태가 조용히 새지 않는지를 이미터 손실 선언으로 함께 확인한다.

또 **열거가 불가능하다** — `q` 가 필수고 익명 쿼터가 50 req/day 다. 통제어휘를 질의어로 쓰는
전략이 결정적이고 유계인지 고정한다.
"""

from __future__ import annotations

from typing import Any

from harness_catalog import (
    CAPABILITY_VOCAB,
    SkillsMpSource,
    default_skill_queries,
    skill_to_component,
)

# 실제 응답 모양(2026-09-07 skillsmp.com/api/v1/skills/search 관측).
ENTRY = {
    "id": "openclaw-openclaw-agents-skills-autoreview-skill-md",
    "name": "autoreview",
    "author": "openclaw",
    "description": "Structured code review when explicitly requested.",
    "contentLanguage": "en",
    "githubUrl": "https://github.com/openclaw/openclaw/tree/main/.agents/skills/autoreview",
    "skillUrl": "https://skillsmp.com/creators/openclaw/openclaw/agents-skills-autoreview",
    "stars": 389030,
    "updatedAt": 1788351039,
}


def envelope(*skills: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "data": {"skills": list(skills), "pagination": {"page": 1, "total": len(skills)}, "filters": {}},
        "meta": {"requestId": "x", "responseTimeMs": 1},
    }


def fake_fetcher(pages: dict[str, dict[str, Any]] | None = None, record: list[str] | None = None):
    """URL → 응답. 기록 리스트를 주면 호출된 URL 을 남긴다(쿼터 검증용)."""

    def _fetch(url: str) -> dict[str, Any]:
        if record is not None:
            record.append(url)
        if pages is not None and url in pages:
            return pages[url]
        return envelope(ENTRY)

    return _fetch


# ── 컴포넌트 변환 ──


def test_metadata_maps_to_skill_component():
    c = skill_to_component(ENTRY)
    assert c is not None
    assert c.type == "skill"
    assert c.name == "autoreview"
    assert c.summary.startswith("Structured code review")
    assert "review.code" in c.capability_tags


def test_id_is_namespaced_by_source_and_author():
    """소스 간 id 충돌을 피한다 — 로컬 큐레이션이 우선이지만 소스끼리도 안 겹쳐야 한다."""
    c = skill_to_component(ENTRY)
    assert c is not None and c.id == "skillsmp/openclaw/autoreview"


def test_body_is_absent_because_api_does_not_provide_it():
    """API 가 본문을 안 준다 — 지어내지 않고 비워 두고 source 로 출처를 남긴다."""
    c = skill_to_component(ENTRY)
    assert c is not None
    assert not (c.body or "")
    assert c.source == ENTRY["githubUrl"]


def test_stars_do_not_become_usage_count():
    """**핵심** — GitHub 별 수는 우리 실측 채택률이 아니다.

    usage_count 는 Phase 9 피드백 신호이고 랭킹의 _W_USAGE 를 먹인다. 별 수(수십만)를 넣으면
    랭킹을 지배하고 usage_count==0 에 걸린 _W_EXPLORE(신규 탐색 부스트)도 죽는다.
    """
    c = skill_to_component(ENTRY)
    assert c is not None
    assert c.usage_count == 0
    assert c.retention_score == 0.0


def test_harvested_status_is_not_stable():
    """미검증 외부 수확분을 stable 로 올리는 건 큐레이션 결정이다."""
    c = skill_to_component(ENTRY)
    assert c is not None and c.status == "beta"


def test_entry_without_name_is_skipped():
    assert skill_to_component({"author": "a", "description": "d"}) is None


# ── 질의 전략(열거 불가 대응) ──


def test_queries_come_from_controlled_vocabulary():
    """카탈로그가 이해하는 능력 이름으로 검색해야 결과가 어휘에 정렬된다."""
    queries = default_skill_queries()
    assert "code review" in queries
    assert len(queries) <= len(CAPABILITY_VOCAB)  # 어휘 크기로 유계


def test_queries_are_deterministic():
    """같은 어휘 버전이면 같은 harvest — 재현 가능해야 한다."""
    assert default_skill_queries() == default_skill_queries()


def test_query_count_is_capped_for_quota():
    """익명 쿼터가 50 req/day 다 — 질의 수에 상한이 있어야 한다."""
    calls: list[str] = []
    src = SkillsMpSource(fetcher=fake_fetcher(record=calls), max_queries=3)
    src.components()
    assert len(calls) == 3
    assert all("q=" in u and "limit=" in u for u in calls)


def test_page_limit_is_clamped_to_api_max():
    """API 상한(50)을 넘겨 요청하면 거부되므로 미리 자른다."""
    calls: list[str] = []
    SkillsMpSource(fetcher=fake_fetcher(record=calls), page_limit=500, max_queries=1).components()
    assert "limit=50" in calls[0]


# ── 견고성 ──


def test_duplicate_skills_across_queries_are_deduped():
    """여러 질의가 같은 스킬을 물어온다 — 중복이 카탈로그를 부풀리면 안 된다."""
    src = SkillsMpSource(fetcher=fake_fetcher(), max_queries=5)
    comps = src.components()
    assert len(comps) == 1


def test_one_failing_query_does_not_kill_the_harvest():
    """쿼터 초과·일시 장애로 한 질의가 죽어도 나머지는 담겨야 한다."""
    calls: list[str] = []

    def flaky(url: str) -> dict[str, Any]:
        calls.append(url)
        if len(calls) == 1:
            raise TimeoutError("quota")
        return envelope({**ENTRY, "name": f"skill{len(calls)}"})

    comps = SkillsMpSource(fetcher=flaky, max_queries=3).components()
    assert len(calls) == 3
    assert len(comps) >= 1


def test_unexpected_shape_yields_empty_not_crash():
    for bad in ({}, {"data": None}, {"data": {"skills": "nope"}}, {"data": {}}):
        src = SkillsMpSource(fetcher=lambda _u, b=bad: b, max_queries=1)
        assert src.components() == []


def test_origin_tag_is_distinct():
    """DB 적재 시 origin 으로 갈라져야 한다(신뢰 등급·삭제 정합)."""
    assert SkillsMpSource.origin == "skillsmp"
    assert SkillsMpSource.origin not in ("registry", "marketplace", "local")


# ── 본문 없는 skill 이 조용히 새지 않는가 ──


def test_emitter_declares_bodyless_skill_as_loss():
    """껍데기 SKILL.md 는 파일이 생겨 성공처럼 보인다 — 이식 손실로 선언돼야 한다."""
    from harness_resolver import (
        ComponentSelection,
        HarnessConfig,
        HarnessMetadata,
        InMemoryRegistry,
        resolve,
    )
    from harness_runtime import target_losses

    harvested = skill_to_component(ENTRY)
    assert harvested is not None
    reg = InMemoryRegistry([harvested])
    cfg = HarnessConfig(
        metadata=HarnessMetadata(id="bot"),
        components=[ComponentSelection(ref=f"{harvested.id}@0.1.0")],
    )
    resolved = resolve(cfg, reg).resolved
    assert resolved is not None
    features = {lo.feature for lo in target_losses(resolved, "claude-code")}
    assert "skill.body" in features


# ── 설정 배선 (기본 off) ──


def test_off_by_default():
    """다른 라이브 소스와 같이 옵트인이다 — 켜지 않은 외부 호출이 생기면 안 된다."""
    from harness_catalog import build_live_sources
    from harness_catalog.settings import Settings

    cfg = Settings(anthropic_key=None, embedder_mode="local", ranker_mode="heuristic", claude_model="m")
    assert cfg.use_skillsmp is False
    assert build_live_sources(cfg, fetcher=fake_fetcher()) == []


def test_wired_when_enabled():
    from harness_catalog import build_live_sources
    from harness_catalog.settings import Settings

    cfg = Settings(
        anthropic_key=None,
        embedder_mode="local",
        ranker_mode="heuristic",
        claude_model="m",
        skillsmp_mode="on",
        skillsmp_max_queries=2,
    )
    sources = build_live_sources(cfg, fetcher=fake_fetcher())
    assert [type(x).__name__ for x in sources] == ["SkillsMpSource"]
    assert sources[0].components()  # 관통


def test_enabled_source_ttl_is_longer_than_others():
    """쿼터가 빡빡해 자주 돌면 소진된다 — TTL 하한을 보장한다."""
    from harness_catalog import build_live_sources
    from harness_catalog.settings import Settings

    cfg = Settings(
        anthropic_key=None,
        embedder_mode="local",
        ranker_mode="heuristic",
        claude_model="m",
        skillsmp_mode="on",
        registry_ttl=10.0,  # 짧게 줘도
    )
    src = build_live_sources(cfg, fetcher=fake_fetcher())[0]
    assert src._ttl >= 900.0  # noqa: SLF001 — TTL 하한 보장이 계약이다


# ── 인증 키가 죽은 설정이 아닌가 ──


def test_api_key_actually_reaches_the_transport():
    """받아만 두고 안 보내면 죽은 설정이다 — 값을 넣어도 쿼터가 안 늘어난다.

    `Fetcher` 계약이 `(url) -> dict` 라 헤더 인자가 없어서, 키가 있으면 **인증 fetcher 로 교체**한다.
    """
    from harness_catalog import bearer_fetcher

    authed = SkillsMpSource(api_key="sk_live_x", max_queries=1)
    anon = SkillsMpSource(max_queries=1)
    assert authed._authenticated is True  # noqa: SLF001
    assert anon._authenticated is False  # noqa: SLF001
    assert authed._fetch.__qualname__ == bearer_fetcher("t").__qualname__  # noqa: SLF001
    assert authed._fetch is not anon._fetch  # noqa: SLF001


def test_injected_fetcher_wins_over_api_key():
    """테스트·앱이 주입한 fetcher 가 우선이어야 한다 — 아니면 테스트가 네트워크를 탄다."""
    sentinel = fake_fetcher()
    src = SkillsMpSource(api_key="sk_live_x", fetcher=sentinel, max_queries=1)
    assert src._fetch is sentinel  # noqa: SLF001


def test_bearer_fetcher_rejects_non_https():
    """토큰을 평문 http 로 보내지 않는다."""
    import pytest

    with pytest.raises(ValueError, match="https"):
        bearer_fetcher_local = __import__("harness_catalog", fromlist=["bearer_fetcher"]).bearer_fetcher
        bearer_fetcher_local("t")("http://insecure.example/x")
