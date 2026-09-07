"""피드백 관측 스토어(DB 영속) — Phase 9.

확정 시점(eject·하네스 저장 등)에 **무엇을 골랐고 무엇을 버렸는지**를 누적한다. 집계·중립 판정은
`harness_catalog.feedback`(순수)이 하고, 여기선 원자적으로 세기만 한다.

GapDemand·CooccurrenceStore 와 같은 규약이다 — **비차단**(쓰기/읽기 실패가 호출자를 깨지 않는다).
피드백을 못 남긴 것 때문에 eject 가 실패하면 안 된다.

**옵트인이 기본 꺼짐이다**(`HARNESS_FEEDBACK=on`). 신호가 없으면 랭킹은 지금과 완전히 같다 —
사용자가 켜지 않은 수집으로 추천 품질이 조용히 달라지면 안 된다.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import Any

from harness_catalog import FeedbackRecord
from sqlalchemy import select
from sqlalchemy.engine import Engine

from .db import component_feedback as _t
from .gap_demand import _dialect_insert
from .store import now_iso

log = logging.getLogger("harness_api")


def feedback_enabled() -> bool:
    """옵트인 게이트. 기본 꺼짐 — 켜지 않으면 아무것도 기록하지 않는다."""
    return os.environ.get("HARNESS_FEEDBACK", "").lower() in ("on", "1", "true")


class FeedbackStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._insert = _dialect_insert(engine)

    def record(self, selected: Iterable[str], dropped: Iterable[str]) -> int:
        """선택/폐기 관측을 원자적으로 +1. 반환: 갱신된 컴포넌트 수(비차단).

        같은 id 가 양쪽에 오면 호출부(`FeedbackEvent.normalized`)가 이미 걸러준다.
        """
        counts: dict[str, tuple[int, int]] = {}
        for cid in selected:
            if cid:
                s, d = counts.get(cid, (0, 0))
                counts[cid] = (s + 1, d)
        for cid in dropped:
            if cid:
                s, d = counts.get(cid, (0, 0))
                counts[cid] = (s, d + 1)
        if not counts:
            return 0

        ts = now_iso()
        try:
            with self._engine.begin() as conn:
                for cid, (sel, drop) in counts.items():
                    stmt = self._insert(_t).values(
                        component_id=cid,
                        selected_count=sel,
                        dropped_count=drop,
                        first_seen_at=ts,
                        last_seen_at=ts,
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["component_id"],
                        set_={
                            "selected_count": _t.c.selected_count + sel,
                            "dropped_count": _t.c.dropped_count + drop,
                            "last_seen_at": ts,
                        },
                    )
                    conn.execute(stmt)
            return len(counts)
        except Exception as exc:  # noqa: BLE001 — 비차단
            log.warning("피드백 기록 실패(무시): %s", exc)
            return 0

    def records(self) -> list[FeedbackRecord]:
        """전체 관측 — 순수 집계기(`harness_catalog.feedback`)의 입력. 실패 시 빈 목록(비차단)."""
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(_t.c.component_id, _t.c.selected_count, _t.c.dropped_count)
                ).all()
            return [
                FeedbackRecord(component_id=r[0], selected_count=r[1], dropped_count=r[2])
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001 — 비차단
            log.warning("피드백 조회 실패(무시): %s", exc)
            return []

    def top(self, n: int = 20) -> list[dict[str, Any]]:
        """관측 많은 순 — 운영 확인용."""
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(_t.c.component_id, _t.c.selected_count, _t.c.dropped_count)
                    .order_by((_t.c.selected_count + _t.c.dropped_count).desc())
                    .limit(max(0, n))
                ).all()
            return [
                {"component_id": r[0], "selected": r[1], "dropped": r[2], "observations": r[1] + r[2]}
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001 — 비차단
            log.warning("피드백 조회 실패(무시): %s", exc)
            return []
