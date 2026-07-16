"""벡터 스토어 — 임베딩 회수(top-K)용.

MVP 는 인메모리(코사인 정렬). 규모가 커지면 pgvector(Postgres 단일 스토어)로 교체하되
인터페이스는 유지한다(개발: 기술 스택 §2). 회수는 벡터로만, 이후 구조화 필드로 후처리
필터·검증하는 2단 구조(카탈로그 스키마 §4).
"""

from __future__ import annotations

from .embeddings import cosine


class VectorStore:
    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}

    def add(self, component_id: str, vector: list[float]) -> None:
        self._vectors[component_id] = vector

    def search(self, query: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        scored = [(cid, cosine(query, v)) for cid, v in self._vectors.items()]
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self._vectors)
