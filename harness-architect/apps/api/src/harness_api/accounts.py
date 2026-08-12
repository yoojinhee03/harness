"""사용자·팀 계정 저장소(SQL) + Bearer 토큰 인증.

멀티테넌시 신원. 사용자당 API 토큰(sha256 해시 저장), 팀(자가서브)으로 하네스 공유. 가시성
스코프 = 내 personal + 내가 속한 팀들. SQLAlchemy(SQLite/Postgres) — 트랜잭션으로 동시성 안전.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.engine import Engine

from .db import team_members, teams, users
from .store import now_iso, safe_id


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ── 사용자 ──
    def register(self, handle: str) -> dict[str, Any]:
        uid = safe_id(handle)
        token = secrets.token_urlsafe(32)
        with self.engine.begin() as conn:
            if conn.execute(select(users.c.id).where(users.c.id == uid)).first():
                raise ValueError(f"이미 존재하는 handle: {uid}")
            conn.execute(
                insert(users).values(id=uid, handle=handle, token_sha=_hash_token(token), created_at=now_iso())
            )
        return {"id": uid, "handle": handle, "token": token}

    def rotate_token(self, uid: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.engine.begin() as conn:
            res = conn.execute(update(users).where(users.c.id == uid).values(token_sha=_hash_token(token)))
            if not res.rowcount:
                raise KeyError(f"사용자 없음: {uid}")
        return token

    def user_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self.engine.connect() as conn:
            row = conn.execute(
                select(users.c.id, users.c.handle).where(users.c.token_sha == _hash_token(token))
            ).mappings().first()
        return {"id": row["id"], "handle": row["handle"]} if row else None

    def get_user(self, uid: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(users.c.id, users.c.handle).where(users.c.id == uid)).mappings().first()
        return {"id": row["id"], "handle": row["handle"]} if row else None

    def _resolve_uid(self, conn: Any, handle_or_id: str) -> str | None:
        row = conn.execute(
            select(users.c.id).where(or_(users.c.id == handle_or_id, users.c.id == safe_id(handle_or_id)))
        ).first()
        return row[0] if row else None

    # ── 팀 ──
    def create_team(self, name: str, owner_id: str) -> dict[str, Any]:
        base = safe_id(name)
        with self.engine.begin() as conn:
            tid, n = base, 2
            while conn.execute(select(teams.c.id).where(teams.c.id == tid)).first():
                tid, n = f"{base}-{n}", n + 1
            conn.execute(insert(teams).values(id=tid, name=name, owner_id=owner_id))
            conn.execute(insert(team_members).values(team_id=tid, user_id=owner_id, role="owner"))
        return {"id": tid, "name": name, "owner_id": owner_id, "members": [owner_id]}

    def member_role(self, tid: str, uid: str) -> str | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(team_members.c.role).where(
                    and_(team_members.c.team_id == tid, team_members.c.user_id == uid)
                )
            ).first()
        return str(row[0]) if row else None

    def get_team(self, tid: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(teams).where(teams.c.id == tid)).mappings().first()
            if row is None:
                return None
            members = conn.execute(select(team_members.c.user_id).where(team_members.c.team_id == tid)).scalars().all()
        return {"id": row["id"], "name": row["name"], "owner_id": row["owner_id"], "members": list(members)}

    def add_member(self, tid: str, actor_id: str, handle_or_id: str, role: str = "editor") -> dict[str, Any]:
        role = role if role in ("owner", "editor", "viewer") else "editor"
        with self.engine.begin() as conn:
            if conn.execute(select(teams.c.id).where(teams.c.id == tid)).first() is None:
                raise KeyError(f"팀 없음: {tid}")
            actor = conn.execute(
                select(team_members.c.role).where(
                    and_(team_members.c.team_id == tid, team_members.c.user_id == actor_id)
                )
            ).first()
            if actor is None or actor[0] not in ("owner", "editor"):
                raise PermissionError("초대 권한이 없습니다(owner/editor 만)")
            new_uid = self._resolve_uid(conn, handle_or_id)
            if new_uid is None:
                raise ValueError(f"사용자를 찾을 수 없음: {handle_or_id}")
            already = conn.execute(
                select(team_members.c.user_id).where(
                    and_(team_members.c.team_id == tid, team_members.c.user_id == new_uid)
                )
            ).first()
            if already:
                conn.execute(
                    update(team_members)
                    .where(and_(team_members.c.team_id == tid, team_members.c.user_id == new_uid))
                    .values(role=role)
                )
            else:
                conn.execute(insert(team_members).values(team_id=tid, user_id=new_uid, role=role))
        team = self.get_team(tid)
        assert team is not None
        return team

    def teams_of(self, uid: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            tids = conn.execute(select(team_members.c.team_id).where(team_members.c.user_id == uid)).scalars().all()
        return [g for t in tids if (g := self.get_team(t)) is not None]

    def is_member(self, tid: str, uid: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(team_members.c.user_id).where(
                    and_(team_members.c.team_id == tid, team_members.c.user_id == uid)
                )
            ).first()
        return row is not None

    def visible_scope_keys(self, uid: str) -> set[str]:
        keys = {f"personal:{uid}"}
        keys |= {f"team:{t['id']}" for t in self.teams_of(uid)}
        return keys
