"""컴포넌트 공출현 집계(DB 영속) — 하드닝 TASK 5e.

한 하네스(verify 로 검증된 실제 레포 등)에서 **함께 등장한 컴포넌트 쌍**의 빈도를 누적한다. verify
`--record` 가 COOCCUR_SIGNAL 로그를 내면 `scripts/aggregate_cooccurrence.py` 가 이 스토어로 durable
집계한다. 협업 필터링 신호("이 MCP 를 쓰면 이 훅도 같이 쓴다") — 랭킹 투입은 백로그.

쌍은 comp_a < comp_b(사전순)로 정규화해 대칭 중복을 없앤다. 원자적 ON CONFLICT 증분·비차단
(GapDemand 와 동일 규약 — 쓰기/읽기 실패가 호출자를 깨지 않는다).
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine

from .db import component_cooccurrence as _t
from .gap_demand import _dialect_insert
from .store import now_iso

log = logging.getLogger("harness_api")


def _pairs(ids: Iterable[str]) -> list[tuple[str, str]]:
    """중복 제거·정렬 후 정규화된 쌍 (a<b) 목록. 1개 이하면 빈 목록."""
    uniq = sorted({i for i in ids if i})
    return list(itertools.combinations(uniq, 2))


class CooccurrenceStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._insert = _dialect_insert(engine)

    def record(self, component_ids: Iterable[str]) -> int:
        """한 하네스의 컴포넌트 id 집합 → 모든 쌍의 카운트를 원자적으로 +1. 반환: 갱신 쌍 수(비차단)."""
        pairs = _pairs(component_ids)
        if not pairs:
            return 0
        ts = now_iso()
        try:
            with self._engine.begin() as conn:
                for a, b in pairs:
                    stmt = self._insert(_t).values(
                        comp_a=a, comp_b=b, count=1, first_seen_at=ts, last_seen_at=ts
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["comp_a", "comp_b"],
                        set_={"count": _t.c.count + 1, "last_seen_at": ts},
                    )
                    conn.execute(stmt)
            return len(pairs)
        except Exception as exc:  # noqa: BLE001 — 비차단
            log.warning("공출현 기록 실패(무시): %s", exc)
            return 0

    def top(self, n: int = 20) -> list[dict[str, Any]]:
        """공출현 빈도 상위 쌍. 실패 시 빈 목록(비차단)."""
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(_t.c.comp_a, _t.c.comp_b, _t.c.count)
                    .order_by(_t.c.count.desc())
                    .limit(max(0, n))
                ).all()
            return [{"pair": [r[0], r[1]], "count": r[2]} for r in rows]
        except Exception as exc:  # noqa: BLE001 — 비차단
            log.warning("공출현 조회 실패(무시): %s", exc)
            return []
