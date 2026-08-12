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


def test_observability_ready_metrics_request_id(client):
    """관측성 — 준비도(DB)·Prometheus 메트릭·요청 ID 헤더."""
    h = client.get("/health")
    assert any(k.lower() == "x-request-id" for k in h.headers)  # 요청 ID 전파
    assert client.get("/ready").json()["ready"] is True  # DB 연결 OK
    m = client.get("/metrics")
    assert m.status_code == 200 and "harness_http_requests_total" in m.text


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
    # github-mcp 은 stdio 서버라 Messages API 로 전송 불가(원격 URL 만 지원) → API 요청엔 안 실린다.
    # (그 서버 정의는 eject → .mcp.json 으로 나가 클라이언트 런타임이 소비한다.)
    assert data["built"]["mcp_servers"] == []
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


def test_key_status_read_only(client):
    """키는 배포 env 로만 설정. 화면엔 상태(설정 여부·품질 모드)만 노출하고 런타임 변조는 없다
    (구설계의 전역 os.environ 변조 = 멀티테넌시 누수를 제거)."""
    st = client.get("/settings/keys").json()
    assert st["anthropic"]["set"] is False and st["voyage"]["set"] is False  # 테스트 env 에 키 없음
    assert st["quality_mode"]["ranker"] in ("heuristic", "claude")
    assert st["quality_mode"]["embedder"] in ("local", "voyage")
    # 런타임 변조 엔드포인트는 제거됨
    assert client.put("/settings/keys", json={"anthropic_api_key": "x"}).status_code in (404, 405)
    assert client.delete("/settings/keys/anthropic").status_code in (404, 405)


def test_verify_reports_unset(client):
    assert client.post("/settings/keys/verify").json()["anthropic"] == "unset"


def test_eject_targets_lists_supported(client):
    """프론트 타깃 셀렉터용 — 지원 타깃 목록."""
    targets = client.get("/eject/targets").json()
    assert "claude-code" in targets and "cursor" in targets


def test_eject_cursor_tree(client):
    body = {"metadata": {"id": "x"}, "components": [{"ref": "github-mcp@1.4.0"}]}
    data = client.post("/eject", params={"target": "cursor"}, json=body).json()
    assert data["ok"] is True
    assert ".cursor/rules/harness.mdc" in data["files"]


def test_eject_unknown_target_400(client):
    body = {"metadata": {"id": "x"}, "components": [{"ref": "github-mcp@1.4.0"}]}
    r = client.post("/eject", params={"target": "nonexistent-runtime"}, json=body)
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
