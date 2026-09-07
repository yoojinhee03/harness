"""팀 역할 관리 — 권한 상승 차단 + owner 최소 1명 불변식.

**실제로 있던 구멍**: `add_member` 가 기존 멤버를 만나면 무조건 역할을 UPDATE 했고 actor 조건이
owner/editor 였다. 그래서 **editor 가 자기 이메일로 `role=owner` 를 보내 스스로 승격**할 수 있었고,
정책이 owner 전용이 된 뒤로는 그게 곧 거버넌스 우회였다(403 → 승격 → 200).

**owner 최소 1명**: owner 가 0 이 되면 멤버 관리도 정책 변경도 아무도 못 하는 통치 불가 상태가
된다. 강등·제거·자진 탈퇴 모두 이 불변식을 지켜야 한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("HARNESS_DEV_AUTH", "on")
    monkeypatch.setenv("HARNESS_SECRET_KEY", "test-secret")
    from harness_api.main import app

    with TestClient(app) as c:
        def login(email: str) -> dict[str, str]:
            tok = c.post("/auth/dev-login", json={"email": email}).json()["token"]
            return {"Authorization": f"Bearer {tok}"}

        owner = login("owner@x.com")
        editor = login("editor@x.com")
        viewer = login("viewer@x.com")
        tid = c.post("/teams", json={"name": "T"}, headers=owner).json()["id"]
        c.post(f"/teams/{tid}/members", json={"email": "editor@x.com", "role": "editor"}, headers=owner)
        c.post(f"/teams/{tid}/members", json={"email": "viewer@x.com", "role": "viewer"}, headers=owner)
        yield {"c": c, "tid": tid, "owner": owner, "editor": editor, "viewer": viewer, "login": login}


def uid_of(team: dict, email: str) -> str:
    return next(m["id"] for m in team["members"] if m["email"] == email)


def team_of(env) -> dict:
    return env["c"].get("/me", headers=env["owner"]).json()["teams"][0]


def roles(team: dict) -> dict[str, str]:
    return {m["email"]: m["role"] for m in team["members"]}


# ── 권한 상승 차단 ──


def test_editor_cannot_self_promote_via_invite(env):
    """실제로 있던 구멍 — 초대 엔드포인트로 자기 역할을 바꿔 owner 가 되던 경로."""
    r = env["c"].post(
        f"/teams/{env['tid']}/members", json={"email": "editor@x.com", "role": "owner"}, headers=env["editor"]
    )
    assert r.status_code == 403
    assert roles(team_of(env))["editor@x.com"] == "editor"


def test_editor_cannot_grant_owner_to_others(env):
    """editor 가 owner 를 만들 수 있으면 자기 대리인을 세워 우회할 수 있다."""
    env["login"]("new@x.com")
    r = env["c"].post(
        f"/teams/{env['tid']}/members", json={"email": "new@x.com", "role": "owner"}, headers=env["editor"]
    )
    assert r.status_code == 403


def test_editor_cannot_change_existing_member_role(env):
    """기존 멤버의 역할 변경은 권한 조작이므로 owner 만."""
    r = env["c"].post(
        f"/teams/{env['tid']}/members", json={"email": "viewer@x.com", "role": "editor"}, headers=env["editor"]
    )
    assert r.status_code == 403


def test_editor_can_still_invite_non_owner(env):
    """초대 자체는 막지 않는다 — 막았으면 협업이 안 된다."""
    env["login"]("fresh@x.com")
    r = env["c"].post(
        f"/teams/{env['tid']}/members", json={"email": "fresh@x.com", "role": "editor"}, headers=env["editor"]
    )
    assert r.status_code == 200
    assert roles(r.json())["fresh@x.com"] == "editor"


def test_escalation_does_not_reach_policy(env):
    """구멍의 실제 영향 — 승격이 막히면 정책도 계속 막혀 있어야 한다."""
    scope = f"team:{env['tid']}"
    body = {"require": {"capabilities": ["lifecycle.guardrail"]}}
    assert env["c"].put("/policies", json=body, params={"scope": scope}, headers=env["editor"]).status_code == 403
    env["c"].post(
        f"/teams/{env['tid']}/members",
        json={"email": "editor@x.com", "role": "owner"},
        headers=env["editor"],
    )
    assert env["c"].put("/policies", json=body, params={"scope": scope}, headers=env["editor"]).status_code == 403


# ── 역할 변경 엔드포인트 ──


def test_owner_can_change_role(env):
    vid = uid_of(team_of(env), "viewer@x.com")
    r = env["c"].put(f"/teams/{env['tid']}/members/{vid}", json={"role": "editor"}, headers=env["owner"])
    assert r.status_code == 200
    assert roles(r.json())["viewer@x.com"] == "editor"


def test_non_owner_cannot_change_role(env):
    vid = uid_of(team_of(env), "viewer@x.com")
    r = env["c"].put(f"/teams/{env['tid']}/members/{vid}", json={"role": "owner"}, headers=env["editor"])
    assert r.status_code == 403


def test_invalid_role_rejected(env):
    vid = uid_of(team_of(env), "viewer@x.com")
    r = env["c"].put(f"/teams/{env['tid']}/members/{vid}", json={"role": "admin"}, headers=env["owner"])
    assert r.status_code == 422


def test_role_change_on_non_member_404(env):
    r = env["c"].put(f"/teams/{env['tid']}/members/nobody", json={"role": "editor"}, headers=env["owner"])
    assert r.status_code == 404


# ── owner 최소 1명 불변식 ──


def test_last_owner_cannot_be_demoted(env):
    oid = uid_of(team_of(env), "owner@x.com")
    r = env["c"].put(f"/teams/{env['tid']}/members/{oid}", json={"role": "editor"}, headers=env["owner"])
    assert r.status_code == 400
    assert "마지막 owner" in r.json()["detail"]
    assert roles(team_of(env))["owner@x.com"] == "owner"


def test_owner_can_be_demoted_when_another_owner_exists(env):
    """불변식은 "최소 1명"이지 "강등 금지"가 아니다 — 승계가 가능해야 한다."""
    eid = uid_of(team_of(env), "editor@x.com")
    env["c"].put(f"/teams/{env['tid']}/members/{eid}", json={"role": "owner"}, headers=env["owner"])
    oid = uid_of(team_of(env), "owner@x.com")
    r = env["c"].put(f"/teams/{env['tid']}/members/{oid}", json={"role": "editor"}, headers=env["owner"])
    assert r.status_code == 200
    assert roles(r.json()) == {"owner@x.com": "editor", "editor@x.com": "owner", "viewer@x.com": "viewer"}


def test_last_owner_cannot_leave(env):
    """자진 탈퇴도 막는다 — 남은 멤버가 통치 불가 상태가 된다."""
    oid = uid_of(team_of(env), "owner@x.com")
    r = env["c"].delete(f"/teams/{env['tid']}/members/{oid}", headers=env["owner"])
    assert r.status_code == 400


# ── 멤버 제거 ──


def test_owner_can_remove_member(env):
    vid = uid_of(team_of(env), "viewer@x.com")
    r = env["c"].delete(f"/teams/{env['tid']}/members/{vid}", headers=env["owner"])
    assert r.status_code == 200
    assert "viewer@x.com" not in roles(r.json())


def test_member_can_leave_by_self(env):
    """본인 탈퇴는 owner 아니어도 가능해야 한다 — 아니면 팀에 갇힌다."""
    team = team_of(env)
    vid = uid_of(team, "viewer@x.com")
    r = env["c"].delete(f"/teams/{env['tid']}/members/{vid}", headers=env["viewer"])
    assert r.status_code == 200
    assert "viewer@x.com" not in roles(r.json())


def test_non_owner_cannot_remove_others(env):
    vid = uid_of(team_of(env), "viewer@x.com")
    r = env["c"].delete(f"/teams/{env['tid']}/members/{vid}", headers=env["editor"])
    assert r.status_code == 403


def test_removed_member_loses_scope_access(env):
    """제거가 실제로 격리에 반영돼야 한다 — 역할 표시만 바뀌면 의미가 없다."""
    scope = f"team:{env['tid']}"
    assert env["c"].get("/harnesses", headers=env["viewer"]).status_code == 200
    vid = uid_of(team_of(env), "viewer@x.com")
    env["c"].delete(f"/teams/{env['tid']}/members/{vid}", headers=env["owner"])
    r = env["c"].get("/policies", params={"scope": scope}, headers=env["viewer"])
    assert r.status_code == 403
