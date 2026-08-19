"""Gap 수요 집계(DB 영속) — '자주 요청되나 카탈로그가 못 채운 능력'을 durable 하게 센다(TASK 2).

인메모리 Counter(재시작 리셋·레플리카 개별)를 DB 로 승격했다. 우선순위가 높은 이유는 성능이 아니라
**복구 불가능성**이다 — 지금 버려지는 수요 데이터는 나중에 되찾을 수 없다.

설계:
- **grain = capability 단일 행.** requested_count 는 누적, source/provenance 는 최근값(last-write).
- **원자적 증분(ON CONFLICT DO UPDATE)** — 다중 레플리카 동시 기록에도 카운트가 정확하다.
- **비차단** — DB 쓰기/읽기 실패가 추천·스튜디오 응답을 깨지 않는다(경고 로그만, 예외 삼킴).
- **provenance**(catalog_revision·caps_source·vocab_version·candidate_count) — 빈 caps 탓 거짓 gap 을
  나중에 재평가·정화하기 위한 근거. `false_gaps`/`mark_resolved`(+ scripts/reeval_gaps.py)가 쓴다.
- **hot-gap 게이팅** — `hot_capabilities(require_trusted=True)` 는 caps_source!='heuristic' 만 노출한다.
  TASK 3 전에는 전부 heuristic 이라 hot 집합이 비어 사용자에게 거짓 gap 을 "만들라"고 노출하지 않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from .db import gap_demand as _t
from .store import now_iso

log = logging.getLogger("harness_api")


def _parse(item: Any) -> tuple[str, str] | None:
    if isinstance(item, dict):
        cap, st = item.get("capability"), item.get("suggested_type")
    else:
        cap, st = getattr(item, "capability", None), getattr(item, "suggested_type", None)
    return (str(cap), str(st or "")) if cap else None


def _dialect_insert(engine: Engine) -> Any:
    """dialect 별 upsert insert(on_conflict_do_update 지원). sqlite/postgresql 반환 타입이 달라 Any."""
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # sqlite(개발) 및 기본

    return sqlite_insert


class GapDemand:
    """capability 별 요청 수요를 DB 에 누적(원자적·비차단). 구 인메모리 Counter 의 대체."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._insert = _dialect_insert(engine)

    def record(
        self,
        gaps: list[Any],
        *,
        source: str = "recommend",
        catalog_revision: str = "",
        candidate_count: int = 0,
        caps_source: str = "heuristic",
        vocab_version: str = "",
    ) -> None:
        """gap 목록을 provenance 와 함께 원자적으로 누적. 실패해도 예외를 던지지 않는다(비차단)."""
        parsed = [p for p in (_parse(g) for g in (gaps or [])) if p is not None]
        if not parsed:
            return
        ts = now_iso()
        try:
            with self._engine.begin() as conn:
                for cap, st in parsed:
                    stmt = self._insert(_t).values(
                        capability=cap,
                        requested_count=1,
                        first_seen_at=ts,
                        last_seen_at=ts,
                        suggested_type=st,
                        resolved_at=None,
                        source=source,
                        catalog_revision=catalog_revision,
                        caps_source=caps_source,
                        vocab_version=vocab_version,
                        candidate_count=candidate_count,
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["capability"],
                        set_={
                            "requested_count": _t.c.requested_count + 1,  # 원자적 증분(기존값+1)
                            "last_seen_at": ts,
                            "suggested_type": st or _t.c.suggested_type,  # 최근 비어있지 않은 값 유지
                            "source": source,
                            "catalog_revision": catalog_revision,
                            "caps_source": caps_source,
                            "vocab_version": vocab_version,
                            "candidate_count": candidate_count,
                        },
                    )
                    conn.execute(stmt)
        except Exception as exc:  # noqa: BLE001 — 비차단: 수요 기록 실패가 응답을 깨지 않는다
            log.warning("gap 수요 기록 실패(무시): %s", exc)

    def top(self, n: int = 10) -> list[dict[str, Any]]:
        """요청 빈도 내림차순, 미해결(resolved_at NULL) 우선. 실패 시 빈 목록(비차단)."""
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(
                        _t.c.capability, _t.c.requested_count, _t.c.suggested_type, _t.c.resolved_at
                    )
                    .order_by(_t.c.resolved_at.is_(None).desc(), _t.c.requested_count.desc())
                    .limit(max(0, n))
                ).all()
            return [
                {
                    "capability": r[0],
                    "count": r[1],
                    "suggested_type": r[2] or "",
                    "resolved": r[3] is not None,
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001 — 비차단
            log.warning("gap top 조회 실패(무시): %s", exc)
            return []

    def hot_capabilities(self, n: int = 10, *, require_trusted: bool = True) -> set[str]:
        """자주 요청되는 미해결 gap 능력. require_trusted 면 caps_source!='heuristic' 만(거짓 gap 노출 억제)."""
        try:
            with self._engine.connect() as conn:
                q = select(_t.c.capability).where(_t.c.resolved_at.is_(None))
                if require_trusted:
                    q = q.where(_t.c.caps_source != "heuristic")
                q = q.order_by(_t.c.requested_count.desc()).limit(max(0, n))
                return {r[0] for r in conn.execute(q).all()}
        except Exception as exc:  # noqa: BLE001 — 비차단
            log.warning("hot gap 조회 실패(무시): %s", exc)
            return set()

    def mark_resolved(self, provided_caps: Iterable[str]) -> int:
        """이제 공급이 생긴 능력의 미해결 gap 에 resolved_at 을 채운다(sync 후 호출). 반환: 갱신 개수."""
        caps = list(provided_caps or [])
        if not caps:
            return 0
        try:
            with self._engine.begin() as conn:
                r = conn.execute(
                    update(_t)
                    .where(_t.c.capability.in_(caps), _t.c.resolved_at.is_(None))
                    .values(resolved_at=now_iso())
                )
            return r.rowcount or 0
        except Exception as exc:  # noqa: BLE001 — 비차단
            log.warning("gap resolved 표시 실패(무시): %s", exc)
            return 0

    def false_gaps(self, provided_caps: Iterable[str]) -> list[dict[str, Any]]:
        """재평가 인터페이스 — 지금 공급 가능한(=거짓) gap 기록을 반환. TASK 3 이후 정화에 쓴다.

        빈 caps 컴포넌트가 능력 매칭에서 이탈해 과거엔 제공 가능한 능력도 gap 으로 기록됐다. caps
        커버리지가 오른 뒤, 현재 공급 가능한 능력 집합으로 과거 기록을 재판정한다.
        """
        caps = list(provided_caps or [])
        if not caps:
            return []
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(
                        _t.c.capability,
                        _t.c.requested_count,
                        _t.c.caps_source,
                        _t.c.catalog_revision,
                        _t.c.resolved_at,
                    )
                    .where(_t.c.capability.in_(caps))
                    .order_by(_t.c.requested_count.desc())
                ).all()
            return [
                {
                    "capability": r[0],
                    "count": r[1],
                    "caps_source": r[2],
                    "catalog_revision": r[3],
                    "already_resolved": r[4] is not None,
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001 — 비차단
            log.warning("gap 재평가 조회 실패(무시): %s", exc)
            return []
