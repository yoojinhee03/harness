"""API 관통 테스트 — 화면 A→B→C→생성 경로를 실제 시드 카탈로그로 검증."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from harness_api.main import app

PR_BOT = "PR 자동 리뷰 봇: 코드 리뷰 코멘트 자동화, 팀 코딩 컨벤션 준수, 보안 시크릿 스캔."


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # lifespan 이 카탈로그 로드
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["catalog_size"] == 13  # 시드 10 + 프롬프트 조각 3


def test_catalog_list_and_filter(client):
    assert len(client.get("/catalog").json()) == 13
    mcp = client.get("/catalog", params={"type": "mcp"}).json()
    ids = {c["id"] for c in mcp}
    assert "github-mcp" in ids and len(ids) >= 4  # github·web-search·slack·notion
    hosting = client.get("/catalog", params={"capability": "vcs.code-hosting"}).json()
    assert [c["id"] for c in hosting] == ["github-mcp"]


def test_catalog_detail_404(client):
    assert client.get("/catalog/nope").status_code == 404


def test_recommend(client):
    r = client.post("/recommend", json={"description": PR_BOT, "top_k": 4})
    assert r.status_code == 200
    data = r.json()
    ids = {rec["id"] for rec in data["recommendations"]}
    assert {"github-mcp", "pr-review-skill", "secret-scan-hook"} <= ids
    assert data["extraction_mode"] == "heuristic"


def test_resolve_success(client):
    body = {
        "metadata": {"id": "pr-review-bot", "name": "PR 봇"},
        "permissions": {"vcs.code-hosting": "read-only"},
        "components": [
            {"ref": "github-mcp@1.4.0"},
            {"ref": "pr-review-skill@2.1.0"},
            {"ref": "coding-convention-ctx@1.0.0"},
            {"ref": "secret-scan-hook@1.2.0"},
        ],
    }
    r = client.post("/resolve", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["resolved"]["cost"]["context_tokens"] == 3000


def test_resolve_gap(client):
    body = {
        "metadata": {"id": "pr-review-bot"},
        "components": [{"ref": "pr-review-skill@2.1.0"}],
    }
    data = client.post("/resolve", json=body).json()
    assert data["ok"] is True  # gap 은 에러 아님
    gap_caps = {g["capability"] for g in data["diagnostics"]["items"] if g["severity"] == "gap"}
    assert gap_caps == {"vcs.code-hosting", "vcs.code-review"}


def test_run_dry_run(client):
    body = {
        "metadata": {"id": "pr-review-bot"},
        "message": "이 PR 리뷰해줘",  # 사용자 메시지(시스템 prompt 블록과 분리된 필드)
        "components": [
            {"ref": "github-mcp@1.4.0"},
            {"ref": "pr-review-skill@2.1.0"},
            {"ref": "secret-scan-hook@1.2.0"},
        ],
    }
    data = client.post("/run", json=body).json()
    assert data["ok"] is True
    assert data["built"]["mcp_servers"] == ["github-mcp"]
    assert data["built"]["hook_plan"]["before_tool_call"] == ["secret-scan-hook"]
    # 키 없는 환경 → dry_run
    assert data["run"]["dry_run"] is True


def test_resolve_with_prompt_block(client):
    """prompt 블록(authored 레이어 + 변수)이 resolve 응답의 합성 프롬프트에 반영된다 (Phase 10)."""
    body = {
        "metadata": {"id": "pr-review-bot"},
        "components": [{"ref": "coding-convention-ctx@1.0.0"}],
        "prompt": {
            "system": [{"inline": "너는 시니어 리뷰어다. 스타일은 {{style}}."}],
            "variables": {"style": {"default": "google"}},
        },
    }
    data = client.post("/resolve", json=body).json()
    assert data["ok"] is True
    p = data["resolved"]["prompt"]
    assert p["hash"].startswith("sha256:")
    # authored inline(변수 치환) 이 맨 앞, 그다음 컴포넌트 기여
    assert p["system_text"].startswith("너는 시니어 리뷰어다. 스타일은 google.")
    assert p["segments"][0]["source"] == "inline"
    assert p["segments"][1]["source"] == "component:coding-convention-ctx"


def test_run_rejects_missing_message(client):
    """message 는 필수 — 빠지면 422."""
    body = {"metadata": {"id": "x"}, "components": [{"ref": "github-mcp@1.4.0"}]}
    assert client.post("/run", json=body).status_code == 422


def test_generate_yaml(client):
    body = {
        "metadata": {"id": "pr-review-bot", "name": "PR 봇", "version": "0.3.0"},
        "components": [{"ref": "github-mcp@1.4.0", "config": {"repo_filter": "myorg/*"}}],
    }
    data = client.post("/generate", json=body).json()
    assert "apiVersion: harness/v1" in data["yaml"]
    assert "github-mcp@1.4.0" in data["yaml"]
    assert data["ok"] is True


def test_eject_claude_code(client):
    """resolve → eject: ResolvedHarness 를 Claude Code 파일 트리로 컴파일 (Phase 5)."""
    body = {
        "metadata": {"id": "pr-bot"},
        "components": [{"ref": "github-mcp@1.4.0"}],
        "prompt": {"system": [{"inline": "너는 시니어 리뷰어다."}]},
    }
    data = client.post("/eject", params={"target": "claude-code"}, json=body).json()
    assert data["ok"] is True
    files = data["files"]
    assert set(files) == {"CLAUDE.md", ".mcp.json", ".claude/settings.json"}
    assert "너는 시니어 리뷰어다." in files["CLAUDE.md"]
    settings = json.loads(files[".claude/settings.json"])
    assert settings["permissions"]["allow"] == ["mcp__github-mcp"]


def test_eject_unknown_target_400(client):
    body = {"metadata": {"id": "x"}, "components": [{"ref": "github-mcp@1.4.0"}]}
    r = client.post("/eject", params={"target": "cursor"}, json=body)
    assert r.status_code == 400


def test_generate_yaml_includes_prompt_block(client):
    """prompt 블록이 harness.yaml 로 라운드트립된다 (authored 레이어·변수 보존)."""
    body = {
        "metadata": {"id": "pr-review-bot"},
        "components": [{"ref": "github-mcp@1.4.0"}],
        "prompt": {"system": [{"inline": "너는 시니어 리뷰어다."}]},
    }
    data = client.post("/generate", json=body).json()
    assert "prompt:" in data["yaml"]
    assert "너는 시니어 리뷰어다." in data["yaml"]
