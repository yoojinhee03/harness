"""멀티테넌시 저장소 테스트 — 인증(Bearer)·사용자 격리·팀 공유·SSE 스코프.

저장소 디렉터리는 tmp 로 격리(HARNESS_STORE_DIR). 핵심 계약: 인증 없으면 접근 불가,
남의 personal 은 못 보고, 팀 스코프는 멤버만, SSE 는 가시 스코프 이벤트만 흘린다.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

HARNESS_YAML = "metadata:\n  id: pr-bot\nmodel:\n  name: claude-sonnet-5\ncomponents: []\n"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_STORE_DIR", str(tmp_path / "store"))
    from harness_api.main import app

    with TestClient(app) as c:
        yield c


def auth(client, handle: str) -> dict[str, str]:
    """등록 → Bearer 헤더."""
    r = client.post("/auth/register", json={"handle": handle})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ── 인증 ──


def test_requires_auth(client):
    assert client.get("/harnesses").status_code == 401
    assert client.get("/me").status_code == 401


def test_register_duplicate_409(client):
    auth(client, "alice")
    assert client.post("/auth/register", json={"handle": "alice"}).status_code == 409


def test_me_lists_teams(client):
    a = auth(client, "alice")
    me = client.get("/me", headers=a).json()
    assert me["id"] == "alice" and me["teams"] == []


def test_versions_history(client):
    a = auth(client, "alice")
    client.put("/harnesses/h", json={"yaml": "v1\n"}, headers=a)
    client.put("/harnesses/h", json={"yaml": "v2\n"}, headers=a)
    doc = client.get("/harnesses/h", headers=a).json()
    assert doc["version"] == 2
    versions = client.get("/harnesses/h/versions", headers=a).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["yaml"] == "v2\n" and versions[1]["yaml"] == "v1\n"
    assert [h["version"] for h in client.get("/harnesses", headers=a).json()] == [2]  # 목록 요약에 버전


def test_optimistic_locking(client):
    a = auth(client, "alice")
    client.put("/harnesses/h", json={"yaml": "v1\n"}, headers=a)  # v1
    r2 = client.put("/harnesses/h", json={"yaml": "v2\n"}, headers={**a, "If-Match": "1"})
    assert r2.status_code == 200 and r2.json()["version"] == 2
    # 오래된 버전(1) 기준 저장 → 충돌 409
    r3 = client.put("/harnesses/h", json={"yaml": "v2b\n"}, headers={**a, "If-Match": "1"})
    assert r3.status_code == 409


def test_pagination(client):
    a = auth(client, "alice")
    for i in range(3):
        client.put(f"/harnesses/h{i}", json={"yaml": f"y{i}\n"}, headers=a)
    assert len(client.get("/harnesses", headers=a).json()) == 3
    assert len(client.get("/harnesses", params={"limit": 2}, headers=a).json()) == 2
    assert len(client.get("/harnesses", params={"limit": 2, "offset": 2}, headers=a).json()) == 1


def test_token_rotate_invalidates_old(client):
    a = auth(client, "alice")
    new = client.post("/auth/token/rotate", headers=a).json()["token"]
    assert client.get("/me", headers=a).status_code == 401  # 기존 토큰 무효
    assert client.get("/me", headers={"Authorization": f"Bearer {new}"}).json()["id"] == "alice"


# ── 사용자 격리 ──


def test_personal_isolation(client):
    a, b = auth(client, "alice"), auth(client, "bob")
    client.put("/harnesses/secret", json={"name": "S", "yaml": HARNESS_YAML}, headers=a)

    assert [h["id"] for h in client.get("/harnesses", headers=a).json()] == ["secret"]
    assert client.get("/harnesses", headers=b).json() == []  # bob 은 alice 것을 못 봄
    assert client.get("/harnesses/secret", headers=b).status_code == 404  # 직접 접근도 격리
    got = client.get("/harnesses/secret", headers=a).json()
    assert got["owner_id"] == "alice" and got["scope"] == "personal:alice"


# ── 팀 공유(메모리 공유) ──


def test_team_sharing(client):
    a, b = auth(client, "alice"), auth(client, "bob")
    tid = client.post("/teams", json={"name": "squad"}, headers=a).json()["id"]
    client.post(f"/teams/{tid}/members", json={"handle": "bob"}, headers=a)

    client.put(
        "/harnesses/shared", json={"name": "공유", "yaml": HARNESS_YAML},
        params={"scope": f"team:{tid}"}, headers=a,
    )
    # bob(팀원)은 팀 하네스를 봄
    ids = [h["id"] for h in client.get("/harnesses", headers=b).json()]
    assert "shared" in ids
    got = client.get("/harnesses/shared", params={"scope": f"team:{tid}"}, headers=b).json()
    assert got["yaml"] == HARNESS_YAML and got["scope"] == f"team:{tid}"


def test_non_member_forbidden(client):
    a, c = auth(client, "alice"), auth(client, "carol")
    tid = client.post("/teams", json={"name": "squad"}, headers=a).json()["id"]
    r = client.put(
        "/harnesses/x", json={"yaml": HARNESS_YAML}, params={"scope": f"team:{tid}"}, headers=c
    )
    assert r.status_code == 403  # carol 은 멤버가 아님
    assert client.get("/harnesses", headers=c).json() == []  # 팀 하네스가 목록에도 안 뜸


def test_add_member_requires_membership(client):
    a, b = auth(client, "alice"), auth(client, "bob")
    auth(client, "carol")
    tid = client.post("/teams", json={"name": "sq"}, headers=a).json()["id"]
    # bob(비멤버)이 carol 을 초대 → 403
    assert client.post(f"/teams/{tid}/members", json={"handle": "carol"}, headers=b).status_code == 403


def test_rbac_viewer_read_only(client):
    a, b = auth(client, "alice"), auth(client, "bob")
    tid = client.post("/teams", json={"name": "sq"}, headers=a).json()["id"]
    client.post(f"/teams/{tid}/members", json={"handle": "bob", "role": "viewer"}, headers=a)
    client.put("/harnesses/t", json={"yaml": "y\n"}, params={"scope": f"team:{tid}"}, headers=a)

    # viewer: 읽기 O, 쓰기 403
    assert client.get("/harnesses/t", params={"scope": f"team:{tid}"}, headers=b).status_code == 200
    assert client.put(
        "/harnesses/t2", json={"yaml": "z\n"}, params={"scope": f"team:{tid}"}, headers=b
    ).status_code == 403

    # editor 로 승격 → 쓰기 O
    client.post(f"/teams/{tid}/members", json={"handle": "bob", "role": "editor"}, headers=a)
    assert client.put(
        "/harnesses/t2", json={"yaml": "z\n"}, params={"scope": f"team:{tid}"}, headers=b
    ).status_code == 200


def test_persistence_across_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_STORE_DIR", str(tmp_path / "store"))
    from harness_api.main import app

    with TestClient(app) as c:
        h = auth(c, "alice")
        c.put("/harnesses/keep", json={"yaml": HARNESS_YAML}, headers=h)
    with TestClient(app) as c2:  # lifespan 재실행 — 디스크에서 재로드(토큰도 유지)
        assert client_get_ids(c2, h) == ["keep"]


def client_get_ids(c, headers):
    return [x["id"] for x in c.get("/harnesses", headers=headers).json()]


# ── SSE 스코프 격리 (제너레이터 직접 구동) ──


def test_event_stream_only_visible_scopes(tmp_path):
    import asyncio

    from harness_api.db import make_engine
    from harness_api.store import Broadcaster, HarnessStore, event_stream

    async def run() -> None:
        store = HarnessStore(make_engine(f"sqlite:///{tmp_path / 't.db'}"))
        store.put("personal:alice", "x", "alice", "X", "", HARNESS_YAML)
        bc = Broadcaster()
        gen = event_stream(store, bc, {"personal:alice"})

        ready = await gen.__anext__()
        assert [h["id"] for h in json.loads(ready["data"])["harnesses"]] == ["x"]

        await bc.publish({"type": "upsert", "id": "y", "scope": "personal:bob", "harness": {"id": "y"}})
        await bc.publish({"type": "upsert", "id": "z", "scope": "personal:alice", "harness": {"id": "z"}})
        ev = await asyncio.wait_for(gen.__anext__(), timeout=1)
        # bob 스코프 이벤트는 건너뛰고, alice 스코프 이벤트만 도착
        assert ev["event"] == "upsert" and json.loads(ev["data"])["id"] == "z"

        await gen.aclose()

    asyncio.run(run())


def test_register_rate_limited(client):
    """register 레이트리밋(20/hour) — 한정적으로 켜서 초과 시 429 확인."""
    import harness_api.main as m

    m.limiter.enabled = True
    try:
        codes = [client.post("/auth/register", json={"handle": f"u{i}"}).status_code for i in range(22)]
        assert codes.count(200) <= 20 and 429 in codes
    finally:
        m.limiter.enabled = False


def test_safe_id_blocks_traversal_and_empty():
    from harness_api.store import safe_id

    sid = safe_id("../../etc/passwd")
    assert "/" not in sid and not sid.startswith((".", "-"))
    assert safe_id("   ") == "harness"
    assert safe_id("My Bot!") == "my-bot"
