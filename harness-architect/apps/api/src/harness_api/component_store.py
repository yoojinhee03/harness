"""유저 저작 컴포넌트 저장소(SQL, 스코프 격리) — `HarnessStore` 를 미러링.

채팅으로 만든 카탈로그 구성요소(v1: context)를 스코프(`personal:<uid>` / `team:<tid>`)로 격리 저장한다.
put 마다 버전을 올리며 이전 버전을 user_component_versions 에 보관(최근 N). `status` 로 검증/테스트
게이트(draft→valid→ready)를 표현하고, ready 만 요청-스코프 레지스트리로 위저드에서 소비된다.
"""

from __future__ import annotations

import json
from typing import Any

from harness_resolver import Component
from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.engine import Engine

from .db import user_component_versions, user_components
from .store import _HISTORY_CAP, VersionConflict, now_iso, safe_id


class ComponentStore:
    """스코프 격리 유저 컴포넌트 저장소. 목록은 요약만, 상세는 data(Component JSON) + 버전 히스토리."""

    _SUMMARY = ("id", "scope", "owner_id", "type", "name", "description", "status", "version", "updated_at")

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_scopes(
        self,
        scope_keys: list[str],
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if not scope_keys:
            return []
        cols = [user_components.c[k] for k in self._SUMMARY]
        stmt = select(*cols).where(user_components.c.scope.in_(scope_keys))
        if status:
            stmt = stmt.where(user_components.c.status == status)
        stmt = stmt.order_by(user_components.c.updated_at.desc())
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]

    def get(self, scope_key: str, cid: str) -> dict[str, Any] | None:
        sid = safe_id(cid)
        with self.engine.connect() as conn:
            row = conn.execute(
                select(user_components).where(
                    and_(user_components.c.scope == scope_key, user_components.c.id == sid)
                )
            ).mappings().first()
            if row is None:
                return None
            hist = conn.execute(
                select(user_component_versions.c.version, user_component_versions.c.updated_at)
                .where(and_(user_component_versions.c.scope == scope_key, user_component_versions.c.id == sid))
                .order_by(user_component_versions.c.version.desc())
            ).mappings().all()
        doc = dict(row)
        doc["history"] = [dict(h) for h in hist]
        return doc

    def put(
        self,
        scope_key: str,
        cid: str,
        owner_id: str,
        name: str,
        description: str,
        data_json: str,
        *,
        type_: str = "context",
        status: str = "draft",
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """저장(upsert). expected_version 을 주면 낙관적 잠금 — 현재와 다르면 VersionConflict."""
        sid = safe_id(cid)
        ts = now_iso()
        nm = name or sid
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(user_components.c.version, user_components.c.data, user_components.c.updated_at).where(
                    and_(user_components.c.scope == scope_key, user_components.c.id == sid)
                )
            ).mappings().first()
            if expected_version is not None:
                current = int(existing["version"]) if existing is not None else 0
                if current != expected_version:
                    raise VersionConflict(current)
            if existing is None:
                version = 1
                conn.execute(
                    insert(user_components).values(
                        scope=scope_key, id=sid, owner_id=owner_id, type=type_, name=nm,
                        description=description, data=data_json, status=status, version=1, updated_at=ts,
                    )
                )
            else:
                version = int(existing["version"]) + 1
                conn.execute(
                    insert(user_component_versions).values(
                        scope=scope_key, id=sid, version=existing["version"],
                        data=existing["data"], updated_at=existing["updated_at"],
                    )
                )
                kept = conn.execute(
                    select(user_component_versions.c.version)
                    .where(and_(user_component_versions.c.scope == scope_key, user_component_versions.c.id == sid))
                    .order_by(user_component_versions.c.version.desc())
                    .limit(_HISTORY_CAP)
                ).scalars().all()
                if kept:
                    conn.execute(
                        delete(user_component_versions).where(
                            and_(
                                user_component_versions.c.scope == scope_key,
                                user_component_versions.c.id == sid,
                                user_component_versions.c.version < min(kept),
                            )
                        )
                    )
                conn.execute(
                    update(user_components)
                    .where(and_(user_components.c.scope == scope_key, user_components.c.id == sid))
                    .values(
                        owner_id=owner_id, type=type_, name=nm, description=description,
                        data=data_json, status=status, version=version, updated_at=ts,
                    )
                )
        return {
            "id": sid, "scope": scope_key, "owner_id": owner_id, "type": type_, "name": nm,
            "description": description, "data": data_json, "status": status,
            "version": version, "updated_at": ts,
        }

    def set_status(self, scope_key: str, cid: str, status: str) -> dict[str, Any] | None:
        """상태만 갱신(검증/테스트 결과 반영). 반환: 갱신된 요약 or None(없음)."""
        sid = safe_id(cid)
        ts = now_iso()
        with self.engine.begin() as conn:
            res = conn.execute(
                update(user_components)
                .where(and_(user_components.c.scope == scope_key, user_components.c.id == sid))
                .values(status=status, updated_at=ts)
            )
            if not (res.rowcount and res.rowcount > 0):
                return None
        return self.get(scope_key, sid)

    def delete(self, scope_key: str, cid: str) -> bool:
        sid = safe_id(cid)
        with self.engine.begin() as conn:
            res = conn.execute(
                delete(user_components).where(
                    and_(user_components.c.scope == scope_key, user_components.c.id == sid)
                )
            )
            conn.execute(
                delete(user_component_versions).where(
                    and_(user_component_versions.c.scope == scope_key, user_component_versions.c.id == sid)
                )
            )
            return bool(res.rowcount and res.rowcount > 0)

    def ready_components(self, scope_keys: list[str]) -> list[Component]:
        """가시 스코프의 ready 컴포넌트들을 Component 로 역직렬화 — 요청-스코프 레지스트리 소스용."""
        if not scope_keys:
            return []
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(user_components.c.data).where(
                    and_(user_components.c.scope.in_(scope_keys), user_components.c.status == "ready")
                )
            ).all()
        out: list[Component] = []
        for (data,) in rows:
            try:
                out.append(Component.model_validate_json(data))
            except Exception:  # noqa: BLE001 — 손상 행은 건너뛴다(서빙 견고성)
                continue
        return out

    def summary(self, doc: dict[str, Any]) -> dict[str, Any]:
        return {k: doc.get(k) for k in self._SUMMARY}


