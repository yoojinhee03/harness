"""공유 하네스 저장소(SQL, 스코프 격리) + SSE 브로드캐스터.

저장은 SQLAlchemy(SQLite 개발/Postgres 프로덕션) — 트랜잭션으로 동시성 안전. 하네스는 스코프
(`personal:<uid>` / `team:<tid>`)로 격리하고, put 마다 버전을 올리며 이전 버전을 harness_versions
에 보관(최근 N). 변경 이벤트는 스코프 태그를 달아 브로드캐스트, SSE 구독자는 가시 스코프만 받는다.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.engine import Engine

from .db import harness_versions, harnesses

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")
_HISTORY_CAP = 20  # 하네스당 보관할 이전 버전 수


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def safe_id(raw: str) -> str:
    """사용자 입력 id 를 안전한 슬러그로."""
    slug = _SLUG_RE.sub("-", raw.strip().lower().replace(" ", "-")).strip("-.")
    return slug or "harness"


def resolve_store_dir() -> Path:
    env = os.environ.get("HARNESS_STORE_DIR")
    base = Path(env).expanduser() if env else Path.home() / ".harness" / "harnesses"
    base.mkdir(parents=True, exist_ok=True)
    return base


class HarnessStore:
    """스코프 격리 하네스 저장소(SQL). 목록은 요약만, 상세는 yaml + 버전 히스토리."""

    _SUMMARY = ("id", "scope", "owner_id", "name", "description", "version", "updated_at")

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_scopes(self, scope_keys: list[str]) -> list[dict[str, Any]]:
        if not scope_keys:
            return []
        cols = [harnesses.c[k] for k in self._SUMMARY]
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(*cols).where(harnesses.c.scope.in_(scope_keys)).order_by(harnesses.c.updated_at.desc())
            ).mappings().all()
        return [dict(r) for r in rows]

    def get(self, scope_key: str, hid: str) -> dict[str, Any] | None:
        sid = safe_id(hid)
        with self.engine.connect() as conn:
            row = conn.execute(
                select(harnesses).where(and_(harnesses.c.scope == scope_key, harnesses.c.id == sid))
            ).mappings().first()
            if row is None:
                return None
            hist = conn.execute(
                select(harness_versions.c.version, harness_versions.c.updated_at, harness_versions.c.yaml)
                .where(and_(harness_versions.c.scope == scope_key, harness_versions.c.id == sid))
                .order_by(harness_versions.c.version.desc())
            ).mappings().all()
        doc = dict(row)
        doc["history"] = [dict(h) for h in hist]
        return doc

    def put(
        self, scope_key: str, hid: str, owner_id: str, name: str, description: str, yaml_text: str
    ) -> dict[str, Any]:
        sid = safe_id(hid)
        ts = now_iso()
        nm = name or sid
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(harnesses.c.version, harnesses.c.yaml, harnesses.c.updated_at).where(
                    and_(harnesses.c.scope == scope_key, harnesses.c.id == sid)
                )
            ).mappings().first()
            if existing is None:
                version = 1
                conn.execute(
                    insert(harnesses).values(
                        scope=scope_key, id=sid, owner_id=owner_id, name=nm,
                        description=description, yaml=yaml_text, version=1, updated_at=ts,
                    )
                )
            else:
                version = int(existing["version"]) + 1
                conn.execute(
                    insert(harness_versions).values(
                        scope=scope_key, id=sid, version=existing["version"],
                        yaml=existing["yaml"], updated_at=existing["updated_at"],
                    )
                )
                kept = conn.execute(
                    select(harness_versions.c.version)
                    .where(and_(harness_versions.c.scope == scope_key, harness_versions.c.id == sid))
                    .order_by(harness_versions.c.version.desc())
                    .limit(_HISTORY_CAP)
                ).scalars().all()
                if kept:
                    conn.execute(
                        delete(harness_versions).where(
                            and_(
                                harness_versions.c.scope == scope_key,
                                harness_versions.c.id == sid,
                                harness_versions.c.version < min(kept),
                            )
                        )
                    )
                conn.execute(
                    update(harnesses)
                    .where(and_(harnesses.c.scope == scope_key, harnesses.c.id == sid))
                    .values(
                        owner_id=owner_id, name=nm, description=description,
                        yaml=yaml_text, version=version, updated_at=ts,
                    )
                )
        return {
            "id": sid, "scope": scope_key, "owner_id": owner_id, "name": nm,
            "description": description, "yaml": yaml_text, "version": version, "updated_at": ts,
        }

    def delete(self, scope_key: str, hid: str) -> bool:
        sid = safe_id(hid)
        with self.engine.begin() as conn:
            res = conn.execute(
                delete(harnesses).where(and_(harnesses.c.scope == scope_key, harnesses.c.id == sid))
            )
            conn.execute(
                delete(harness_versions).where(
                    and_(harness_versions.c.scope == scope_key, harness_versions.c.id == sid)
                )
            )
            return bool(res.rowcount and res.rowcount > 0)

    def versions(self, scope_key: str, hid: str) -> list[dict[str, Any]] | None:
        doc = self.get(scope_key, hid)
        if doc is None:
            return None
        current = {"version": doc["version"], "updated_at": doc["updated_at"], "yaml": doc["yaml"]}
        return [current, *doc.get("history", [])]

    def summary(self, doc: dict[str, Any]) -> dict[str, Any]:
        return {k: doc.get(k) for k in self._SUMMARY}


class Broadcaster:
    """인메모리 SSE pub/sub — 단일 프로세스. 스케일아웃은 RedisBroadcaster(REDIS_URL)."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.discard(q)

    async def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subs):
            await q.put(event)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)


