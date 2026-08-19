"""벡터 스토어 — 임베딩 회수(top-K)용.

MVP 는 인메모리(코사인 정렬). 규모가 커지면 pgvector(Postgres 단일 스토어)로 교체하되
인터페이스는 유지한다(개발: 기술 스택 §2) — pgvector 구현은 `apps/api` 의 `PgVectorStore`
(catalog 는 DB 무의존). 회수는 벡터로만, 이후 구조화 필드로 후처리 필터·검증하는 2단 구조.

스토어 계약(인메모리·pgvector 공통):
  ensure(entries, embed)  entries=[(id, content_hash, doc)] → 필요한 것만 임베딩해 벡터를 보유.
                          pgvector 구현은 (id, content_hash) 가 이미 있으면 재임베딩을 건너뛴다(영속).
  search(query, top_k)    코사인 유사도 상위 K → [(id, score)].
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Protocol

from .embeddings import cosine

EmbedFn = Callable[[list[str]], list[list[float]]]


def content_hash(doc: str) -> str:
    """임베딩 문서의 내용 해시 — 변경 감지용(같은 해시 = 재임베딩 불필요)."""
    return hashlib.sha256(doc.encode("utf-8")).hexdigest()


class VectorStoreLike(Protocol):
    """벡터 스토어 계약(구조적) — 인메모리 `VectorStore` 와 apps/api 의 `PgVectorStore` 가 둘 다 만족.

    Recommender 가 이 Protocol 로 주입받아 인메모리/pgvector 를 갈아끼운다(catalog 는 DB 무의존 유지).
    """

    def ensure(self, entries: list[tuple[str, str, str]], embed: EmbedFn) -> None: ...

    def search(self, query: list[float], top_k: int = 10) -> list[tuple[str, float]]: ...


class VectorStore:
    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}

    def add(self, component_id: str, vector: list[float]) -> None:
        self._vectors[component_id] = vector

    def ensure(self, entries: list[tuple[str, str, str]], embed: EmbedFn) -> None:
        """현 집합을 벡터로 채운다. 인메모리는 영속하지 않으므로 매번 전량 임베딩(현 집합으로 리셋).

        entries: [(id, content_hash, doc)]. content_hash 는 인메모리 경로에선 쓰지 않는다(영속 스토어만
        재임베딩 스킵에 사용). 검색 대상을 현 집합으로 국한하려고 벡터맵을 새로 만든다.
        """
        docs = [doc for _id, _h, doc in entries]
        vectors = embed(docs) if docs else []
        self._vectors = {entry[0]: v for entry, v in zip(entries, vectors, strict=True)}

    def search(self, query: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        scored = [(cid, cosine(query, v)) for cid, v in self._vectors.items()]
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self._vectors)
