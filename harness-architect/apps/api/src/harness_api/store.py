"""공유 하네스 저장소(스코프 격리) + SSE 브로드캐스터.

하네스는 **스코프**로 격리된다: `personal:<user_id>` 또는 `team:<team_id>`. 스코프마다 별도
디렉터리라 남의 스코프는 구조적으로 못 읽는다. 변경(upsert/delete)은 스코프 태그를 달아
브로드캐스트하고, SSE 구독자는 자기 가시 스코프 이벤트만 받는다. 단일 uvicorn 프로세스라
인메모리 pub/sub 로 충분(스케일아웃 시 Redis 등으로 교체 — 경계 유지).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def safe_id(raw: str) -> str:
    """사용자 입력 id 를 파일명 안전한 슬러그로. 경로 탈출 방지."""
    slug = _SLUG_RE.sub("-", raw.strip().lower().replace(" ", "-")).strip("-.")
    return slug or "harness"


def resolve_store_dir() -> Path:
    env = os.environ.get("HARNESS_STORE_DIR")
    base = Path(env).expanduser() if env else Path.home() / ".harness" / "harnesses"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _scope_dir_name(scope_key: str) -> str:
    """스코프 키(`personal:uid`/`team:tid`)를 디렉터리 이름으로. uid/tid 는 이미 safe_id."""
    return scope_key.replace(":", "__")


_HISTORY_CAP = 20  # 하네스당 보관할 이전 버전 수(최근 N)


class HarnessStore:
    """스코프별 디렉터리에 하네스당 JSON 한 파일. 목록은 요약만, 상세는 yaml + 버전 히스토리."""

    _SUMMARY = ("id", "scope", "owner_id", "name", "description", "version", "updated_at")

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def _scope_path(self, scope_key: str) -> Path:
        return self.dir / _scope_dir_name(scope_key)

    def _path(self, scope_key: str, hid: str) -> Path:
        return self._scope_path(scope_key) / f"{safe_id(hid)}.json"

    def list_scopes(self, scope_keys: list[str]) -> list[dict[str, Any]]:
        """주어진 스코프들에서 볼 수 있는 하네스 요약(최신순)."""
        items: list[dict[str, Any]] = []
        for sk in scope_keys:
            d = self._scope_path(sk)
            if not d.is_dir():
                continue
            for p in d.glob("*.json"):
                try:
                    doc = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                items.append({k: doc.get(k) for k in self._SUMMARY})
        items.sort(key=lambda d: d.get("updated_at") or "", reverse=True)
        return items

    def get(self, scope_key: str, hid: str) -> dict[str, Any] | None:
        p = self._path(scope_key, hid)
        if not p.exists():
            return None
        return cast(dict[str, Any], json.loads(p.read_text(encoding="utf-8")))

    def put(
        self, scope_key: str, hid: str, owner_id: str, name: str, description: str, yaml_text: str
    ) -> dict[str, Any]:
        sid = safe_id(hid)
        existing = self.get(scope_key, sid)
        version = 1
        history: list[dict[str, Any]] = []
        if existing is not None:
            version = int(existing.get("version", 1)) + 1
            prev = {
                "version": existing.get("version", 1),
                "updated_at": existing.get("updated_at"),
                "yaml": existing.get("yaml", ""),
            }
            history = [prev, *existing.get("history", [])][:_HISTORY_CAP]
        doc = {
            "id": sid,
            "scope": scope_key,
            "owner_id": owner_id,
            "name": name or sid,
            "description": description,
            "yaml": yaml_text,
            "version": version,
            "updated_at": now_iso(),
            "history": history,
        }
        path = self._path(scope_key, sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return doc

    def versions(self, scope_key: str, hid: str) -> list[dict[str, Any]] | None:
        """현재 + 이전 버전들(최신순) — 각 {version, updated_at, yaml}. 없으면 None."""
        doc = self.get(scope_key, hid)
        if doc is None:
            return None
        current = {"version": doc.get("version", 1), "updated_at": doc.get("updated_at"), "yaml": doc.get("yaml", "")}
        history = doc.get("history", [])
        return [current, *history]

    def delete(self, scope_key: str, hid: str) -> bool:
        p = self._path(scope_key, hid)
        if p.exists():
            p.unlink()
            return True
        return False

    def summary(self, doc: dict[str, Any]) -> dict[str, Any]:
        return {k: doc.get(k) for k in self._SUMMARY}


class Broadcaster:
    """인메모리 SSE pub/sub — 구독자별 asyncio.Queue 로 이벤트를 흘린다(스코프 필터는 구독 측)."""

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


async def event_stream(
    store: HarnessStore, broadcaster: Broadcaster, visible_scopes: set[str]
) -> Any:
    """SSE 제너레이터 — 연결 시 가시 스코프의 현재 목록(ready), 이후 가시 스코프 이벤트만 흘린다.

    (sync TestClient 로 SSE 스트림을 연 채 다른 요청을 하면 교착하므로 제너레이터를 직접 테스트.)
    """
    q = broadcaster.subscribe()
    try:
        snapshot = store.list_scopes(sorted(visible_scopes))
        yield {"event": "ready", "data": json.dumps({"harnesses": snapshot}, ensure_ascii=False)}
        while True:
            event = await q.get()
            if event.get("scope") not in visible_scopes:
                continue  # 다른 사용자/팀 스코프 이벤트는 격리
            yield {"event": event["type"], "data": json.dumps(event, ensure_ascii=False)}
    finally:
        broadcaster.unsubscribe(q)
