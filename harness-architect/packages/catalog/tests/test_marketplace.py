"""플러그인 마켓플레이스 소스 테스트 — 네트워크 없이 fetcher 주입.

plugin→Component 매핑(타입 추론·source·keywords) · dedup · max_plugins · 오프라인 폴백 ·
federate 편입(HARNESS_MARKETPLACE=on)을 검증한다. 실제 GitHub 는 치지 않는다.
"""

from __future__ import annotations

from harness_catalog import (
    FederatedRegistry,
    MarketplaceSource,
    Settings,
    build_live_sources,
    federate,
    plugin_to_component,
)
from harness_resolver import InMemoryRegistry

SKILL_PLUGIN = {
    "name": "box",
    "description": "Work with your Box content from Claude Code",
    "category": "productivity",
    "skills": ["./skills/box", "./skills/box-legal"],
    "source": {"source": "url", "url": "https://github.com/box/box-for-ai.git"},
}
MCP_PLUGIN = {
    "name": "airtable",
    "description": "Database layer for agents. Bundles the official Airtable MCP server.",
    "category": "productivity",
    "source": {"source": "git-subdir", "url": "https://github.com/Airtable/skills.git", "path": "plugins/airtable"},
}
HOOK_PLUGIN = {
    "name": "secret-guard",
    "description": "Block risky commands",
    "hooks": {"PreToolUse": [{"command": "guard.sh"}]},
    "source": "./plugins/secret-guard",
}
LOCAL_PLUGIN = {
    "name": "clangd-lsp",
    "displayName": "clangd",
    "description": "C/C++ language server for code intelligence",
    "version": "1.0.0",
    "source": "./plugins/clangd-lsp",
}
# 실행 마커 없음 + 능력이 knowledge facet(convention.coding) 뿐 → context.
CONTEXT_KNOWLEDGE_PLUGIN = {
    "name": "team-style-guide",
    "description": "Team coding convention and style guide as always-on background",
    "category": "convention",
    "source": "./plugins/team-style-guide",
}
# 실행 마커 없음 + 능력이 prompt facet(prompt.format) 뿐 → context.
CONTEXT_PROMPT_PLUGIN = {
    "name": "output-format-rules",
    "description": "Structured output format guidance injected as a prompt directive",
    "source": "./plugins/output-format-rules",
}
# 실행 마커 없지만 능력이 task facet(analyze.data) → context 아님(기본 skill).
TASK_PLUGIN = {
    "name": "data-analyzer",
    "description": "Analyze data and produce statistics",
    "source": "./plugins/data-analyzer",
}


# ── plugin → Component 매핑 ──
def test_skill_plugin_maps_type_source_keywords():
    c = plugin_to_component(SKILL_PLUGIN)
    assert c is not None
    assert c.id == "box"
    assert c.type == "skill"  # skills 배열 → skill
    assert c.source == "https://github.com/box/box-for-ai.git"
    assert "productivity" in c.keywords  # category 가 keywords 로


def test_mcp_plugin_inferred_from_description():
    c = plugin_to_component(MCP_PLUGIN)
    assert c is not None and c.type == "mcp"  # "bundles the official ... MCP server"
    assert c.source == "https://github.com/Airtable/skills.git"


def test_hook_plugin_from_explicit_hooks():
    c = plugin_to_component(HOOK_PLUGIN)
    assert c is not None and c.type == "hook"
    assert c.source == "./plugins/secret-guard"  # 로컬 경로 source 그대로


def test_local_source_string_and_display_name():
    c = plugin_to_component(LOCAL_PLUGIN)
    assert c is not None
    assert c.type == "skill"  # 배열·힌트 없음 → 기본 skill
    assert c.name == "clangd"  # displayName 우선
    assert c.version == "1.0.0"


def test_nameless_plugin_skipped():
    assert plugin_to_component({"description": "이름 없음"}) is None


def test_context_plugin_from_knowledge_facet():
    c = plugin_to_component(CONTEXT_KNOWLEDGE_PLUGIN)
    assert c is not None and c.type == "context"  # convention.coding(knowledge) 뿐 → context
    assert "convention.coding" in c.provides


def test_context_plugin_from_prompt_facet():
    c = plugin_to_component(CONTEXT_PROMPT_PLUGIN)
    assert c is not None and c.type == "context"  # prompt.format(prompt) 뿐 → context


def test_task_facet_plugin_stays_skill():
    c = plugin_to_component(TASK_PLUGIN)
    assert c is not None and c.type == "skill"  # analyze.data(task) → context 아님, 기본 skill


# ── MarketplaceSource ──
def _fetcher(payload: dict):
    def _f(_url: str) -> dict:
        return payload
    return _f


def test_marketplace_source_maps_and_dedups():
    payload = {"name": "official", "plugins": [SKILL_PLUGIN, MCP_PLUGIN, SKILL_PLUGIN]}  # box 중복
    comps = MarketplaceSource(fetcher=_fetcher(payload), clock=lambda: 0.0).components()
    ids = sorted(c.id for c in comps)
    assert ids == ["airtable", "box"]  # dedup
    assert {c.type for c in comps} == {"skill", "mcp"}


def test_marketplace_max_plugins_caps():
    plugins = [{"name": f"p{i}", "description": "x"} for i in range(10)]
    src = MarketplaceSource(fetcher=_fetcher({"plugins": plugins}), clock=lambda: 0.0, max_plugins=4)
    assert len(src.components()) == 4


def test_marketplace_missing_plugins_array_is_empty():
    src = MarketplaceSource(fetcher=_fetcher({"name": "x"}), clock=lambda: 0.0)
    assert src.components() == []


def test_marketplace_offline_fallback():
    import urllib.error

    def dead(_url: str) -> dict:
        raise urllib.error.URLError("down")

    assert MarketplaceSource(fetcher=dead, clock=lambda: 0.0).components() == []  # 크래시 없음


# ── federate 편입 ──
def _settings(**kw: object) -> Settings:
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


def test_build_live_sources_includes_marketplace_when_on():
    srcs = build_live_sources(_settings(marketplace_mode="on"), fetcher=_fetcher({"plugins": [SKILL_PLUGIN]}))
    assert len(srcs) == 1 and isinstance(srcs[0], MarketplaceSource)


def test_federate_combines_registry_and_marketplace():
    # 둘 다 on — 한 fetcher 가 URL 로 분기(레지스트리 vs 마켓플레이스).
    def fetcher(url: str) -> dict:
        if "marketplace" in url or "githubusercontent" in url:
            return {"plugins": [SKILL_PLUGIN]}
        return {"servers": [], "metadata": {}}

    settings = _settings(live_registry_mode="on", marketplace_mode="on")
    fed = federate(InMemoryRegistry([]), settings=settings, fetcher=fetcher)
    assert isinstance(fed, FederatedRegistry)
    assert [c.id for c in fed.all()] == ["box"]  # 마켓플레이스에서 box 유입
