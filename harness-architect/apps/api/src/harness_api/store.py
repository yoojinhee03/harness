"""공유 하네스 저장소 + SSE 브로드캐스터.

웹과 VSCode 확장이 **같은 백엔드**를 허브로 harness.yaml 을 저장/동기화한다. 저장소는
디렉터리에 하네스당 JSON 한 파일(영속). 변경(upsert/delete)은 브로드캐스터로 SSE 구독자에게
실시간 푸시한다. 단일 uvicorn 프로세스라 인메모리 pub/sub 로 충분하다.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_id(raw: str) -> str:
    """사용자 입력 id 를 파일명 안전한 슬러그로. 경로 탈출 방지."""
    slug = _SLUG_RE.sub("-", raw.strip().lower().replace(" ", "-")).strip("-.")
    return slug or "harness"


def resolve_store_dir() -> Path:
    env = os.environ.get("HARNESS_STORE_DIR")
    base = Path(env).expanduser() if env else Path.home() / ".harness" / "harnesses"
    base.mkdir(parents=True, exist_ok=True)
    return base


class HarnessStore:
    """하네스당 JSON 파일 저장소. 목록은 요약만, 상세는 yaml 포함."""

    _SUMMARY = ("id", "name", "description", "updated_at")

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, hid: str) -> Path:
        return self.dir / f"{safe_id(hid)}.json"

    def list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for p in self.dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            items.append({k: d.get(k) for k in self._SUMMARY})
        items.sort(key=lambda d: d.get("updated_at") or "", reverse=True)
        return items

    def get(self, hid: str) -> dict[str, Any] | None:
        p = self._path(hid)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def put(self, hid: str, name: str, description: str, yaml_text: str) -> dict[str, Any]:
        sid = safe_id(hid)
        doc = {
            "id": sid,
            "name": name or sid,
            "description": description,
            "yaml": yaml_text,
            "updated_at": now_iso(),
        }
        self._path(sid).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return doc

    def delete(self, hid: str) -> bool:
        p = self._path(hid)
        if p.exists():
            p.unlink()
            return True
        return False

    def summary(self, doc: dict[str, Any]) -> dict[str, Any]:
        return {k: doc.get(k) for k in self._SUMMARY}


class Broadcaster:
    """인메모리 SSE pub/sub — 구독자별 asyncio.Queue 로 이벤트를 흘린다."""

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


async def event_stream(store: HarnessStore, broadcaster: Broadcaster) -> Any:
    """SSE 이벤트 제너레이터 — 연결 시 현재 목록(ready), 이후 upsert/delete 를 흘린다.

    엔드포인트와 분리해 단위 테스트 가능하게 둔다(sync TestClient 로는 SSE 스트림을 열어 둔 채
    다른 요청을 하면 교착하므로).
    """
    q = broadcaster.subscribe()
    try:
        yield {"event": "ready", "data": json.dumps({"harnesses": store.list()}, ensure_ascii=False)}
        while True:
            event = await q.get()
            yield {"event": event["type"], "data": json.dumps(event, ensure_ascii=False)}
    finally:
        broadcaster.unsubscribe(q)
