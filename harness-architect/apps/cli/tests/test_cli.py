"""harness CLI 테스트 (Phase 5) — resolve/eject 가 실제 시드 카탈로그로 관통.

카탈로그는 build_registry() 자동 탐색(옆 폴더 harness-catalog/components)에 기댄다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from harness_cli.main import main

CONFIG = """\
metadata:
  id: cli-test
components:
  - ref: github-mcp@1.4.0
prompt:
  system:
    - inline: "너는 리뷰어다."
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    p = tmp_path / "harness.yaml"
    p.write_text(CONFIG, encoding="utf-8")
    return p


def test_resolve_ok(config_file: Path) -> None:
    assert main(["resolve", str(config_file)]) == 0


def test_eject_writes_claude_code_tree(config_file: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    rc = main(["eject", str(config_file), "--to", "claude-code", "--out", str(out)])
    assert rc == 0

    settings_path = out / ".claude" / "settings.json"
    assert settings_path.exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["model"]  # 채워짐
    assert (out / ".mcp.json").exists()

    claude_md = (out / "CLAUDE.md").read_text(encoding="utf-8")
    assert "너는 리뷰어다." in claude_md  # authored inline 이 합성 프롬프트로


def test_eject_dry_run_writes_nothing(config_file: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    rc = main(["eject", str(config_file), "--to", "claude-code", "--out", str(out), "--dry-run"])
    assert rc == 0
    assert not out.exists()  # dry-run 은 디스크에 쓰지 않는다


def test_eject_unknown_target_rejected(config_file: Path) -> None:
    # argparse choices 로 미지원 타깃은 SystemExit(2).
    with pytest.raises(SystemExit):
        main(["eject", str(config_file), "--to", "cursor"])
