"""스코프별 조직 정책 저장소 — Phase 8 의 남은 절반.

**왜 필요한가**: 정책이 요청 본문에서만 오면 클라이언트가 그냥 안 보내서 우회할 수 있다.
CI(`harness resolve --policy`)는 운영자가 직접 주니 그게 맞지만, 제품 안에서 조직이 멤버를
묶으려면 **서버가 들고 있다가 항상 적용**해야 한다. 여기가 그 저장소다.

요청 본문 정책과는 `harness_resolver.strictest` 로 합친다 — 저장된 것은 클라이언트가 낮출 수
없는 하한이고, 클라이언트는 더 엄격해질 수만 있다.

GapDemand·Cooccurrence 와 달리 **비차단이 아니다.** 정책 조회가 실패했을 때 "정책 없음"으로
넘기면 가드레일이 조용히 사라진다 — 그건 사고다. 읽기 실패는 예외로 올려 요청을 실패시킨다.
"""

from __future__ import annotations

import logging
from typing import Any

from harness_resolver import Policy
from sqlalchemy import select
from sqlalchemy.engine import Engine

from .db import scope_policies as _t
from .gap_demand import _dialect_insert
from .store import now_iso

log = logging.getLogger("harness_api")


class PolicyStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._insert = _dialect_insert(engine)

    def get(self, scope_key: str) -> Policy | None:
        """스코프의 저장된 정책. 없으면 None.

        조회 실패를 삼키지 않는다 — "못 읽었으니 정책 없음"은 가드레일을 조용히 끄는 것이다.
        """
        with self._engine.connect() as conn:
            row = conn.execute(select(_t.c.doc).where(_t.c.scope_key == scope_key)).first()
        if row is None:
            return None
        return Policy.model_validate_json(row[0])

    def meta(self, scope_key: str) -> dict[str, Any] | None:
        """정책 + 갱신 정보(화면에 "누가 언제 정했나"를 보여주기 위해)."""
        with self._engine.connect() as conn:
            row = conn.execute(
                select(_t.c.doc, _t.c.updated_at, _t.c.updated_by).where(_t.c.scope_key == scope_key)
            ).first()
        if row is None:
            return None
        return {
            "policy": Policy.model_validate_json(row[0]).model_dump(),
            "updated_at": row[1],
            "updated_by": row[2],
        }

    def put(self, scope_key: str, policy: Policy, updated_by: str = "") -> None:
        """정책 저장(upsert)."""
        ts = now_iso()
        doc = policy.model_dump_json()
        with self._engine.begin() as conn:
            stmt = self._insert(_t).values(
                scope_key=scope_key, doc=doc, updated_at=ts, updated_by=updated_by
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["scope_key"],
                set_={"doc": doc, "updated_at": ts, "updated_by": updated_by},
            )
            conn.execute(stmt)
        log.info("정책 저장: scope=%s by=%s", scope_key, updated_by)

    def delete(self, scope_key: str) -> bool:
        """정책 해제. 반환: 실제로 지워졌는가."""
        with self._engine.begin() as conn:
            result = conn.execute(_t.delete().where(_t.c.scope_key == scope_key))
        removed = bool(result.rowcount)
        if removed:
            log.info("정책 해제: scope=%s", scope_key)
        return removed
