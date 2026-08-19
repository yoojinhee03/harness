"""Gap 수요 집계(인메모리) — '자주 요청되나 카탈로그에 없는 능력'을 런타임에 센다(Phase 14 후속).

recommend/스튜디오 검색이 gap 을 낼 때마다 capability 를 누적한다. 스튜디오가 이걸 근거로 "자주 요청되는
공백 — 만들면 카탈로그에 남아 재사용됨"을 능동 제안한다(gap 집계 → 저작 제안). 프로세스-로컬(재시작 리셋·
레플리카 개별)인 라이브 UX 신호다. 감사·시딩용 durable 집계는 GAP_SIGNAL 로그 + `aggregate_gaps.py`(오프라인).
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any


def _parse(item: Any) -> tuple[str, str] | None:
    if isinstance(item, dict):
        cap, st = item.get("capability"), item.get("suggested_type")
    else:
        cap, st = getattr(item, "capability", None), getattr(item, "suggested_type", None)
    return (str(cap), str(st or "")) if cap else None


class GapDemand:
    """capability → 요청 횟수 누적(스레드 세이프). suggested_type 은 최근값 유지."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._type: dict[str, str] = {}
        self._lock = threading.Lock()

    def record(self, gaps: list[Any]) -> None:
        with self._lock:
            for g in gaps or []:
                parsed = _parse(g)
                if parsed is None:
                    continue
                cap, st = parsed
                self._counts[cap] += 1
                if st:
                    self._type[cap] = st

    def top(self, n: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"capability": c, "count": cnt, "suggested_type": self._type.get(c, "")}
                for c, cnt in self._counts.most_common(max(0, n))
            ]

    def hot_capabilities(self, n: int = 10) -> set[str]:
        return {r["capability"] for r in self.top(n)}
