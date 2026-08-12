"""공유 하네스 저장소 + SSE 테스트 — 웹↔확장 양방향 동기화의 백엔드 계약.

저장소 디렉터리는 tmp 로 격리한다(HARNESS_STORE_DIR). SSE 는 upsert/delete 가 실제로
스트림에 실리는지, put 이 응답 + 브로드캐스트를 함께 하는지 확인한다.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_STORE_DIR", str(tmp_path / "store"))
    # 저장소 dir 을 env 로 고정한 뒤 앱을 가져와 lifespan 을 태운다.
    from harness_api.main import app

    with TestClient(app) as c:
        yield c


HARNESS_YAML = "metadata:\n  id: pr-bot\nmodel:\n  name: claude-sonnet-5\ncomponents: []\n"


def test_crud_roundtrip(client):
    assert client.get("/harnesses").json() == []

    r = client.put("/harnesses/pr-bot", json={"name": "PR 봇", "description": "리뷰", "yaml": HARNESS_YAML})
    assert r.status_code == 200
    doc = r.json()
    assert doc["id"] == "pr-bot" and doc["yaml"] == HARNESS_YAML and doc["updated_at"]

    lst = client.get("/harnesses").json()
    assert len(lst) == 1 and lst[0]["id"] == "pr-bot" and "yaml" not in lst[0]  # 목록은 요약만

    got = client.get("/harnesses/pr-bot").json()
    assert got["yaml"] == HARNESS_YAML and got["name"] == "PR 봇"

    assert client.get("/harnesses/nope").status_code == 404

    assert client.delete("/harnesses/pr-bot").json()["ok"] is True
    assert client.get("/harnesses").json() == []
    assert client.delete("/harnesses/pr-bot").status_code == 404


def test_id_slugified_over_http(client):
    r = client.put("/harnesses/My Bot!", json={"yaml": HARNESS_YAML})
    assert r.json()["id"] == "my-bot"  # 공백·특수문자 정규화
    assert client.get("/harnesses/my-bot").status_code == 200


def test_safe_id_blocks_traversal_and_empty():
    """경로 탈출·빈 입력 방어(파일명 안전 슬러그) — URL 정규화와 무관하게 함수 자체를 검증."""
    from harness_api.store import safe_id

    sid = safe_id("../../etc/passwd")
    assert "/" not in sid and not sid.startswith((".", "-"))
    assert safe_id("   ") == "harness"
    assert safe_id("My Bot!") == "my-bot"


def test_persistence_across_app_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_STORE_DIR", str(tmp_path / "store"))
    from harness_api.main import app

    with TestClient(app) as c:
        c.put("/harnesses/keep", json={"yaml": HARNESS_YAML})
    # 새 TestClient(=lifespan 재실행)로도 디스크에서 다시 로드돼야 한다.
    with TestClient(app) as c2:
        assert [h["id"] for h in c2.get("/harnesses").json()] == ["keep"]


def test_event_stream_yields_ready_then_pushed_events(tmp_path):
    """SSE 제너레이터 직접 구동 — 연결 시 ready(현재 목록), 이후 publish 된 이벤트를 흘린다.

    (sync TestClient 로 SSE 스트림을 연 채 다른 요청을 하면 교착하므로 제너레이터를 직접 테스트.)
    """
    import asyncio

    from harness_api.store import Broadcaster, HarnessStore, event_stream

    async def run() -> None:
        store = HarnessStore(tmp_path / "store")
        store.put("existing", "E", "", HARNESS_YAML)
        bc = Broadcaster()
        gen = event_stream(store, bc)

        ready = await gen.__anext__()
        assert ready["event"] == "ready"
        payload = json.loads(ready["data"])
        assert [h["id"] for h in payload["harnesses"]] == ["existing"]

        await bc.publish({"type": "upsert", "id": "live", "harness": {"id": "live", "name": "L"}})
        ev = await asyncio.wait_for(gen.__anext__(), timeout=1)
        assert ev["event"] == "upsert" and json.loads(ev["data"])["harness"]["name"] == "L"

        await bc.publish({"type": "delete", "id": "live"})
        ev2 = await asyncio.wait_for(gen.__anext__(), timeout=1)
        assert ev2["event"] == "delete" and json.loads(ev2["data"])["id"] == "live"

        await gen.aclose()
        assert bc.subscriber_count == 0  # aclose → finally → unsubscribe

    asyncio.run(run())
