"""라이브 MCP 레지스트리 연동 테스트 — 네트워크 없이 fetcher 주입으로 관통.

매핑(remote/npm) · 커서 페이지네이션 · TTL 캐시 · 오프라인 폴백 · FederatedRegistry(로컬 우선)를
검증한다. 실제 registry.modelcontextprotocol.io 는 치지 않는다(결정성).
"""

from __future__ import annotations

import urllib.error
from urllib.parse import parse_qs, urlparse

from harness_catalog import (
    FederatedRegistry,
    MCPRegistrySource,
    Settings,
    build_live_sources,
    descriptor_from_entry,
    federate,
)
from harness_resolver import Component, InMemoryRegistry


# ── 픽스처: 엔트리·fetcher·clock ──
def _official(status: str = "active", is_latest: bool = True) -> dict:
    return {"io.modelcontextprotocol.registry/official": {"status": status, "isLatest": is_latest}}


REMOTE_ENTRY = {
    "name": "acme/remote-mcp",
    "title": "Remote Search",
    "description": "웹 검색 원격 서버",
    "version": "1.0.0",
    "remotes": [{"type": "streamable-http", "url": "https://mcp.acme.example/x"}],
    "_meta": _official(),
}
NPM_ENTRY = {
    "name": "acme/gh-mcp",
    "title": "GitHub",
    "description": "깃허브 이슈·PR 관리",
    "version": "2.1.0",
    "packages": [
        {"registry_type": "npm", "identifier": "@acme/gh-mcp", "environment_variables": [{"name": "GH_TOKEN"}]}
    ],
    "_meta": _official(),
}
STALE_ENTRY = {"name": "acme/old", "description": "구버전", "version": "0.1.0", "_meta": _official(is_latest=False)}
DELETED_ENTRY = {"name": "acme/gone", "description": "삭제됨", "version": "1.0.0", "_meta": _official(status="deleted")}


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class PagedFetcher:
    """pages[i] 를 cursor=i 로 서빙. page 는 {servers, metadata:{nextCursor}}."""

    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, url: str) -> dict:
        self.calls.append(url)
        cursor = parse_qs(urlparse(url).query).get("cursor", [None])[0]
        return self.pages[int(cursor) if cursor is not None else 0]

    @property
    def cycles(self) -> int:
        """전체 재페치 사이클 수(= cursor 없는 1페이지 요청 횟수)."""
        return sum(1 for u in self.calls if "cursor=" not in u)


# ── 매핑 ──
def test_descriptor_from_remote_entry_maps_url():
    desc = descriptor_from_entry(REMOTE_ENTRY)
    assert desc is not None
    assert desc.id == "acme/remote-mcp"
    assert desc.name == "Remote Search"
    assert desc.url == "https://mcp.acme.example/x"
    assert desc.command is None


def test_descriptor_from_npm_entry_maps_stdio_command_and_env():
    desc = descriptor_from_entry(NPM_ENTRY)
    assert desc is not None
    assert desc.command == "npx"
    assert desc.args == ["-y", "@acme/gh-mcp"]
    assert desc.env == {"GH_TOKEN": ""}
    assert desc.url is None


def test_descriptor_skips_non_latest_and_deleted():
    assert descriptor_from_entry(STALE_ENTRY) is None
    assert descriptor_from_entry(DELETED_ENTRY) is None
    assert descriptor_from_entry({"description": "이름 없음"}) is None


def test_descriptor_unwraps_real_wrapped_shape():
    # 실제 registry.modelcontextprotocol.io 형태: {"server": {...}, "_meta": {...}}
    wrapped = {
        "server": {
            "name": "ac.inference.sh/mcp",
            "title": "inference.sh",
            "description": "Run 150+ AI apps",
            "version": "1.0.1",
            "remotes": [{"type": "streamable-http", "url": "https://api.inference.sh/mcp"}],
        },
        "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "isLatest": True}},
    }
    desc = descriptor_from_entry(wrapped)
    assert desc is not None
    assert desc.id == "ac.inference.sh/mcp"
    assert desc.name == "inference.sh"
    assert desc.url == "https://api.inference.sh/mcp"
    # 래퍼 안 구버전(isLatest=false)은 스킵.
    stale = {
        "server": {"name": "x", "version": "1.0.0"},
        "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": False}},
    }
    assert descriptor_from_entry(stale) is None


def test_harvested_component_carries_mcp_spec():
    fetcher = PagedFetcher([{"servers": [REMOTE_ENTRY, NPM_ENTRY], "metadata": {}}])
    comps = MCPRegistrySource(fetcher=fetcher, clock=Clock()).components()
    by_id = {c.id: c for c in comps}
    remote = by_id["acme/remote-mcp"]
    assert remote.type == "mcp"
    assert remote.mcp is not None and remote.mcp.transport == "http"
    assert remote.mcp.url == "https://mcp.acme.example/x"
    gh = by_id["acme/gh-mcp"]
    assert gh.mcp is not None and gh.mcp.transport == "stdio"
    assert gh.mcp.command == "npx" and gh.mcp.args == ["-y", "@acme/gh-mcp"]


