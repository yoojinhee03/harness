"""유저 저작 컴포넌트(스튜디오) 테스트 — 저장소·저작·검증·스코프 격리·요청-스코프 resolve.

LLM 키는 삭제해 결정적(휴리스틱/스킵) 경로로 검증한다 — 실제 Claude 호출·네트워크 없이.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from harness_catalog import FederatedRegistry
from harness_resolver import (
    Component,
    ComponentSelection,
    HarnessConfig,
    HarnessMetadata,
    InMemoryRegistry,
    resolve,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # 결정적: 휴리스틱/스킵 경로
    from harness_api.main import app

    with TestClient(app) as c:
        yield c


def auth(client: TestClient, email: str) -> dict[str, str]:
    r = client.post("/auth/dev-login", json={"email": email})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _context(cid: str = "u-team-conv") -> Component:
    return Component(
        id=cid, type="context", name="Team conv", version="0.1.0", status="stable",
        summary="team coding convention", body="Always follow the team style guide.",
        provides=["convention.coding"], capability_tags=["convention.coding"],
    )


# ── ComponentStore 단위 ──


def test_component_store_crud_versioning_isolation(tmp_path):
    from harness_api.component_store import ComponentStore
    from harness_api.db import make_engine

    store = ComponentStore(make_engine(f"sqlite:///{tmp_path / 'c.db'}"))
    comp = _context()
    store.put("personal:alice", comp.id, "alice", comp.name, comp.summary, comp.model_dump_json(), status="valid")
    store.put("personal:alice", comp.id, "alice", comp.name, "edited", comp.model_dump_json(), status="ready")

    doc = store.get("personal:alice", comp.id)
    assert doc is not None and doc["version"] == 2 and doc["status"] == "ready"
    assert [h["version"] for h in doc["history"]] == [1]  # 이전 버전 이력

    # 스코프 격리 — 다른 스코프엔 안 보임
    assert store.get("personal:bob", comp.id) is None
    assert [c["id"] for c in store.list_scopes(["personal:alice"])] == [comp.id]
    assert store.list_scopes(["personal:bob"]) == []

    # status 필터 + ready_components
    assert [c["id"] for c in store.list_scopes(["personal:alice"], status="ready")] == [comp.id]
    ready = store.ready_components(["personal:alice"])
    assert [c.id for c in ready] == [comp.id]
    assert store.ready_components(["personal:bob"]) == []

    assert store.delete("personal:alice", comp.id) is True
    assert store.get("personal:alice", comp.id) is None


def test_ready_component_resolves_via_scoped_registry(tmp_path):
    """'실제 사용' 핵심 — ready 컴포넌트가 요청-스코프 레지스트리로 resolve 되고, 타 스코프엔 격리."""
    from harness_api.component_store import ComponentStore, UserComponentSource
    from harness_api.db import make_engine

    store = ComponentStore(make_engine(f"sqlite:///{tmp_path / 'c.db'}"))
    comp = _context()
    store.put("personal:alice", comp.id, "alice", comp.name, "", comp.model_dump_json(), status="ready")

    base = InMemoryRegistry([])
    reg = FederatedRegistry(base, [UserComponentSource(store, {"personal:alice"})])
    assert reg.get(comp.id) is not None

    cfg = HarnessConfig(
        metadata=HarnessMetadata(id="h", name="h"),
        components=[ComponentSelection(ref=f"{comp.id}@0.1.0")],
    )
    res = resolve(cfg, reg)
    assert res.ok and any(rc.id == comp.id for rc in res.resolved.components)

    # 다른 유저 스코프에선 안 보임(누출 없음)
    reg_bob = FederatedRegistry(base, [UserComponentSource(store, {"personal:bob"})])
    assert reg_bob.get(comp.id) is None


# ── authoring 단위(휴리스틱/스킵) ──


def test_author_component_heuristic_offline(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from harness_api.authoring import author_component, validate_component

    comp = author_component("팀 파이썬 코딩 컨벤션: 타입힌트 필수, 함수는 짧게", "context")
    assert comp.type == "context" and comp.body
    assert comp.id.startswith("u-")  # 네임스페이스 접두사
    assert validate_component(comp)["ok"] is True

    # skill 도 휴리스틱으로 body 채움
    sk = author_component("PR diff 를 정확성·가독성·컨벤션 순으로 리뷰하는 절차", "skill")
    assert sk.type == "skill" and sk.body and sk.entrypoint

    # mcp/hook 은 실행 스펙이 없으면 검증에서 draft(에러)로 — 휴리스틱만으론 미완성
    m = author_component("GitHub 저장소·이슈·PR 접근", "mcp")
    assert m.type == "mcp" and validate_component(m)["ok"] is False  # mcp 스펙 없음


def test_author_skill_delegates_execution_to_requires(monkeypatch):
    """Fix A — 실행형 절차 skill 은 access 능력을 provides 로 지어내지 않고 requires 로 위임한다.

    브이로그 자동편집처럼 실제 실행(영상 컷·bgm)이 필요한 절차는, skill 이 스스로 못 하므로 그 access 능력을
    requires 에 실어 조립 때 gap(=실존 MCP 필요)으로 표면화되게 해야 한다(껍데기 방지)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from harness_api.authoring import author_component

    sk = author_component("브이로그 영상을 자동 편집하는 절차 — 컷·전환·bgm 삽입", "skill")
    assert sk.type == "skill"
    assert "media.edit" in sk.requires  # 편집 실행은 MCP 에 위임(requires)
    assert any(c in sk.requires for c in ("media.video", "media.audio"))
    # skill 은 실행(access)을 스스로 provides 한다고 주장하지 않는다
    assert all(c not in sk.provides for c in ("media.edit", "media.video", "media.audio"))


