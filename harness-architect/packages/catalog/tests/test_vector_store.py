"""벡터 스토어 계약 — ensure/search + 영속 스토어의 재임베딩 스킵(pgvector 배선의 핵심 이득).

PgVectorStore 자체는 Postgres 필요(라이브 검증)라, 같은 ensure 계약을 따르는 메모리 더블로 Recommender
통합·재사용 로직을 결정적으로 검증한다.
"""

from __future__ import annotations

from harness_catalog.embeddings import cosine
from harness_catalog.recommender import Recommender
from harness_catalog.store import VectorStore, content_hash
from harness_resolver import Component, InMemoryRegistry


def _comp(cid: str, summary: str) -> Component:
    return Component(
        id=cid, type="skill", name=cid, version="1.0.0", summary=summary,
        provides=[], capability_tags=[], body="x", entrypoint=f"skills/{cid}/SKILL.md",
    )


class _CountingEmbedder:
    name = "fake:v1"

    def __init__(self) -> None:
        self.docs = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.docs += len(texts)
        return [[float(len(t)), float(i)] for i, t in enumerate(texts)]


class _PersistentStore:
    """PgVectorStore 계약을 흉내내는 메모리 더블 — (id, content_hash) 그대로면 재임베딩 스킵."""

    def __init__(self) -> None:
        self._rows: dict[str, tuple[str, list[float]]] = {}

    def ensure(self, entries, embed):  # type: ignore[no-untyped-def]
        missing = [(i, h, d) for (i, h, d) in entries if self._rows.get(i, (None,))[0] != h]
        if missing:
            vectors = embed([d for _i, _h, d in missing])
            for (i, h, _d), v in zip(missing, vectors, strict=True):
                self._rows[i] = (h, v)
        current = {i for i, _h, _d in entries}
        for i in [k for k in self._rows if k not in current]:
            del self._rows[i]

    def search(self, query, top_k=10):  # type: ignore[no-untyped-def]
        scored = [(i, cosine(query, v)) for i, (_h, v) in self._rows.items()]
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]


def test_content_hash_stable_and_sensitive():
    assert content_hash("a") == content_hash("a")
    assert content_hash("a") != content_hash("b")


def test_inmemory_store_ensure_and_search():
    st = VectorStore()
    st.ensure([("a", "h1", "doc a"), ("b", "h2", "doc bb")], lambda docs: [[1.0, 0.0], [0.0, 1.0]])
    assert len(st) == 2
    assert st.search([1.0, 0.0], top_k=1)[0][0] == "a"
    # 인메모리는 매 ensure 마다 현 집합으로 리셋
    st.ensure([("c", "h3", "doc c")], lambda docs: [[0.5, 0.5]])
    assert len(st) == 1 and st.search([0.5, 0.5], 1)[0][0] == "c"


def test_persistent_store_skips_reembedding_across_reindex():
    reg = InMemoryRegistry([_comp("a", "alpha"), _comp("b", "beta")])
    emb = _CountingEmbedder()
    store = _PersistentStore()
    Recommender(reg, embedder=emb, store=store)  # 첫 인덱싱 — 2개 임베딩
    assert emb.docs == 2
    Recommender(reg, embedder=emb, store=store)  # 재인덱싱 — 내용 동일 → 재임베딩 0
    assert emb.docs == 2  # 증가 없음(영속 스토어가 스킵)


def test_persistent_store_reembeds_only_changed():
    store = _PersistentStore()
    emb = _CountingEmbedder()
    Recommender(InMemoryRegistry([_comp("a", "alpha"), _comp("b", "beta")]), embedder=emb, store=store)
    assert emb.docs == 2
    # b 내용 변경 + c 신규 → 2개만 재임베딩(a 는 스킵), a 는 유지
    Recommender(
        InMemoryRegistry([_comp("a", "alpha"), _comp("b", "beta v2"), _comp("c", "gamma")]),
        embedder=emb, store=store,
    )
    assert emb.docs == 4  # 2(초기) + 2(b변경·c신규)
