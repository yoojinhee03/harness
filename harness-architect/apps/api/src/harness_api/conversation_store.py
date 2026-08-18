"""스튜디오 대화 저장소(SQL, 스코프 격리) — 채팅으로 카탈로그를 만드는 대화 스레드.

대화(`studio_conversations`)는 하네스/컴포넌트와 동일하게 스코프(`personal:<uid>` / `team:<tid>`)로
격리한다. 대화당 산출물 1개(`draft` = 현재 초안 Component JSON, `draft_type` = 추론 타입). 메시지
(`studio_messages`)는 턴 이력이고 `meta` 에 구조화 페이로드(intent·추천·초안 스냅샷·테스트)를 싣는다.
변경은 하네스/컴포넌트와 브로드캐스터를 공유하되 `kind=="conversation"` 으로 채널을 구분한다.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.engine import Engine

from .db import studio_conversations, studio_messages
from .store import now_iso


def new_conversation_id() -> str:
    """대화 id — 제목이 비어 시작하므로 랜덤 hex 로 유일성 보장(`c-<hex>`)."""
    return "c-" + secrets.token_hex(8)


class ConversationStore:
    """스코프 격리 스튜디오 대화 저장소. 목록은 요약만, 상세는 메시지 이력 + 현재 초안."""

    _SUMMARY = (
        "id", "scope", "owner_id", "title", "draft_type", "component_id",
        "status", "version", "created_at", "updated_at",
    )

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ── 대화 ──

    def create(self, scope_key: str, owner_id: str, title: str = "") -> dict[str, Any]:
        cid = new_conversation_id()
        ts = now_iso()
        with self.engine.begin() as conn:
            conn.execute(
                insert(studio_conversations).values(
                    scope=scope_key, id=cid, owner_id=owner_id, title=title, draft="", draft_type="",
                    component_id=None, status="active", version=0, created_at=ts, updated_at=ts,
                )
            )
        return {
            "id": cid, "scope": scope_key, "owner_id": owner_id, "title": title, "draft_type": "",
            "component_id": None, "status": "active", "version": 0, "created_at": ts, "updated_at": ts,
        }

    def list_scopes(
        self, scope_keys: list[str], limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        if not scope_keys:
            return []
        cols = [studio_conversations.c[k] for k in self._SUMMARY]
        stmt = (
            select(*cols)
            .where(studio_conversations.c.scope.in_(scope_keys))
            .order_by(studio_conversations.c.updated_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]

    def header(self, scope_key: str, cid: str) -> dict[str, Any] | None:
        """헤더만(메시지 제외) — 존재 확인·요약 브로드캐스트용."""
        with self.engine.connect() as conn:
            row = conn.execute(
                select(studio_conversations).where(
                    and_(studio_conversations.c.scope == scope_key, studio_conversations.c.id == cid)
                )
            ).mappings().first()
        return dict(row) if row else None

    def get(self, scope_key: str, cid: str) -> dict[str, Any] | None:
        """대화 상세 — 헤더 + 메시지 이력(오래된→최신) + 파싱된 현재 초안."""
        row = self.header(scope_key, cid)
        if row is None:
            return None
        with self.engine.connect() as conn:
            msgs = conn.execute(
                select(studio_messages)
                .where(
                    and_(studio_messages.c.scope == scope_key, studio_messages.c.conversation_id == cid)
                )
                .order_by(studio_messages.c.id.asc())
            ).mappings().all()
        doc = dict(row)
        doc["draft_component"] = _loads(row.get("draft"))
        doc["messages"] = [_message_doc(m) for m in msgs]
        return doc

    def add_message(
        self, scope_key: str, cid: str, role: str, content: str, meta: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """메시지 추가(+ 대화 updated_at 갱신). 반환: 프런트용 메시지 doc."""
        ts = now_iso()
        meta_json = json.dumps(meta, ensure_ascii=False, default=str) if meta else ""
        with self.engine.begin() as conn:
            res = conn.execute(
                insert(studio_messages).values(
                    scope=scope_key, conversation_id=cid, role=role,
                    content=content, meta=meta_json, created_at=ts,
                )
            )
            conn.execute(
                update(studio_conversations)
                .where(and_(studio_conversations.c.scope == scope_key, studio_conversations.c.id == cid))
                .values(updated_at=ts)
            )
        mid = res.inserted_primary_key[0] if res.inserted_primary_key else None
        return {
            "id": mid, "conversation_id": cid, "role": role,
            "content": content, "meta": meta or None, "created_at": ts,
        }

    def set_draft(self, scope_key: str, cid: str, draft_json: str, draft_type: str) -> int:
        """현재 초안 교체 + 리비전(version) +1. 반환: 새 version."""
        ts = now_iso()
        with self.engine.begin() as conn:
            cur = conn.execute(
                select(studio_conversations.c.version).where(
                    and_(studio_conversations.c.scope == scope_key, studio_conversations.c.id == cid)
                )
            ).scalar_one_or_none()
            version = (int(cur) if cur is not None else 0) + 1
            conn.execute(
                update(studio_conversations)
                .where(and_(studio_conversations.c.scope == scope_key, studio_conversations.c.id == cid))
                .values(draft=draft_json, draft_type=draft_type, version=version, updated_at=ts)
            )
        return version

    def set_title(self, scope_key: str, cid: str, title: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(studio_conversations)
                .where(and_(studio_conversations.c.scope == scope_key, studio_conversations.c.id == cid))
                .values(title=title[:256], updated_at=now_iso())
            )

    def set_component(self, scope_key: str, cid: str, component_id: str) -> None:
        """commit 후 저장된 컴포넌트 링크 + status=committed."""
        with self.engine.begin() as conn:
            conn.execute(
                update(studio_conversations)
                .where(and_(studio_conversations.c.scope == scope_key, studio_conversations.c.id == cid))
                .values(component_id=component_id, status="committed", updated_at=now_iso())
            )

    def delete(self, scope_key: str, cid: str) -> bool:
        with self.engine.begin() as conn:
            res = conn.execute(
                delete(studio_conversations).where(
                    and_(studio_conversations.c.scope == scope_key, studio_conversations.c.id == cid)
                )
            )
            conn.execute(
                delete(studio_messages).where(
                    and_(studio_messages.c.scope == scope_key, studio_messages.c.conversation_id == cid)
                )
            )
            return bool(res.rowcount and res.rowcount > 0)

    def summary(self, doc: dict[str, Any]) -> dict[str, Any]:
        return {k: doc.get(k) for k in self._SUMMARY}


def _loads(raw: Any) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _message_doc(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "meta": _loads(row["meta"]),
        "created_at": row["created_at"],
    }


async def conversation_event_stream(
    store: ConversationStore, broadcaster: Any, visible_scopes: set[str]
) -> Any:
    """대화 목록 전용 SSE — 연결 시 가시 스코프 목록, 이후 `kind==conversation` 이벤트만 흘린다.

    하네스/컴포넌트와 브로드캐스터를 공유하므로 `kind` 로 채널을 구분한다(다른 스트림은 이 이벤트를 스킵).
    """
    q = broadcaster.subscribe()
    try:
        snapshot = store.list_scopes(sorted(visible_scopes))
        yield {
            "event": "ready",
            "data": json.dumps({"conversations": snapshot}, ensure_ascii=False, default=str),
        }
        while True:
            event = await q.get()
            if event.get("kind") != "conversation":
                continue
            if event.get("scope") not in visible_scopes:
                continue
            yield {"event": event["type"], "data": json.dumps(event, ensure_ascii=False, default=str)}
    finally:
        broadcaster.unsubscribe(q)