class SSEBroadcaster(Protocol):
    """브로드캐스터 인터페이스 — 인메모리(Broadcaster)/Redis(RedisBroadcaster) 스왑 가능."""

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]: ...
    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None: ...
    async def publish(self, event: dict[str, Any]) -> None: ...


class RedisBroadcaster:
    """Redis pub/sub 기반 — 여러 워커·레플리카 간 SSE 이벤트 전달(스케일아웃).

    publish 는 redis 채널로 보내고, 각 인스턴스의 백그라운드 리스너가 자기 로컬 큐로 팬아웃한다.
    그래서 워커 A 에서 발행해도 워커 B 의 구독자에게 도달한다(인메모리 브로드캐스터의 한계 극복).
    REDIS_URL 로 활성 · `redis` extra 필요(uv sync --extra redis).
    """

    CHANNEL = "harness:events"

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # 선택 의존성 — REDIS_URL 설정 시에만 필요

        self._redis = redis.from_url(url)
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()
        self._listener: asyncio.Task[None] | None = None

    def _ensure_listener(self) -> None:
        if self._listener is None or self._listener.done():
            self._listener = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self.CHANNEL)
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                event = json.loads(msg["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            for q in list(self._subs):
                await q.put(event)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subs.add(q)
        self._ensure_listener()
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.discard(q)

    async def publish(self, event: dict[str, Any]) -> None:
        await self._redis.publish(self.CHANNEL, json.dumps(event, ensure_ascii=False, default=str))


def make_broadcaster() -> SSEBroadcaster:
    """REDIS_URL 있으면 Redis(스케일아웃), 없으면 인메모리(단일 프로세스)."""
    url = os.environ.get("REDIS_URL")
    return RedisBroadcaster(url) if url else Broadcaster()


async def event_stream(
    store: HarnessStore, broadcaster: SSEBroadcaster, visible_scopes: set[str]
) -> Any:
    """SSE 제너레이터 — 연결 시 가시 스코프의 현재 목록(ready), 이후 가시 스코프 이벤트만 흘린다."""
    q = broadcaster.subscribe()
    try:
        snapshot = store.list_scopes(sorted(visible_scopes))
        yield {"event": "ready", "data": json.dumps({"harnesses": snapshot}, ensure_ascii=False, default=str)}
        while True:
            event = await q.get()
            if event.get("scope") not in visible_scopes:
                continue
            yield {"event": event["type"], "data": json.dumps(event, ensure_ascii=False, default=str)}
    finally:
        broadcaster.unsubscribe(q)
