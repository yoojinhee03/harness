"""pgvector 백엔드 벡터 스토어 — 임베딩을 Postgres 에 영속(재시작 시 재임베딩 회피) + 코사인 검색.

`harness_catalog.store.VectorStore` 와 같은 계약(ensure/search)을 만족해 Recommender 에 주입한다.
catalog 패키지는 DB 무의존이라 pgvector 구현은 여기(apps/api, sqlalchemy 보유)에 둔다.

핵심: (id, content_hash) 가 이미 있으면 재임베딩을 **건너뛴다**. 그래서 재시작·재인덱싱 때 카탈로그
전량을 매번 OpenAI 로 재임베딩하던 비용/지연이 사라진다(변경분만 임베딩).

`embedding vector`(차원 미고정) 컬럼을 쓴다 — 임베더(OpenAI 1536·Local 512 등)가 달라도 스키마 변경이
필요 없다. 검색은 현 파이프라인이 전체를 회수해 재랭킹하므로 ANN 인덱스 없이 seq-scan 코사인으로 충분
(수천 규모). 벡터는 문자열 리터럴 `[..]::vector` 로 넘겨 pgvector 파이썬 어댑터 의존을 피한다.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

from .store import now_iso

EmbedFn = Callable[[list[str]], list[list[float]]]


def _vec_literal(vector: list[float]) -> str:
    """[0.1,0.2,...] — pgvector 가 파싱하는 벡터 리터럴(::vector 로 캐스팅)."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class PgVectorStore:
    """catalog_embeddings 테이블 기반 영속 벡터 스토어. model 시그니처로 임베더별 행을 분리한다."""

    def __init__(self, engine: Engine, model: str) -> None:
        self._engine = engine
        self._model = model  # 임베더 시그니처(예: "openai:text-embedding-3-small") — 재임베딩 스킵 키의 일부.
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS catalog_embeddings ("
                    "id TEXT NOT NULL, model TEXT NOT NULL, content_hash TEXT NOT NULL, "
                    "embedding vector NOT NULL, updated_at TEXT NOT NULL, "
                    "PRIMARY KEY (id, model))"
                )
            )

    def ensure(self, entries: list[tuple[str, str, str]], embed: EmbedFn) -> None:
        """entries=[(id, content_hash, doc)]. 이미 같은 (id, content_hash) 가 있으면 임베딩 스킵.

        변경/신규만 임베딩·upsert 하고, 현 집합에 없는 stale 행은 삭제한다(검색이 옛 컴포넌트 반환 방지).
        """
        with self._engine.begin() as conn:
            existing = {
                row[0]: row[1]
                for row in conn.execute(
                    text("SELECT id, content_hash FROM catalog_embeddings WHERE model = :m"),
                    {"m": self._model},
                )
            }
            missing = [(cid, h, doc) for (cid, h, doc) in entries if existing.get(cid) != h]
            if missing:
                vectors = embed([doc for _cid, _h, doc in missing])
                ts = now_iso()
                rows = [
                    {"id": cid, "m": self._model, "h": h, "e": _vec_literal(vec), "ts": ts}
                    for (cid, h, _doc), vec in zip(missing, vectors, strict=True)
                ]
                conn.execute(
                    text(
                        "INSERT INTO catalog_embeddings (id, model, content_hash, embedding, updated_at) "
                        "VALUES (:id, :m, :h, (:e)::vector, :ts) "
                        "ON CONFLICT (id, model) DO UPDATE SET "
                        "content_hash = EXCLUDED.content_hash, embedding = EXCLUDED.embedding, "
                        "updated_at = EXCLUDED.updated_at"
                    ),
                    rows,
                )
            current = {cid for cid, _h, _doc in entries}
            stale = [cid for cid in existing if cid not in current]
            if stale:
                conn.execute(
                    text("DELETE FROM catalog_embeddings WHERE model = :m AND id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"m": self._model, "ids": stale},
                )

    def search(self, query: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        """코사인 유사도 상위 K. `<=>` 는 코사인 거리라 유사도 = 1 - 거리."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, 1 - (embedding <=> (:q)::vector) AS score "
                    "FROM catalog_embeddings WHERE model = :m "
                    "ORDER BY embedding <=> (:q)::vector LIMIT :k"
                ),
                {"q": _vec_literal(query), "m": self._model, "k": int(top_k)},
            ).all()
        return [(row[0], float(row[1])) for row in rows]

    def __len__(self) -> int:
        with self._engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM catalog_embeddings WHERE model = :m"), {"m": self._model}
            ).scalar()
        return int(n or 0)
