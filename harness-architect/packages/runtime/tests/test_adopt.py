"""역방향 adopt 테스트 (Phase 7) — eject 산출물을 IR 로 되흡수하는 라운드트립.

eject∘adopt 가 구조적으로 식별 가능한 부분(MCP ref·model·프롬프트 본문)을 항등에 가깝게
복원하는지 확인한다. 카탈로그에 없는 서버는 unknown(수확 후보)으로 분리.
"""

from __future__ import annotations

from harness_resolver import (
    Component,
    ComponentSelection,
    HarnessConfig,
    HarnessMetadata,
    InMemoryRegistry,
    PromptLayer,
    PromptSpec,
    resolve,
)
from harness_resolver.models import McpServerSpec
from harness_runtime import adopt, emit


def registry() -> InMemoryRegistry:
    return InMemoryRegistry(
        [
            Component(
                id="github-mcp", type="mcp", name="GitHub", version="1.4.0",
                provides=["vcs.code-hosting"],
                mcp=McpServerSpec(transport="stdio", command="npx", args=["-y", "server-github"]),
            )
        ]
    )


def _ejected_tree(target: str) -> dict[str, str]:
    reg = registry()
    config = HarnessConfig(
        metadata=HarnessMetadata(id="pr-bot"),
        components=[ComponentSelection(ref="github-mcp@1.4.0")],
        prompt=PromptSpec(system=[PromptLayer(inline="너는 시니어 리뷰어다.")]),
    )
    resolved = resolve(config, reg).resolved
    assert resolved is not None
    return emit(resolved, target)


def test_adopt_roundtrips_claude_code():
    """eject(claude-code) → adopt → 같은 MCP ref + 프롬프트 본문 복원, 재resolve 성공."""
    tree = _ejected_tree("claude-code")
    result = adopt(tree, registry(), harness_id="re")

    refs = [c.ref for c in result.config.components]
    assert refs == ["github-mcp@1.4.0"]
    assert result.unknown_mcp == []
    assert result.config.prompt is not None
    assert result.config.prompt.system[0].inline == "너는 시니어 리뷰어다."
    # 되흡수한 config 가 다시 resolve 되는지(라운드트립 유효성)
    assert resolve(result.config, registry()).ok is True


def test_adopt_roundtrips_cursor():
    tree = _ejected_tree("cursor")
    result = adopt(tree, registry(), harness_id="re")
    assert [c.ref for c in result.config.components] == ["github-mcp@1.4.0"]
    assert result.config.prompt is not None
    assert "너는 시니어 리뷰어다." in result.config.prompt.system[0].inline


def test_adopt_flags_unknown_mcp_as_harvest_candidate():
    """카탈로그에 없는 서버는 ref 가 아니라 unknown(수확 후보)으로 분리된다."""
    tree = {
        ".mcp.json": '{"mcpServers": {"exotic-mcp": {"command": "npx", "args": []}}}',
        "CLAUDE.md": "<!-- gen -->\n\n지침 텍스트",
    }
    result = adopt(tree, registry())
    assert result.unknown_mcp == ["exotic-mcp"]
    assert result.config.components == []  # 미지 서버는 ref 로 넣지 않음
    assert any("수확 후보" in n for n in result.notes)
    assert result.config.prompt is not None and result.config.prompt.system[0].inline == "지침 텍스트"