class UserComponentSource:
    """유저 컴포넌트를 `LiveSource` 로 노출 — resolve/generate 요청-스코프 레지스트리에 편입.

    특정 유저의 가시 스코프(personal + 팀)의 **ready** 컴포넌트만 준다. 전역 app.state.registry
    에는 절대 넣지 않는다(전원 누출). 요청마다 그 유저 것만 담아 FederatedRegistry 로 감싼다.
    """

    origin = "user"

    def __init__(self, store: ComponentStore, scope_keys: set[str] | list[str]) -> None:
        self._store = store
        self._scopes = list(scope_keys)

    def components(self) -> list[Component]:
        return self._store.ready_components(self._scopes)


async def component_event_stream(
    store: ComponentStore, broadcaster: Any, visible_scopes: set[str]
) -> Any:
    """컴포넌트 전용 SSE — 연결 시 가시 스코프 목록, 이후 `kind==component` 이벤트만 흘린다.

    하네스와 브로드캐스터를 공유하므로 `kind` 로 채널을 구분한다(하네스 스트림은 kind==component 를 스킵).
    """
    q = broadcaster.subscribe()
    try:
        snapshot = store.list_scopes(sorted(visible_scopes))
        yield {"event": "ready", "data": json.dumps({"components": snapshot}, ensure_ascii=False, default=str)}
        while True:
            event = await q.get()
            if event.get("kind") != "component":
                continue
            if event.get("scope") not in visible_scopes:
                continue
            yield {"event": event["type"], "data": json.dumps(event, ensure_ascii=False, default=str)}
    finally:
        broadcaster.unsubscribe(q)
