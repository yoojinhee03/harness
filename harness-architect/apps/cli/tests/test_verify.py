"""harness verify — 정적 검증 CI 게이트 (하드닝 TASK 5c/5d).

완료기준: 픽스처 레포에 올바른 종료코드(0 통과 / 1 위반 / 2 실행오류) · Cursor 손실 리포트가
이미터 제약과 일치 · env 값이 출력에 나타나지 않음(5b 보안).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from harness_cli.main import main


def _repo(
    tmp_path: Path,
    *,
    mcp: list[str] | None = None,
    model: str | None = None,
    claude_md: str = "You are a helpful agent.",
    env: dict[str, str] | None = None,
) -> Path:
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    (root / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    settings: dict[str, Any] = {}
    if model:
        settings["model"] = model
    (root / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    if mcp:
        servers = {
            sid: {"command": "npx", "args": [], **({"env": env} if env else {})} for sid in mcp
        }
        (root / ".mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    return root


def test_verify_normal_exit0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["verify", str(_repo(tmp_path, claude_md="You review PRs.")), "--format", "json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_verify_required_missing_exit1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["verify", str(_repo(tmp_path)), "--require", "media.transcode", "--format", "json"])
    assert rc == 1
    assert "required_missing" in json.loads(capsys.readouterr().out)["violations"]


def test_verify_missing_repo_exit2(tmp_path: Path) -> None:
    assert main(["verify", str(tmp_path / "nope"), "--format", "json"]) == 2


def test_verify_env_value_not_leaked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """5b: .mcp.json env 값(시크릿)이 IR·출력·로그 어디에도 나타나지 않는다."""
    repo = _repo(tmp_path, mcp=["github-mcp"], env={"SECRET_TOKEN": "sk-super-secret-123"})
    main(["verify", str(repo), "--format", "json"])
    captured = capsys.readouterr()
    assert "sk-super-secret-123" not in captured.out
    assert "sk-super-secret-123" not in captured.err


def test_verify_cursor_loss_reports_model(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Cursor 는 model 지정 네이티브 대응이 없다 → 손실 리포트에 model.name 이 뜬다(matrix 정합)."""
    repo = _repo(tmp_path, model="claude-sonnet-5")
    main(["verify", str(repo), "--target", "cursor", "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    feats = [lo["feature"] for lo in out["findings"].get("portability_loss", [])]
    assert "model.name" in feats
