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


# ── 피드백 루프 (Phase 9) ──


def test_feedback_disabled_by_default(client):
    """옵트인 꺼짐이 기본 — 켜지 않으면 아무것도 기록하지 않는다."""
    r = client.post("/feedback", json={"selected": ["github-mcp"], "dropped": ["slack-mcp"]})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False and body["recorded"] == 0
    assert client.get("/feedback/top").json()["enabled"] is False


def test_feedback_records_when_enabled(client, monkeypatch):
    monkeypatch.setenv("HARNESS_FEEDBACK", "on")
    r = client.post(
        "/feedback", json={"selected": ["github-mcp", "pr-review-skill"], "dropped": ["slack-mcp"]}
    )
    assert r.json() == {"ok": True, "recorded": 3, "enabled": True}
    top = {i["component_id"]: i for i in client.get("/feedback/top").json()["items"]}
    assert top["github-mcp"]["selected"] >= 1
    assert top["slack-mcp"]["dropped"] >= 1


def test_eject_records_selected_when_enabled(client, monkeypatch):
    """eject 는 '실제로 런타임에 가져간다' 는 가장 강한 확정 신호다."""
    monkeypatch.setenv("HARNESS_FEEDBACK", "on")
    body = {"metadata": {"id": "fb-bot"}, "components": [{"ref": "coding-convention-ctx@1.0.0"}]}
    assert client.post("/eject", json=body, params={"target": "claude-code"}).json()["ok"] is True
    top = {i["component_id"]: i for i in client.get("/feedback/top").json()["items"]}
    assert top["coding-convention-ctx"]["selected"] >= 1


def test_eject_records_nothing_when_disabled(client):
    """옵트인 꺼짐이면 eject 도 아무것도 남기지 않는다."""
    body = {"metadata": {"id": "fb-off"}, "components": [{"ref": "notion-mcp@1.2.0"}]}
    client.post("/eject", json=body, params={"target": "claude-code"})
    assert client.get("/feedback/top").json() == {"enabled": False, "items": []}


def test_recommendation_unchanged_without_feedback(client):
    """신호가 없으면 추천 점수가 피드백 도입 이전과 같아야 한다(조용한 품질 변화 금지)."""
    a = client.post("/recommend", json={"description": PR_BOT, "top_k": 4}).json()
    b = client.post("/recommend", json={"description": PR_BOT, "top_k": 4}).json()
    assert [(r["id"], r["score"]) for r in a["recommendations"]] == [
        (r["id"], r["score"]) for r in b["recommendations"]
    ]


# ── 정책 as code (Phase 8) ──

POLICY_HARNESS = {
    "metadata": {"id": "policy-bot"},
    "components": [{"ref": "github-mcp@1.4.0"}, {"ref": "pr-review-skill@2.1.0"}],
}
GUARDRAIL_POLICY = {"require": {"capabilities": ["lifecycle.guardrail"]}}


def test_policy_absent_keeps_existing_behavior(client):
    """정책 필드가 없으면 기존 응답과 완전히 같아야 한다(도입만으로 동작이 바뀌면 안 된다)."""
    a = client.post("/resolve", json=POLICY_HARNESS).json()
    b = client.post("/resolve", json={**POLICY_HARNESS, "policy": None}).json()
    assert a == b
    assert a["ok"] is True


def test_policy_blocks_resolve(client):
    body = client.post("/resolve", json={**POLICY_HARNESS, "policy": GUARDRAIL_POLICY}).json()
    assert body["ok"] is False
    viol = [d for d in body["diagnostics"]["items"] if d["code"] == "policy_violation"]
    assert viol and viol[0]["detail"]["rule"] == "require.capabilities"


def test_policy_satisfied_passes(client):
    body = client.post(
        "/resolve",
        json={
            **POLICY_HARNESS,
            "components": [*POLICY_HARNESS["components"], {"ref": "secret-scan-hook@1.2.0"}],
            "policy": GUARDRAIL_POLICY,
        },
    ).json()
    assert body["ok"] is True


@pytest.mark.parametrize("path", ["/generate", "/eject", "/preview"])
def test_policy_enforced_on_every_endpoint_using_the_body(client, path):
    """정책을 /resolve 에서만 막고 다른 경로가 무시하면 우회 가능하다 — 전부 막혀야 한다."""
    r = client.post(path, json={**POLICY_HARNESS, "policy": GUARDRAIL_POLICY})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_policy_enforced_on_run(client):
    """/run 도 마찬가지 — 여기가 뚫리면 정책을 걸어도 그냥 실행된다."""
    body = client.post(
        "/run", json={**POLICY_HARNESS, "message": "리뷰해줘", "policy": GUARDRAIL_POLICY}
    ).json()
    assert body["ok"] is False and body["run"] is None


