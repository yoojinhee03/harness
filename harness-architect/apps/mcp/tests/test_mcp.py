"""MCP 툴 스모크 — in-process 함수를 직접 호출한다(레포 안에서 sibling 카탈로그 전제).

FastMCP 등록과 무관하게 핵심 로직은 순수 함수라 그대로 테스트한다.
"""

from __future__ import annotations

from pathlib import Path

from harness_mcp import server

PR_BOT_YAML = """
apiVersion: harness/v1
kind: Harness
metadata:
  id: pr-review-bot
  name: PR Review Bot
components:
  - ref: github-mcp@1.4.0
  - ref: pr-review-skill@2.1.0
  - ref: secret-scan-hook@1.2.0
"""


def test_list_catalog_filters_by_type() -> None:
    mcps = server.list_catalog(type="mcp")
    assert mcps, "카탈로그(sibling)를 못 찾음 — 레포 안에서 실행하는지 확인"
    assert all(c["type"] == "mcp" for c in mcps)


def test_recommend_returns_grounded_recommendations() -> None:
    out = server.recommend_harness("GitHub PR 리뷰를 자동화하고 싶다", top_k=5)
    assert out["recommendations"], "추천이 비어있음"
    assert "groups" in out and "requirements" in out


def test_resolve_ok_for_valid_config() -> None:
    out = server.resolve_harness(PR_BOT_YAML)
    assert out["ok"] is True
    assert out["diagnostics"]["errors"] == []
    assert set(out["resolved"]["components"]) >= {"github-mcp", "pr-review-skill", "secret-scan-hook"}


def test_resolve_reports_diagnostics_for_unknown_ref() -> None:
    bad = PR_BOT_YAML.replace("github-mcp@1.4.0", "does-not-exist@9.9.9")
    out = server.resolve_harness(bad)
    assert out["ok"] is False


def test_eject_writes_claude_dir(tmp_path: Path) -> None:
    out = server.eject_harness(PR_BOT_YAML, target="claude-code", out_dir=str(tmp_path))
    assert out["ok"] is True
    assert (tmp_path / ".claude" / "settings.json").exists()
    assert (tmp_path / ".mcp.json").exists()
    assert (tmp_path / "CLAUDE.md").exists()


def test_eject_returns_tree_without_out_dir() -> None:
    out = server.eject_harness(PR_BOT_YAML)
    assert out["ok"] is True
    assert ".claude/settings.json" in out["files"]


def test_eject_rejects_unknown_target() -> None:
    out = server.eject_harness(PR_BOT_YAML, target="cursor")
    assert out["ok"] is False
    assert "targets" in out
