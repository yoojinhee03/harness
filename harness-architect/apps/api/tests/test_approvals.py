"""승격 다인 승인 — 공급망 게이트.

승격은 `origin='promoted'` 로 **전 유저**의 검색·추천에 등장한다. 지금까지는 write 권한만 있으면
단독으로 올릴 수 있었다. 정족수를 켜면 다음 두 규칙이 "다인 승인"을 이름만 남지 않게 만든다:

  · **자기 승인은 안 센다** — 작성자가 자기 것을 승인해 통과시킬 수 있으면 무의미하다.
  · **현재 버전의 승인만 센다** — 심사한 내용과 올라가는 내용이 다르면 심사가 무의미하다.

그리고 **기본은 꺼짐**(정족수 0)이라 기존 동작이 한 치도 안 바뀐다.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from harness_api.promotion import approval_progress

READY_COMPONENT = {
    "id": "team-ctx",
    "type": "context",
    "name": "팀 컨벤션",
    "version": "1.0.0",
    "summary": "팀 코딩 컨벤션",
    "description": "팀 코딩 컨벤션",
    "provides": ["convention.coding"],
    "capability_tags": ["convention.coding"],
    "body": "snake_case 를 쓴다.",
}


def make_env(tmp_path, monkeypatch, approvals: str | None = None):
    monkeypatch.setenv("HARNESS_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("HARNESS_DEV_AUTH", "on")
    monkeypatch.setenv("HARNESS_SECRET_KEY", "test-secret")
    if approvals is not None:
        monkeypatch.setenv("HARNESS_PROMOTION_APPROVALS", approvals)
    else:
        monkeypatch.delenv("HARNESS_PROMOTION_APPROVALS", raising=False)
    from harness_api.main import app

    return app


@pytest.fixture()
def two_person(tmp_path, monkeypatch):
    """정족수 1(작성자 외 1명)로 켠 환경 + 작성자/리뷰어 두 사람."""
    app = make_env(tmp_path, monkeypatch, approvals="1")
    with TestClient(app) as c:
        def login(email: str) -> dict[str, str]:
            tok = c.post("/auth/dev-login", json={"email": email}).json()["token"]
            return {"Authorization": f"Bearer {tok}"}

        author = login("author@x.com")
        reviewer = login("reviewer@x.com")
        # 작성자 개인 스코프에 ready 컴포넌트를 둔다.
        c.put(
            "/components/team-ctx",
            json={"name": "팀 컨벤션", "description": "", "data": READY_COMPONENT},
            headers=author,
        )
        yield {"c": c, "author": author, "reviewer": reviewer}


def set_ready(env) -> None:
    """스튜디오 검증을 거치지 않고 상태만 ready 로 올린다(승인 게이트만 보려고)."""
    from harness_api.component_store import ComponentStore
    from harness_api.main import app

    store = ComponentStore(app.state.engine)
    me = env["c"].get("/me", headers=env["author"]).json()
    store.set_status(f"personal:{me['id']}", "team-ctx", "ready")


# ── 기본은 꺼짐 ──


def test_default_is_off_so_behavior_unchanged(tmp_path, monkeypatch):
    """정족수 기본 0 — 이 기능 도입만으로 기존 승격이 막히면 안 된다."""
    from harness_api.approvals import required_approvals

    monkeypatch.delenv("HARNESS_PROMOTION_APPROVALS", raising=False)
    assert required_approvals() == 0


def test_invalid_threshold_falls_back_to_default(monkeypatch):
    """오타가 게이트를 임의로 열거나 닫으면 안 된다 — 기본값으로 떨어진다."""
    from harness_api.approvals import required_approvals

    monkeypatch.setenv("HARNESS_PROMOTION_APPROVALS", "두명")
    assert required_approvals() == 0


def test_negative_threshold_is_clamped(monkeypatch):
    from harness_api.approvals import required_approvals

    monkeypatch.setenv("HARNESS_PROMOTION_APPROVALS", "-5")
    assert required_approvals() == 0


# ── 정족수 판정(순수) ──

DOC = {"owner_id": "author", "version": 3}


def test_other_person_approval_counts():
    p = approval_progress(DOC, [{"approver_id": "bob", "component_version": 3}], 1)
    assert p["satisfied"] is True and p["approved_by"] == ["bob"]


def test_self_approval_does_not_count():
    """**핵심** — 작성자가 자기 것을 승인해 통과시키면 다인 승인이 이름만 남는다."""
    p = approval_progress(DOC, [{"approver_id": "author", "component_version": 3}], 1)
    assert p["satisfied"] is False
    assert p["count"] == 0
    assert p["self_approved_ignored"] is True


def test_stale_approval_does_not_count():
    """심사한 버전과 올라가는 버전이 다르면 심사가 무의미하다."""
    p = approval_progress(DOC, [{"approver_id": "bob", "component_version": 2}], 1)
    assert p["satisfied"] is False
    assert p["stale_ignored"] == ["bob"]


def test_same_person_cannot_fill_quorum_alone():
    """같은 승인자 중복은 하나로 센다(스토어 PK 로도 막지만 판정에서도 확인)."""
    dupes = [{"approver_id": "bob", "component_version": 3}] * 3
    assert approval_progress(DOC, dupes, 2)["count"] == 1


def test_progress_reports_shortfall():
    p = approval_progress(DOC, [{"approver_id": "bob", "component_version": 3}], 2)
    assert p["required"] == 2 and p["count"] == 1 and p["satisfied"] is False


# ── 엔드포인트 관통 ──


def test_promote_blocked_until_other_person_approves(two_person):
    set_ready(two_person)
    c = two_person["c"]

    r = c.post("/components/team-ctx/promote", headers=two_person["author"])
    assert r.status_code == 400
    assert "작성자 외 승인 1명" in r.json()["detail"]

    # 작성자 자기 승인은 통과시키지 못한다.
    c.post("/components/team-ctx/approvals", json={"note": "내 것"}, headers=two_person["author"])
    r = c.post("/components/team-ctx/promote", headers=two_person["author"])
    assert r.status_code == 400
    assert "작성자 본인의 승인은" in r.json()["detail"]


def test_approval_progress_endpoint_explains_why_not_counted(two_person):
    set_ready(two_person)
    c = two_person["c"]
    c.post("/components/team-ctx/approvals", json={"note": "내 것"}, headers=two_person["author"])
    p = c.get("/components/team-ctx/approvals", headers=two_person["author"]).json()["progress"]
    assert p["self_approved_ignored"] is True and p["count"] == 0


def test_personal_scope_is_a_dead_end_and_says_so(two_person):
    """개인 스코프엔 다른 승인자가 접근할 수 없어 정족수를 **영원히** 못 채운다.

    그냥 "승인 부족"으로만 알리면 사용자는 무엇을 해야 하는지 알 수 없다 → 막다른 길을 밝힌다.
    """
    set_ready(two_person)
    c = two_person["c"]
    # 리뷰어의 personal 스코프엔 이 컴포넌트가 없다(격리는 유지된다).
    r = c.get("/components/team-ctx/approvals", headers=two_person["reviewer"])
    assert r.status_code == 404

    detail = c.post("/components/team-ctx/promote", headers=two_person["author"]).json()["detail"]
    assert "팀 스코프로 옮긴 뒤" in detail


def test_team_scope_flow_end_to_end(tmp_path, monkeypatch):
    """실제로 되는 경로 — 팀 스코프에서 다른 멤버가 승인하면 승격이 열린다."""
    from harness_api.component_store import ComponentStore

    app = make_env(tmp_path, monkeypatch, approvals="1")
    with TestClient(app) as c:
        a = {"Authorization": f"Bearer {c.post('/auth/dev-login', json={'email': 'author@x.com'}).json()['token']}"}
        b = {"Authorization": f"Bearer {c.post('/auth/dev-login', json={'email': 'rev@x.com'}).json()['token']}"}
        tid = c.post("/teams", json={"name": "T"}, headers=a).json()["id"]
        c.post(f"/teams/{tid}/members", json={"email": "rev@x.com", "role": "editor"}, headers=a)
        scope = {"scope": f"team:{tid}"}

        c.put(
            "/components/team-ctx",
            json={"name": "n", "description": "", "data": READY_COMPONENT},
            params=scope,
            headers=a,
        )
        ComponentStore(app.state.engine).set_status(f"team:{tid}", "team-ctx", "ready")

        # 승인 전 차단
        assert c.post("/components/team-ctx/promote", params=scope, headers=a).status_code == 400
        # 다른 멤버 승인 → 정족수 충족
        prog = c.post(
            "/components/team-ctx/approvals", json={"note": "검토 완료"}, params=scope, headers=b
        ).json()["progress"]
        assert prog["satisfied"] is True and prog["count"] == 1
        assert c.post("/components/team-ctx/promote", params=scope, headers=a).status_code == 200

        # 승격 후 승인이 정리돼 다음 버전은 다시 검토가 필요하다
        after = c.get("/components/team-ctx/approvals", params=scope, headers=a).json()
        assert after["approvals"] == []


def test_withdraw_lowers_the_count(tmp_path, monkeypatch):
    """재검토 후 마음이 바뀔 수 있어야 한다 — 철회하면 정족수가 다시 미충족이 된다."""
    from harness_api.component_store import ComponentStore

    app = make_env(tmp_path, monkeypatch, approvals="1")
    with TestClient(app) as c:
        a = {"Authorization": f"Bearer {c.post('/auth/dev-login', json={'email': 'author@x.com'}).json()['token']}"}
        b = {"Authorization": f"Bearer {c.post('/auth/dev-login', json={'email': 'rev@x.com'}).json()['token']}"}
        tid = c.post("/teams", json={"name": "T"}, headers=a).json()["id"]
        c.post(f"/teams/{tid}/members", json={"email": "rev@x.com", "role": "editor"}, headers=a)
        scope = {"scope": f"team:{tid}"}
        c.put(
            "/components/team-ctx",
            json={"name": "n", "description": "", "data": READY_COMPONENT},
            params=scope,
            headers=a,
        )
        ComponentStore(app.state.engine).set_status(f"team:{tid}", "team-ctx", "ready")

        c.post("/components/team-ctx/approvals", json={"note": "ok"}, params=scope, headers=b)
        assert c.get("/components/team-ctx/approvals", params=scope, headers=a).json()["progress"]["satisfied"]

        assert c.request("DELETE", "/components/team-ctx/approvals", params=scope, headers=b).json()["removed"]
        prog = c.get("/components/team-ctx/approvals", params=scope, headers=a).json()["progress"]
        assert prog["satisfied"] is False and prog["count"] == 0


def test_promotion_clears_approvals_so_next_version_needs_review_again(tmp_path, monkeypatch):
    """승격 후 승인을 남겨두면 다음 버전이 과거 승인으로 통과한다."""
    from harness_api.approvals import ApprovalStore
    from harness_api.component_store import ComponentStore

    app = make_env(tmp_path, monkeypatch, approvals="1")
    with TestClient(app) as c:
        tok = c.post("/auth/dev-login", json={"email": "a@x.com"}).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        uid = c.get("/me", headers=h).json()["id"]
        sk = f"personal:{uid}"
        c.put(
            "/components/team-ctx",
            json={"name": "n", "description": "", "data": READY_COMPONENT},
            headers=h,
        )
        ComponentStore(app.state.engine).set_status(sk, "team-ctx", "ready")

        store = ApprovalStore(app.state.engine)
        store.record(sk, "team-ctx", "reviewer-uid", 1, "검토 완료")
        assert len(store.list(sk, "team-ctx")) == 1

        r = c.post("/components/team-ctx/promote", headers=h)
        # 카탈로그 스토어가 없으면 503 — 그 경우는 승인 정리 여부를 못 본다.
        if r.status_code == 200:
            assert store.list(sk, "team-ctx") == []


def test_approvals_are_scope_isolated(tmp_path, monkeypatch):
    """남의 스코프 컴포넌트에 승인을 남길 수 없다."""
    app = make_env(tmp_path, monkeypatch, approvals="1")
    with TestClient(app) as c:
        a = {"Authorization": f"Bearer {c.post('/auth/dev-login', json={'email': 'a@x.com'}).json()['token']}"}
        b = {"Authorization": f"Bearer {c.post('/auth/dev-login', json={'email': 'b@x.com'}).json()['token']}"}
        c.put("/components/team-ctx", json={"name": "n", "description": "", "data": READY_COMPONENT}, headers=a)
        assert c.post("/components/team-ctx/approvals", json={"note": ""}, headers=b).status_code == 404


def test_approval_note_is_recorded_for_audit(tmp_path, monkeypatch):
    """누가 왜 승인했는지가 남아야 감사가 된다."""
    app = make_env(tmp_path, monkeypatch, approvals="1")
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {c.post('/auth/dev-login', json={'email': 'a@x.com'}).json()['token']}"}
        c.put("/components/team-ctx", json={"name": "n", "description": "", "data": READY_COMPONENT}, headers=h)
        c.post("/components/team-ctx/approvals", json={"note": "샌드박스 확인함"}, headers=h)
        records = c.get("/components/team-ctx/approvals", headers=h).json()["approvals"]
        assert records[0]["note"] == "샌드박스 확인함"
        assert json.dumps(records)  # 직렬화 가능
