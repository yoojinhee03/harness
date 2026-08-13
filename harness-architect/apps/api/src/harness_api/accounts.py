"""사용자·팀 계정 저장소(SQL) + Bearer 토큰 인증.

멀티테넌시 신원. 사용자는 OAuth(이메일)로 로그인, 자격증명은 api_tokens(sha256 해시)에 분리 저장한다:
웹 세션(kind=session)과 VSCode/기계용 PAT(kind=pat)가 한 사용자에 여러 개 — 발급·폐기가 서로 독립.
팀(자가서브)으로 하네스 공유. 가시성 스코프 = 내 personal + 내가 속한 팀들.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, insert, or_, select, update
from sqlalchemy.engine import Engine

from .db import api_tokens, team_members, teams, users
from .store import now_iso, safe_id


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _uuid() -> str:
    return secrets.token_hex(16)


class AccountStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ── 사용자(OAuth 신원) ──
    def upsert_oauth_user(
        self, provider: str, sub: str, email: str, name: str = "", avatar_url: str = ""
    ) -> dict[str, Any]:
        """공급자 계정으로 로그인 — (provider, sub) 로 찾고, 없으면 email 로, 그래도 없으면 생성."""
        display = name or (email.split("@")[0] if email else provider)
        with self.engine.begin() as conn:
            row = conn.execute(
                select(users.c.id).where(
                    and_(users.c.provider == provider, users.c.provider_sub == sub)
                )
            ).first()
            if row is None:
                # 다른 공급자로 같은 이메일이 이미 있으면 그 계정에 연결(계정 통합).
                erow = conn.execute(select(users.c.id).where(users.c.email == email)).first()
                if erow is None:
                    uid = _uuid()
                    conn.execute(
                        insert(users).values(
                            id=uid,
                            email=email,
                            name=display,
                            avatar_url=avatar_url,
                            provider=provider,
                            provider_sub=sub,
                            created_at=now_iso(),
                        )
                    )
                    return self._user_row(conn, uid)
                uid = erow[0]
            else:
                uid = row[0]
            # 최신 프로필로 갱신(이름·아바타·연결 공급자).
            conn.execute(
                update(users)
                .where(users.c.id == uid)
                .values(name=display, avatar_url=avatar_url, provider=provider, provider_sub=sub)
            )
            return self._user_row(conn, uid)

    def _user_row(self, conn: Any, uid: str) -> dict[str, Any]:
        row = conn.execute(
            select(users.c.id, users.c.email, users.c.name, users.c.avatar_url).where(users.c.id == uid)
        ).mappings().first()
        assert row is not None
        return dict(row)

    def get_user(self, uid: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(users.c.id, users.c.email, users.c.name, users.c.avatar_url).where(users.c.id == uid)
            ).mappings().first()
        return dict(row) if row else None

    def _resolve_uid(self, conn: Any, email_or_id: str) -> str | None:
        row = conn.execute(
            select(users.c.id).where(or_(users.c.id == email_or_id, users.c.email == email_or_id))
        ).first()
        return row[0] if row else None

    # ── 토큰(자격증명) ──
    def create_token(self, uid: str, kind: str, name: str = "", ttl_days: int | None = None) -> dict[str, Any]:
        """토큰 발급 — 원문은 이 반환에서만 노출(저장은 해시). kind: session|pat."""
        token = secrets.token_urlsafe(32)
        tid = _uuid()
        created = now_iso()
        expires = (datetime.now(UTC) + timedelta(days=ttl_days)).isoformat() if ttl_days else None
        with self.engine.begin() as conn:
            conn.execute(
                insert(api_tokens).values(
                    id=tid,
                    user_id=uid,
                    kind=kind,
                    name=name,
                    token_sha=_hash_token(token),
                    created_at=created,
                    last_used_at=None,
                    expires_at=expires,
                )
            )
        return {"id": tid, "token": token, "name": name, "kind": kind, "created_at": created, "expires_at": expires}

    def user_by_token(self, token: str) -> dict[str, Any] | None:
        """토큰으로 사용자 신원 — 만료 검사 + last_used 갱신(best-effort)."""
        if not token:
            return None
        sha = _hash_token(token)
        with self.engine.begin() as conn:
            row = conn.execute(
                select(api_tokens.c.user_id, api_tokens.c.expires_at).where(api_tokens.c.token_sha == sha)
            ).mappings().first()
            if row is None:
                return None
            if row["expires_at"] and row["expires_at"] < now_iso():
                conn.execute(delete(api_tokens).where(api_tokens.c.token_sha == sha))  # 만료 토큰 청소
                return None
            conn.execute(
                update(api_tokens).where(api_tokens.c.token_sha == sha).values(last_used_at=now_iso())
            )
            return self._user_row(conn, row["user_id"])

    def list_tokens(self, uid: str, kind: str = "pat") -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    api_tokens.c.id,
                    api_tokens.c.name,
                    api_tokens.c.created_at,
                    api_tokens.c.last_used_at,
                )
                .where(and_(api_tokens.c.user_id == uid, api_tokens.c.kind == kind))
                .order_by(api_tokens.c.created_at.desc())
            ).mappings().all()
        return [dict(r) for r in rows]

    def revoke_token(self, uid: str, tid: str) -> bool:
        with self.engine.begin() as conn:
            res = conn.execute(
                delete(api_tokens).where(and_(api_tokens.c.id == tid, api_tokens.c.user_id == uid))
            )
        return bool(res.rowcount)

    def revoke_by_token(self, token: str) -> bool:
        """원문 토큰으로 폐기(로그아웃 — 현재 세션 토큰 무효화)."""
        if not token:
            return False
        with self.engine.begin() as conn:
            res = conn.execute(delete(api_tokens).where(api_tokens.c.token_sha == _hash_token(token)))
        return bool(res.rowcount)

    # ── 팀 ──
    def create_team(self, name: str, owner_id: str) -> dict[str, Any]:
        base = safe_id(name)
        with self.engine.begin() as conn:
            tid, n = base, 2
            while conn.execute(select(teams.c.id).where(teams.c.id == tid)).first():
                tid, n = f"{base}-{n}", n + 1
            conn.execute(insert(teams).values(id=tid, name=name, owner_id=owner_id))
            conn.execute(insert(team_members).values(team_id=tid, user_id=owner_id, role="owner"))
        team = self.get_team(tid)
        assert team is not None
        return team

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
            # 멤버를 users 와 조인해 이메일·이름을 함께 돌려준다(uuid 대신 사람이 읽을 정보).
            mrows = conn.execute(
                select(
                    team_members.c.user_id,
                    team_members.c.role,
                    users.c.email,
                    users.c.name,
                )
                .select_from(team_members.join(users, users.c.id == team_members.c.user_id))
                .where(team_members.c.team_id == tid)
            ).mappings().all()
        members = [
            {"id": m["user_id"], "email": m["email"], "name": m["name"], "role": m["role"]} for m in mrows
        ]
        return {"id": row["id"], "name": row["name"], "owner_id": row["owner_id"], "members": members}

    def add_member(self, tid: str, actor_id: str, email_or_id: str, role: str = "editor") -> dict[str, Any]:
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
            new_uid = self._resolve_uid(conn, email_or_id)
            if new_uid is None:
                raise ValueError(f"사용자를 찾을 수 없음: {email_or_id}")
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