def test_author_all_types_via_llm():
    from harness_api.authoring import author_component, validate_component

    payload = {
        "name": "X", "summary": "s", "description": "d", "provides": ["review.code"],
        "body": "step 1", "requires": ["vcs.code-hosting"],
        "mcp": {"transport": "stdio", "command": "npx", "args": ["-y", "srv"]},
        "usage_note": "쓰기 주의", "auth": {"required": True, "type": "oauth", "scopes": ["repo"]},
        "events": ["before_tool_call"], "emit_command": "echo ok", "sandbox": "restricted",
        "blocking": True, "failure": "fail_closed",
    }

    def fake(_system, _user, _mt):
        return payload

    sk = author_component("x", "skill", complete=fake)
    assert sk.type == "skill" and sk.body == "step 1" and sk.requires == ["vcs.code-hosting"] and sk.entrypoint

    m = author_component("x", "mcp", complete=fake)
    assert m.type == "mcp" and m.mcp and m.mcp.command == "npx" and m.auth and m.auth.required
    assert validate_component(m)["ok"] is True

    h = author_component("x", "hook", complete=fake)
    assert h.type == "hook" and h.events == ["before_tool_call"] and h.emit_command == "echo ok"
    assert validate_component(h)["ok"] is True


def test_validate_rejects_empty_body_and_bad_cap(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from harness_api.authoring import validate_component

    bad = Component(id="u-x", type="context", name="x", version="0.1.0", status="stable",
                    summary="s", body="", provides=["not.a-real-cap"])
    res = validate_component(bad)
    assert res["ok"] is False and len(res["errors"]) >= 2  # 빈 body + 미지 능력


def test_test_component_skipped_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from harness_api.authoring import test_component

    r = test_component(_context())
    assert r["skipped"] is True and r["pass"] is False


# ── API 플로우 ──


def test_components_requires_auth(client):
    assert client.get("/components").status_code == 401
    assert client.post("/components/author", json={"prompt": "x"}).status_code == 401


def test_author_requires_llm_key(client):
    # 키 미등록이면 LLM 사용(생성) 차단.
    a = auth(client, "alice@x.io")
    assert client.post("/components/author", json={"prompt": "x"}, headers=a).status_code == 400


def test_author_save_validate_test_flow(client):
    a = auth(client, "alice@x.io")
    client.put("/settings/llm", json={"llm_key": "sk-x"}, headers=a)  # 키 등록(SDK 없어 생성은 휴리스틱 폴백)
    resp = client.post("/components/author", json={"prompt": "팀 코딩 컨벤션: 타입힌트 필수"}, headers=a)
    comp = resp.json()["component"]
    assert comp["type"] == "context" and comp["body"]
    cid = comp["id"]

    # 저장 → 자동 검증 → valid
    saved = client.put(f"/components/{cid}", json={"name": comp["name"], "data": comp}, headers=a)
    assert saved.status_code == 200, saved.text
    assert saved.json()["validation"]["ok"] is True

    # 목록에 valid 로 등장
    lst = client.get("/components", headers=a).json()
    assert [c["id"] for c in lst] == [cid] and lst[0]["status"] == "valid"

    # 테스트: 키는 있으나 SDK 미설치 → 통과 실패 → status 유지 valid(ready 로 못 감)
    tested = client.post(f"/components/{cid}/test", headers=a)
    assert tested.status_code == 200
    assert tested.json()["result"]["pass"] is False and tested.json()["status"] == "valid"


def test_component_personal_isolation(client):
    a, b = auth(client, "alice@x.io"), auth(client, "bob@x.io")
    client.put("/settings/llm", json={"llm_key": "sk-x"}, headers=a)
    comp = client.post("/components/author", json={"prompt": "코딩 컨벤션 가이드"}, headers=a).json()["component"]
    cid = comp["id"]
    client.put(f"/components/{cid}", json={"data": comp}, headers=a)

    assert client.get("/components", headers=b).json() == []  # bob 은 alice 것을 못 봄
    assert client.get(f"/components/{cid}", headers=b).status_code == 404
