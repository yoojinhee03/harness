"""사용자·팀 계정 저장소 + Bearer 토큰 인증.

멀티테넌시의 신뢰 근거. 사용자당 API 토큰(해시 저장)으로 신원을 확인하고, 팀(자가서브)으로
하네스를 공유한다. 가시성 스코프: 내 personal + 내가 속한 팀들. 파일 기반(v1) — users.json /
teams.json 을 통째로 rewrite(단일 프로세스 락). 규모가 커지면 DB 로 교체(경계 유지).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from pathlib import Path
from typing import Any

from .store import now_iso, safe_id


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountStore:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self._users_path = self.dir / "users.json"
        self._teams_path = self.dir / "teams.json"
        self._lock = threading.Lock()

    # ── 로우레벨 파일 IO ──
    def _read(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return data
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 사용자 ──
    def register(self, handle: str) -> dict[str, Any]:
        """새 사용자 + 토큰 발급. 토큰 원문은 이 반환에서만 노출(해시만 저장)."""
        with self._lock:
            users = self._read(self._users_path)
            uid = safe_id(handle)
            if uid in users:
                raise ValueError(f"이미 존재하는 handle: {uid}")
            token = secrets.token_urlsafe(32)
            users[uid] = {
                "id": uid,
                "handle": handle,
                "token_sha": _hash_token(token),
                "created_at": now_iso(),
            }
            self._write(self._users_path, users)
            return {"id": uid, "handle": handle, "token": token}

    def user_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        sha = _hash_token(token)
        for u in self._read(self._users_path).values():
            if hmac.compare_digest(u.get("token_sha", ""), sha):
                return {"id": u["id"], "handle": u["handle"]}
        return None

    def get_user(self, uid: str) -> dict[str, Any] | None:
        u = self._read(self._users_path).get(uid)
        return {"id": u["id"], "handle": u["handle"]} if u else None

    def _resolve_uid(self, handle_or_id: str) -> str | None:
        users = self._read(self._users_path)
        if handle_or_id in users:
            return handle_or_id
        sid = safe_id(handle_or_id)
        return sid if sid in users else None

    # ── 팀 (자가서브) ──
    def create_team(self, name: str, owner_id: str) -> dict[str, Any]:
        with self._lock:
            teams = self._read(self._teams_path)
            tid = safe_id(name)
            base, n = tid, 2
            while tid in teams:  # 이름 충돌 시 접미사
                tid = f"{base}-{n}"
                n += 1
            team = {"id": tid, "name": name, "owner_id": owner_id, "members": [owner_id]}
            teams[tid] = team
            self._write(self._teams_path, teams)
            return team

    def get_team(self, tid: str) -> dict[str, Any] | None:
        return self._read(self._teams_path).get(tid)

    def add_member(self, tid: str, actor_id: str, handle_or_id: str) -> dict[str, Any]:
        with self._lock:
            teams = self._read(self._teams_path)
            team: dict[str, Any] | None = teams.get(tid)
            if team is None:
                raise KeyError(f"팀 없음: {tid}")
            if actor_id not in team["members"]:
                raise PermissionError("팀 멤버만 초대할 수 있습니다")
            new_uid = self._resolve_uid(handle_or_id)
            if new_uid is None:
                raise ValueError(f"사용자를 찾을 수 없음: {handle_or_id}")
            if new_uid not in team["members"]:
                team["members"].append(new_uid)
                self._write(self._teams_path, teams)
            return team

    def teams_of(self, uid: str) -> list[dict[str, Any]]:
        return [t for t in self._read(self._teams_path).values() if uid in t.get("members", [])]

    def is_member(self, tid: str, uid: str) -> bool:
        team = self.get_team(tid)
        return bool(team and uid in team.get("members", []))

    # ── 가시성 스코프 ──
    def visible_scope_keys(self, uid: str) -> set[str]:
        """이 사용자가 볼 수 있는 스코프 키 집합 — 내 personal + 속한 팀들."""
        keys = {f"personal:{uid}"}
        keys |= {f"team:{t['id']}" for t in self.teams_of(uid)}
        return keys