# ── 페이지네이션 ──
def test_pagination_follows_next_cursor_and_dedups():
    pages = [
        {"servers": [REMOTE_ENTRY, STALE_ENTRY], "metadata": {"nextCursor": "1"}},
        {"servers": [NPM_ENTRY, REMOTE_ENTRY], "metadata": {}},  # REMOTE 중복 → dedup
    ]
    fetcher = PagedFetcher(pages)
    comps = MCPRegistrySource(fetcher=fetcher, clock=Clock()).components()
    ids = sorted(c.id for c in comps)
    assert ids == ["acme/gh-mcp", "acme/remote-mcp"]  # STALE 스킵 + 중복 제거
    assert len(fetcher.calls) == 2  # 두 페이지 모두 방문


def test_max_pages_caps_fetch():
    # 끝없이 nextCursor 를 주는 페이지 → max_pages 에서 멈춘다.
    pages = [{"servers": [], "metadata": {"nextCursor": str(i + 1)}} for i in range(10)]
    src = MCPRegistrySource(fetcher=PagedFetcher(pages), clock=Clock(), max_pages=3)
    src.components()
    # 정확히 max_pages 만큼만 페이지를 방문(무한 루프 방지).
    assert len([c for c in src._cache]) == 0  # noqa: SLF001 — 캐시 비었는지만 확인


# ── TTL 캐시 ──
def test_ttl_cache_reuses_within_window_then_refetches():
    clock = Clock()
    fetcher = PagedFetcher([{"servers": [REMOTE_ENTRY], "metadata": {}}])
    src = MCPRegistrySource(fetcher=fetcher, clock=clock, ttl_seconds=300.0)

    src.components()
    assert fetcher.cycles == 1
    clock.t = 299.0  # TTL 내 → 캐시 재사용
    src.components()
    assert fetcher.cycles == 1
    clock.t = 301.0  # TTL 만료 → 재페치
    src.components()
    assert fetcher.cycles == 2


# ── 오프라인 폴백 ──
class FlakyFetcher:
    def __init__(self, page: dict) -> None:
        self.page = page
        self.fail = False
        self.calls = 0

    def __call__(self, url: str) -> dict:
        self.calls += 1
        if self.fail:
            raise urllib.error.URLError("network down")
        return self.page


def test_offline_first_fetch_returns_empty_without_crashing():
    fetcher = FlakyFetcher({"servers": [REMOTE_ENTRY], "metadata": {}})
    fetcher.fail = True
    src = MCPRegistrySource(fetcher=fetcher, clock=Clock())
    assert src.components() == []  # 크래시 없이 빈 결과


def test_offline_falls_back_to_stale_cache():
    clock = Clock()
    fetcher = FlakyFetcher({"servers": [REMOTE_ENTRY], "metadata": {}})
    src = MCPRegistrySource(fetcher=fetcher, clock=clock, ttl_seconds=300.0)

    good = src.components()
    assert [c.id for c in good] == ["acme/remote-mcp"]
    clock.t = 400.0  # TTL 만료 후 네트워크 다운
    fetcher.fail = True
    stale = src.components()
    assert [c.id for c in stale] == ["acme/remote-mcp"]  # 마지막 캐시 유지


# ── FederatedRegistry ──
def _source_with(*entries: dict) -> MCPRegistrySource:
    return MCPRegistrySource(fetcher=PagedFetcher([{"servers": list(entries), "metadata": {}}]), clock=Clock())


def test_federated_union_and_local_precedence():
    local = InMemoryRegistry([Component(id="acme/gh-mcp", type="mcp", name="LOCAL", version="9.9.9")])
    fed = FederatedRegistry(local, [_source_with(REMOTE_ENTRY, NPM_ENTRY)])

    ids = sorted(c.id for c in fed.all())
    assert ids == ["acme/gh-mcp", "acme/remote-mcp"]  # 합집합
    # id 충돌 → 로컬이 이긴다.
    assert fed.get("acme/gh-mcp").name == "LOCAL"
    # 로컬에 없는 것 → 라이브로 폴스루.
    assert fed.get("acme/remote-mcp").mcp.url == "https://mcp.acme.example/x"
    assert fed.get("nope") is None


def test_federated_live_source_failure_keeps_local():
    local = InMemoryRegistry([Component(id="local/only", type="skill", name="X", version="1.0.0")])
    dead = FlakyFetcher({"servers": [], "metadata": {}})
    dead.fail = True
    fed = FederatedRegistry(local, [MCPRegistrySource(fetcher=dead, clock=Clock())])
    assert [c.id for c in fed.all()] == ["local/only"]  # 라이브 죽어도 로컬은 뜬다


# ── federate 팩토리(옵트인) ──
def _settings(mode: str) -> Settings:
    return Settings(
        anthropic_key=None,
        voyage_key=None,
        embedder_mode="local",
        ranker_mode="heuristic",
        embed_model="x",
        claude_model="y",
        live_registry_mode=mode,
    )


def test_federate_off_by_default_returns_local_identity():
    local = InMemoryRegistry([])
    assert federate(local, settings=_settings("off")) is local
    assert build_live_sources(_settings("off")) == []


def test_federate_on_wraps_and_includes_live():
    local = InMemoryRegistry([])
    fetcher = PagedFetcher([{"servers": [REMOTE_ENTRY], "metadata": {}}])
    fed = federate(local, settings=_settings("on"), fetcher=fetcher)
    assert isinstance(fed, FederatedRegistry)
    assert [c.id for c in fed.all()] == ["acme/remote-mcp"]
