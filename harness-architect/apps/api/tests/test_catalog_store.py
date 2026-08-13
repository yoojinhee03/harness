"""DB 백엔드 카탈로그 테스트 — harvest→DB 적재, 서빙은 DB 읽기(네트워크 없음).

CatalogStore(replace/all/get/count/revision) · DbCatalogSource(revision 캐시) ·
sync_catalog(fake fetcher 로 두 소스 harvest→DB) · FederatedRegistry 서빙. 임시 SQLite 파일 사용.
"""

from __future__ import annotations

from urllib.parse import urlparse

from harness_api.catalog_store import CatalogStore, DbCatalogSource, seconds_since, sync_catalog
from harness_api.db import make_engine
from harness_catalog import FederatedRegistry, Settings
from harness_resolver import Component, InMemoryRegistry


def _engine(tmp_path):
    return make_engine(f"sqlite:///{tmp_path}/catalog.db")


def _comp(cid: str, ctype: str = "mcp", provides: list[str] | None = None) -> Component:
    return Component(id=cid, type=ctype, name=cid.upper(), version="1.0.0", provides=provides or [])


# ── CatalogStore ──
def test_replace_all_get_count(tmp_path):
    store = CatalogStore(_engine(tmp_path))
    n = store.replace("registry", [_comp("a/x"), _comp("a/y")])
    assert n == 2
    assert store.count() == 2
    assert sorted(c.id for c in store.all()) == ["a/x", "a/y"]
    got = store.get("a/x")
    assert got is not None and got.name == "A/X"
    assert store.get("a/x", version="9.9.9") is None  # 버전 불일치
    assert store.get("nope") is None


def test_replace_is_atomic_per_origin(tmp_path):
    store = CatalogStore(_engine(tmp_path))
    store.replace("registry", [_comp("r/1"), _comp("r/2")])
    store.replace("marketplace", [_comp("m/1", "skill")])
    assert store.count() == 3
    # registry 재적재 → registry 행만 교체, marketplace 는 유지.
    store.replace("registry", [_comp("r/1")])
    assert sorted(c.id for c in store.all()) == ["m/1", "r/1"]


def test_revision_changes_on_write(tmp_path):
    store = CatalogStore(_engine(tmp_path))
    r0 = store.revision()
    store.replace("registry", [_comp("a/x")])
    r1 = store.revision()
    assert r0 != r1  # 내용 변화 → revision 변경


# ── DbCatalogSource (revision 캐시) ──
def test_db_source_caches_until_revision_changes(tmp_path):
    engine = _engine(tmp_path)
    store = CatalogStore(engine)
    store.replace("registry", [_comp("a/x")])
    src = DbCatalogSource(store)
    first = src.components()
    assert [c.id for c in first] == ["a/x"]
    # 변화 없음 → 같은 캐시 객체 재사용(재조회 안 함).
    assert src.components() is first
    # DB 가 바뀌면 다음 호출에 재로드.
    store.replace("registry", [_comp("a/x"), _comp("a/z")])
    reloaded = src.components()
    assert reloaded is not first
    assert sorted(c.id for c in reloaded) == ["a/x", "a/z"]


# ── sync_catalog (harvest → DB) ──
REGISTRY_ENTRY = {
    "server": {
        "name": "acme/remote-mcp",
        "title": "Remote",
        "description": "웹 검색 원격",
        "version": "1.0.0",
        "remotes": [{"type": "streamable-http", "url": "https://mcp.acme/x"}],
    },
    "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "isLatest": True}},
}
MARKET_PLUGIN = {
    "name": "box",
    "description": "Work with Box",
    "category": "productivity",
    "skills": ["./skills/box"],
    "source": {"source": "url", "url": "https://github.com/box/box-for-ai.git"},
}


def _both_sources_fetcher(url: str) -> dict:
    """URL 로 레지스트리/마켓플레이스 분기(build_live_sources 가 두 소스에 같은 fetcher 주입)."""
    if "/v0/servers" in urlparse(url).path:
        return {"servers": [REGISTRY_ENTRY], "metadata": {}}
    return {"plugins": [MARKET_PLUGIN]}


def _settings(**kw) -> Settings:
    base = dict(
        anthropic_key=None,
        voyage_key=None,
        embedder_mode="local",
        ranker_mode="heuristic",
        embed_model="x",
        claude_model="y",
    )
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def test_sync_catalog_writes_both_origins(tmp_path):
    engine = _engine(tmp_path)
    cfg = _settings(live_registry_mode="on", marketplace_mode="on")
    res = sync_catalog(engine, settings=cfg, fetcher=_both_sources_fetcher)
    assert res == {"registry": 1, "marketplace": 1}
    store = CatalogStore(engine)
    by_id = {c.id: c for c in store.all()}
    assert set(by_id) == {"acme/remote-mcp", "box"}
    assert by_id["box"].type == "skill" and by_id["acme/remote-mcp"].type == "mcp"


def test_sync_catalog_noop_when_flags_off(tmp_path):
    engine = _engine(tmp_path)
    res = sync_catalog(engine, settings=_settings(), fetcher=_both_sources_fetcher)
    assert res == {}
    assert CatalogStore(engine).count() == 0  # 소스 없음 → 아무것도 안 씀


# ── 서빙(로컬 + DB) ──
def test_federated_serving_from_db(tmp_path):
    engine = _engine(tmp_path)
    cfg = _settings(live_registry_mode="on", marketplace_mode="on")
    sync_catalog(engine, settings=cfg, fetcher=_both_sources_fetcher)
    local = InMemoryRegistry([_comp("local/seed", "context")])
    reg = FederatedRegistry(local, [DbCatalogSource(CatalogStore(engine))])
    ids = sorted(c.id for c in reg.all())
    assert ids == ["acme/remote-mcp", "box", "local/seed"]  # 로컬 시드 + DB harvest
    assert reg.get("box").type == "skill"  # DB 에서 서빙


# ── seconds_since ──
def test_seconds_since():
    assert seconds_since(None) == float("inf")
    assert seconds_since("not-a-date") == float("inf")
    assert seconds_since("2020-01-01T00:00:00+00:00") > 0  # 과거 → 양수 경과
