"""승격 승인 저장소 — 공유 카탈로그 승격의 다인 승인(하드닝 후속 #5 잔여).

**왜 필요한가**: 승격은 `origin='promoted'` 로 **전 유저**의 검색·추천에 등장한다. 지금까지는
write 권한만 있으면 단독으로 올릴 수 있었다 — 공급망 관점에서 한 사람의 판단이 전체에 퍼지는
구조다(CONTRIBUTING §3 은 자동 승격을 금지하지만, "명시 액션 1회"는 여전히 단독이다).

설계 판단 셋:

1. **자기 승인은 정족수에 안 든다.** 작성자가 자기 것을 승인해 통과시킬 수 있으면 "다인 승인"이
   이름만 남는다. 임계값은 **작성자 외 승인자 수**로 센다.
2. **(스코프, 컴포넌트, 승인자) 단일 행.** 한 사람이 여러 번 눌러 정족수를 채울 수 없다.
3. **컴포넌트가 바뀌면 과거 승인이 무효다.** 승인 당시 버전을 함께 저장하고, 현재 버전과 다른
   승인은 세지 않는다 — 심사한 내용과 올라가는 내용이 달라지면 심사가 무의미하다.

정책 조회처럼 **실패를 삼키지 않는다.** "못 읽었으니 승인 0"으로 넘기면 게이트가 조용히 닫히는
쪽이라 안전하지만, "못 읽었으니 통과"가 되지 않도록 예외를 올린다.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.engine import Engine

from .db import component_approvals as _t
from .gap_demand import _dialect_insert
from .store import now_iso

log = logging.getLogger("harness_api")

# 승격에 필요한 **작성자 외** 승인 수. 기본 0 = 기존 동작(단독 승격) 완전 불변 — 조직이 켠다.
DEFAULT_MIN_APPROVALS = 0


def required_approvals() -> int:
    """배포 단위 정족수(`HARNESS_PROMOTION_APPROVALS`).

    스코프별이 아니라 **배포 전역**인 이유: 승격 대상은 전 유저가 보는 단일 공유 카탈로그다.
    영향 범위가 전역이므로 정족수도 전역 정책이 맞다(팀별로 느슨하게 열 수 있으면 우회가 된다).
    """
    raw = os.environ.get("HARNESS_PROMOTION_APPROVALS", str(DEFAULT_MIN_APPROVALS))
    try:
        return max(0, int(raw))
    except ValueError:
        log.warning("HARNESS_PROMOTION_APPROVALS 파싱 실패(%r) — 기본 %d 사용", raw, DEFAULT_MIN_APPROVALS)
        return DEFAULT_MIN_APPROVALS


class ApprovalStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._insert = _dialect_insert(engine)

    def record(
        self, scope_key: str, cid: str, approver_id: str, version: int, note: str = ""
    ) -> None:
        """승인 기록(upsert). 같은 사람이 다시 누르면 버전·시각만 갱신된다(중복 카운트 없음)."""
        ts = now_iso()
        with self._engine.begin() as conn:
            stmt = self._insert(_t).values(
                scope_key=scope_key,
                component_id=cid,
                approver_id=approver_id,
                component_version=version,
                note=note,
                created_at=ts,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["scope_key", "component_id", "approver_id"],
                set_={"component_version": version, "note": note, "created_at": ts},
            )
            conn.execute(stmt)

    def withdraw(self, scope_key: str, cid: str, approver_id: str) -> bool:
        """승인 철회. 반환: 실제로 지워졌는가."""
        with self._engine.begin() as conn:
            result = conn.execute(
                _t.delete().where(
                    and_(
                        _t.c.scope_key == scope_key,
                        _t.c.component_id == cid,
                        _t.c.approver_id == approver_id,
                    )
                )
            )
        return bool(result.rowcount)

    def list(self, scope_key: str, cid: str) -> list[dict[str, Any]]:
        """이 컴포넌트의 모든 승인(버전 무관 — 호출부가 현재 버전과 대조해 유효성을 판단한다)."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(
                    _t.c.approver_id, _t.c.component_version, _t.c.note, _t.c.created_at
                ).where(and_(_t.c.scope_key == scope_key, _t.c.component_id == cid))
            ).all()
        return [
            {"approver_id": r[0], "component_version": r[1], "note": r[2], "created_at": r[3]}
            for r in rows
        ]

    def clear(self, scope_key: str, cid: str) -> int:
        """승격 완료 후 정리. 반환: 지워진 승인 수."""
        with self._engine.begin() as conn:
            result = conn.execute(
                _t.delete().where(and_(_t.c.scope_key == scope_key, _t.c.component_id == cid))
            )
        return int(result.rowcount or 0)
