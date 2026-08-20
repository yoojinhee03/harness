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


def test_catalog_pagination(client):
    # 총계는 X-Total-Count 헤더로, 본문은 현재 페이지만.
    r = client.get("/catalog", params={"limit": 5, "offset": 0})
    assert r.headers["X-Total-Count"] == "13"
    page1 = r.json()
    assert len(page1) == 5
    page2 = client.get("/catalog", params={"limit": 5, "offset": 5}).json()
    assert len(page2) == 5
    # 페이지 경계 안정(정렬) — 겹침 없음.
    assert {c["id"] for c in page1}.isdisjoint({c["id"] for c in page2})
    # 마지막 페이지는 남은 것만.
    tail = client.get("/catalog", params={"limit": 5, "offset": 10}).json()
    assert len(tail) == 3


def test_catalog_search_q(client):
    r = client.get("/catalog", params={"q": "slack"})
    hits = r.json()
    assert [c["id"] for c in hits] == ["slack-mcp"]  # id 부분일치
    # 검색 결과 총계가 헤더에 반영(limit 없음 → 본문=전체).
    assert int(r.headers["X-Total-Count"]) == len(hits)


def test_catalog_detail_404(client):
    assert client.get("/catalog/nope").status_code == 404


def test_catalog_detail_slashed_id_reaches_handler(client):
    # 연합 레지스트리 id 는 `io.github.owner/server` 처럼 슬래시를 포함한다. 라우트가 `:path` 여야
    # 슬래시를 세그먼트로 넘겨 핸들러까지 도달한다(아니면 화면에서 상세 404 → 크래시). 없는 id 라도
    # 핸들러의 404(전체 id 포함)면 라우팅이 맞은 것 — Starlette 기본 'Not Found' 와 구분된다.
    slashed = "io.github.owner/server-name"
    r = client.get(f"/catalog/{slashed}")
    assert r.status_code == 404
    assert slashed in r.json()["detail"]


def test_catalog_items_trust_curated(client):
    # 테스트는 로컬 시드만 로드(harvest off) → 전부 손큐레이션 = curated. source 키도 노출.
    items = client.get("/catalog").json()
    assert items and all(it["trust"] == "curated" for it in items)
    assert all("source" in it for it in items)


def test_catalog_exclude_curated(client):
    # 테스트는 시드만 로드 → curated 제외하면 외부 수확분이 없어 빈 목록.
    r = client.get("/catalog", params={"exclude_curated": "true"})
    assert r.json() == []
    assert r.headers["X-Total-Count"] == "0"


def test_catalog_detail_includes_trust(client):
    cid = client.get("/catalog").json()[0]["id"]
    assert client.get(f"/catalog/{cid}").json()["trust"] == "curated"


def test_catalog_item_trust_defaults_community():
    # 외부 수확분은 community 가 기본 — from_component 에 명시해야 등급이 바뀐다.
    from harness_api.schemas import CatalogItem
    from harness_resolver import Component

    c = Component(id="io.github.x/y", type="mcp", name="Y", version="1.0.0")
    assert CatalogItem.from_component(c).trust == "community"
    assert CatalogItem.from_component(c, trust="official").trust == "official"


def test_trust_tiers():
    from harness_api.main import _trust

    curated = {"pr-review-skill"}
    origins = {
        "box": "marketplace",
        "io.github.modelcontextprotocol/servers": "registry",
        "io.github.randomdev/thing": "registry",
    }
    assert _trust("pr-review-skill", curated, origins) == "curated"
    assert _trust("box", curated, origins) == "official"  # 공식 마켓플레이스
    assert _trust("io.github.modelcontextprotocol/servers", curated, origins) == "official"  # 신뢰 ns
    assert _trust("io.github.randomdev/thing", curated, origins) == "community"  # 임의 발행자


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


def test_verify_endpoint_clean(client):
    """POST /verify — 프롬프트만 있는 트리는 통과(ok). CLI 와 같은 verify 코어."""
    r = client.post("/verify", json={"files": {"CLAUDE.md": "You review PRs."}})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_verify_endpoint_required_missing_violation(client):
    r = client.post(
        "/verify", json={"files": {"CLAUDE.md": "x"}, "require": ["media.transcode"]}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "required_missing" in body["violations"]


def test_verify_endpoint_records_cooccurrence(client):
    """MCP 2개 트리 → 공출현이 DB 에 기록된다(TASK 5e durable)."""
    files = {
        ".mcp.json": (
            '{"mcpServers": {"github-mcp": {"command": "npx", "args": []}, '
            '"slack-mcp": {"command": "npx", "args": []}}}'
        )
    }
    r = client.post("/verify", json={"files": files})
    assert r.status_code == 200
    from harness_api.cooccurrence import CooccurrenceStore

    pairs = {tuple(p["pair"]) for p in CooccurrenceStore(app.state.engine).top()}
    assert ("github-mcp", "slack-mcp") in pairs
