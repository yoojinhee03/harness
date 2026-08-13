"""Capability LLM 보강 테스트 — 네트워크 없이 fake classifier 주입.

무보강 폴백(분류기 없음/off) · caps 빈 것만 보강 · 통제 어휘 필터 · 배치 · 상한 · 라이브 소스 연동.
"""

from __future__ import annotations

from harness_catalog import CapabilityEnricher, MCPRegistrySource
from harness_resolver import Component


def _comp(cid: str, name: str, caps: list[str] | None = None) -> Component:
    return Component(id=cid, type="mcp", name=name, version="1.0.0", capability_tags=caps or [])


class RecordingClassifier:
    """호출을 기록하고 미리 정한 매핑을 돌려주는 fake. 자유 텍스트 오염(cap 아님)도 섞어 필터를 검증."""

    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self.mapping = mapping
        self.batches: list[list[str]] = []

    def __call__(self, items: list[tuple[str, str]]) -> dict[str, list[str]] | None:
        self.batches.append([i for i, _ in items])
        return {cid: self.mapping.get(cid, []) for cid, _ in items}


def test_no_classifier_is_noop():
    comps = [_comp("a/x", "X")]
    enr = CapabilityEnricher(classifier=None)
    assert enr.active is False
    out = enr.enrich(comps)
    assert out[0].capability_tags == []  # 무보강


def test_enriches_only_empty_caps_and_filters_vocab():
    clf = RecordingClassifier(
        {
            "a/empty": ["web.search", "made.up.cap", "vcs.ci-cd"],  # 중간은 어휘 밖 → 필터
            "a/tagged": ["comms.email"],  # 이미 태그 있음 → 건드리지 않음
        }
    )
    tagged = _comp("a/tagged", "Slack", caps=["comms.messaging"])
    empty = _comp("a/empty", "Search server")
    out = CapabilityEnricher(classifier=clf).enrich([tagged, empty])

    by_id = {c.id: c for c in out}
    assert by_id["a/empty"].capability_tags == ["web.search", "vcs.ci-cd"]  # 어휘 밖 제거
    assert by_id["a/empty"].provides == ["web.search", "vcs.ci-cd"]  # provides 도 동기
    assert by_id["a/tagged"].capability_tags == ["comms.messaging"]  # 기존 유지
    assert clf.batches == [["a/empty"]]  # 빈 것만 대상


def test_batching_splits_targets():
    clf = RecordingClassifier({})
    comps = [_comp(f"a/{i}", f"n{i}") for i in range(5)]
    CapabilityEnricher(classifier=clf, batch_size=2).enrich(comps)
    assert [len(b) for b in clf.batches] == [2, 2, 1]  # 5개 → 2/2/1


def test_max_enrich_caps_targets():
    clf = RecordingClassifier({})
    comps = [_comp(f"a/{i}", f"n{i}") for i in range(10)]
    CapabilityEnricher(classifier=clf, batch_size=100, max_enrich=3).enrich(comps)
    assert sum(len(b) for b in clf.batches) == 3  # 상한 3개만 분류 호출


def test_failed_classifier_keeps_original():
    def dead(_items: list[tuple[str, str]]) -> dict[str, list[str]] | None:
        return None

    comps = [_comp("a/x", "X")]
    CapabilityEnricher(classifier=dead).enrich(comps)
    assert comps[0].capability_tags == []  # 실패 → 원본 유지, 크래시 없음


def test_registry_source_applies_enricher():
    # 라이브 소스가 수확 후 enricher 를 태우는지 — remote 서버는 heuristic 으로 caps 가 비어야 대상이 됨.
    from urllib.parse import parse_qs, urlparse

    entry = {
        "server": {
            "name": "acme/search",
            "title": "Search",
            "description": "generic tool",  # 휴리스틱 키워드 미매칭 → caps 빔
            "version": "1.0.0",
            "remotes": [{"type": "streamable-http", "url": "https://mcp.acme/x"}],
        },
        "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "isLatest": True}},
    }

    def fetcher(url: str) -> dict:
        _ = parse_qs(urlparse(url).query)
        return {"servers": [entry], "metadata": {}}

    clf = RecordingClassifier({"acme/search": ["web.search"]})
    src = MCPRegistrySource(
        fetcher=fetcher, clock=lambda: 0.0, enricher=CapabilityEnricher(classifier=clf)
    )
    comps = src.components()
    assert comps[0].capability_tags == ["web.search"]  # 라이브 수확 → 보강 적용