def test_policy_rejects_unknown_key(client):
    """오타를 삼키면 '정책을 걸었다고 믿는데 안 걸린' 최악의 실패가 된다 → 422."""
    r = client.post("/resolve", json={**POLICY_HARNESS, "policy": {"require": {"capabilties": []}}})
    assert r.status_code == 422


PREVIEW_BODY = {
    "metadata": {"id": "pr-bot"},
    "permissions": {"vcs.code-hosting": "read-only"},
    "components": [
        {"ref": "github-mcp@1.4.0"},
        {"ref": "pr-review-skill@2.1.0"},
        {"ref": "secret-scan-hook@1.2.0"},
    ],
    "prompt": {"system": [{"inline": "너는 시니어 리뷰어다."}]},
}


def test_preview_decomposes_without_calling_model(client):
    """POST /preview — 조립 분해(프롬프트 조각·MCP·훅·예산). 모델 호출 없음."""
    r = client.post("/preview", json=PREVIEW_BODY)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["context_budget"]["used"] > 0
    assert sum(c["context_tokens"] for c in body["components"]) == body["context_budget"]["used"]
    assert [s["source"] for s in body["prompt_sections"]][0] == "inline"
    assert body["hooks"]["before_tool_call"][0]["id"] == "secret-scan-hook"
    assert body["eject_files"] is None  # target 미지정이면 방출 미리보기 없음


def test_preview_with_eject_target_includes_file_tree(client):
    body = client.post("/preview", json=PREVIEW_BODY, params={"target": "claude-code"}).json()
    assert body["eject_target"] == "claude-code"
    assert "CLAUDE.md" in body["eject_files"]


def test_preview_rejects_unknown_target(client):
    r = client.post("/preview", json=PREVIEW_BODY, params={"target": "nope"})
    assert r.status_code == 400


def test_preview_surfaces_resolver_diagnostics(client):
    """예산을 조이면 리졸버 경고가 그대로 실려 나온다(프리뷰가 재계산하지 않는다)."""
    body = client.post(
        "/preview", json={**PREVIEW_BODY, "budget": {"context_tokens": 10, "added_tools": 1}}
    ).json()
    assert "token_budget_exceeded" in {d["code"] for d in body["diagnostics"]}
    assert body["context_budget"]["used"] > body["context_budget"]["limit"]


ADOPT_TREE = {
    ".mcp.json": (
        '{"mcpServers": {"github-mcp": {"command": "npx", "args": []}, '
        '"slack-mcp": {"command": "npx", "args": []}}}'
    ),
    "CLAUDE.md": "너는 시니어 코드 리뷰어다.",
}


def test_adopt_endpoint_returns_usable_ir(client):
    """POST /adopt — 네이티브 트리가 편집 가능한 harness.yaml IR 로 돌아온다(온보딩 진입점)."""
    r = client.post("/adopt", json={"files": ADOPT_TREE, "harness_id": "my-bot"})
    assert r.status_code == 200
    body = r.json()
    assert "github-mcp" in body["yaml"] and "slack-mcp" in body["yaml"]
    assert body["config"]["metadata"]["id"] == "my-bot"
    assert "너는 시니어 코드 리뷰어다." in body["yaml"]  # CLAUDE.md 본문이 inline prompt 로 보존
    assert body["ok"] is True and body["errors"] == 0


def test_adopt_result_round_trips_through_resolve(client):
    """adopt 산출 config 가 그대로 /resolve 를 통과해야 한다 — 안 그러면 온보딩이 끊긴다."""
    config = client.post("/adopt", json={"files": ADOPT_TREE}).json()["config"]
    r = client.post("/resolve", json=config)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_adopt_preserves_unknown_without_inventing(client):
    """카탈로그에 없는 서버는 unknown 으로 보존만 한다 — 비슷한 걸로 지어내면 안 된다(환각 금지)."""
    files = {".mcp.json": '{"mcpServers": {"weird-unknown-mcp": {"command": "npx", "args": []}}}'}
    body = client.post("/adopt", json={"files": files}).json()
    assert body["unknown_mcp"] == ["weird-unknown-mcp"]
    assert "weird-unknown-mcp" not in body["yaml"]  # ref 로 승격되지 않는다
    assert body["config"].get("components", []) == []


def test_adopt_endpoint_records_cooccurrence(client):
    """adopt 로 해소된 조합은 '실제로 함께 쓰이던' 관측이라 공출현에 기록된다(백로그 #2 데이터)."""
    from harness_api.cooccurrence import CooccurrenceStore

    client.post("/adopt", json={"files": ADOPT_TREE})
    pairs = {tuple(p["pair"]) for p in CooccurrenceStore(app.state.engine).top()}
    assert ("github-mcp", "slack-mcp") in pairs


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
