"""추천기 라이브 갱신 테스트 — registry generation 변화 시 재인덱싱, 아니면 재사용.

FederatedRegistry.generation() 이 라이브 내용 변화를 반영하는지 + LiveRecommender 가 그 변화만큼만
Recommender 를 재구성하는지. 임베더는 키 없으면 LocalEmbedder(오프라인)라 네트워크 불필요.
"""

from __future__ import annotations

from harness_catalog import FederatedRegistry, LiveRecommender
from harness_resolver import Component, InMemoryRegistry


def _comp(cid: str, provides: list[str] | None = None) -> Component:
    return Component(id=cid, type="mcp", name=cid.upper(), version="1.0.0", provides=provides or [])


class SnapshotSource:
    """현재 스냅샷을 안정적으로 돌려주는 fake 소스. `advance()` 로만 다음 배치로 넘어간다(TTL refresh 모사).

    실제 TTL 캐시처럼 같은 refresh 안에선 components() 가 동일 리스트를 반환해야 generation·인덱싱이
    일관된다(호출마다 전진하면 비현실적).
    """

    def __init__(self, batches: list[list[Component]]) -> None:
        self._batches = batches
        self.idx = 0

    def advance(self) -> None:
        self.idx = min(self.idx + 1, len(self._batches) - 1)

    def components(self) -> list[Component]:
        return self._batches[self.idx]


def test_generation_changes_when_live_content_changes():
    src = SnapshotSource([[_comp("a")], [_comp("a"), _comp("b")]])
    fed = FederatedRegistry(InMemoryRegistry([]), [src])
    g1 = fed.generation()
    g1_again = fed.generation()
    assert g1 == g1_again  # 같은 스냅샷 → 안정
    src.advance()
    assert fed.generation() != g1  # 내용 변화 → generation 변경


def test_generation_stable_for_static_registry():
    fed = FederatedRegistry(InMemoryRegistry([_comp("a")]), [])
    assert fed.generation() == fed.generation()


def test_live_recommender_rebuilds_only_on_generation_change():
    class FakeReg:
        def __init__(self) -> None:
            self.gen = 0
            self._comps = [_comp("a")]

        def generation(self) -> int:
            return self.gen

        def all(self) -> list[Component]:
            return self._comps

        def get(self, cid: str, version: str | None = None) -> Component | None:
            return None

        def get_base(self, name: str):  # noqa: ANN201
            return None

    reg = FakeReg()
    lr = LiveRecommender(reg)
    r1 = lr.get()
    r2 = lr.get()
    assert r1 is r2  # generation 불변 → 재사용(재임베딩 안 함)

    reg.gen = 1  # 라이브 내용 변경 신호
    assert lr.get() is not r1  # generation 변경 → 재구성


def test_live_recommender_static_registry_builds_once():
    lr = LiveRecommender(InMemoryRegistry([_comp("a")]))
    assert lr.get() is lr.get()  # generation() 없는 정적 레지스트리 → 1회 고정


def test_live_recommender_reflects_new_component_in_results():
    a = _comp("web/search", ["web.search"])
    b = _comp("mail/send", ["comms.email"])
    src = SnapshotSource([[a], [a, b]])
    fed = FederatedRegistry(InMemoryRegistry([]), [src])
    lr = LiveRecommender(fed)

    ids1 = {r.id for r in lr.get().recommend("이메일 보내기", top_k=5).recommendations}
    assert "mail/send" not in ids1  # 첫 스냅샷엔 없음

    src.advance()  # TTL refresh 로 mail/send 유입
    ids2 = {r.id for r in lr.get().recommend("이메일 보내기", top_k=5).recommendations}
    assert "mail/send" in ids2  # 재인덱싱되어 추천에 등장
