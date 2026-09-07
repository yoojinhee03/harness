"""실행 전 프리뷰 테스트 (Phase 6) — 조립 분해가 실제 실행과 같은 것을 말하는가.

프리뷰의 가치는 정확성 하나다. 여기 보이는 것과 실제로 나가는 것이 다르면 "실행 전에 이해·신뢰"가
거짓말이 된다. 그래서 (1) 분해 수치가 IR·빌더와 일치하고 (2) 경고는 리졸버 것을 그대로 나르며
(3) 모델 호출이 없는지를 고정한다. 픽스처는 인라인 시드로 자립한다(리졸버 테스트 불변식).
"""

from __future__ import annotations

import pytest
from harness_resolver import (
    Budget,
    Component,
    ComponentSelection,
    Cost,
    HarnessConfig,
    HarnessMetadata,
    InMemoryRegistry,
    PromptLayer,
    PromptSpec,
    resolve,
)
from harness_resolver.models import Auth, McpServerSpec
from harness_runtime import build_request, preview


def registry() -> InMemoryRegistry:
    return InMemoryRegistry(
        [
            Component(
                id="github-mcp", type="mcp", name="GitHub", version="1.4.0",
                provides=["vcs.code-hosting"],
                cost=Cost(context_tokens=400, added_tools=8),
                auth=Auth(required=True, type="oauth", scopes=["repo"]),
                mcp=McpServerSpec(transport="stdio", command="npx", args=["-y", "server-github"]),
            ),
            Component(
                id="remote-mcp", type="mcp", name="Remote", version="1.0.0",
                provides=["web.search"],
                cost=Cost(context_tokens=100, added_tools=2),
                mcp=McpServerSpec(transport="http", url="https://example.test/mcp"),
            ),
            Component(
                id="big-ctx", type="context", name="큰 컨텍스트", version="1.0.0",
                provides=["convention.coding"],
                cost=Cost(context_tokens=2000),
                body="컨벤션 본문",
            ),
            Component(
                id="old-skill", type="skill", name="낡은 스킬", version="0.9.0",
                provides=["review.code"], status="deprecated",
                cost=Cost(context_tokens=50),
                body="리뷰 절차",
            ),
            Component(
                id="scan-hook", type="hook", name="스캔 훅", version="1.0.0",
                provides=["lifecycle.guardrail"],
                events=["before_tool_call"], blocking=True, sandbox="restricted",
                failure="fail_closed", timeout_ms=2000,
            ),
        ]
    )


def config(**kw) -> HarnessConfig:
    base = dict(
        metadata=HarnessMetadata(id="pr-bot"),
        permissions={"vcs.code-hosting": "read-only"},
        components=[
            ComponentSelection(ref="github-mcp@1.4.0"),
            ComponentSelection(ref="remote-mcp@1.0.0"),
            ComponentSelection(ref="big-ctx@1.0.0"),
            ComponentSelection(ref="scan-hook@1.0.0"),
        ],
        prompt=PromptSpec(system=[PromptLayer(inline="너는 시니어 리뷰어다.")]),
    )
    return HarnessConfig(**{**base, **kw})


@pytest.fixture
def report():
    return preview(config(), registry())


# ── 분해가 IR·빌더와 일치하는가 ──


def test_component_costs_sum_to_total_and_sort_heaviest_first(report):
    """컴포넌트별 분해의 합이 IR 총량과 같아야 한다 — 다르면 '무엇을 빼야 하나'가 거짓이 된다."""
    assert [c.id for c in report.components][0] == "big-ctx"  # 2000 이 가장 무겁다
    assert sum(c.context_tokens for c in report.components) == report.context_budget.used
    assert report.context_budget.used == 2500  # 400 + 100 + 2000 + 0


def test_share_reflects_contribution(report):
    big = next(c for c in report.components if c.id == "big-ctx")
    assert big.share == pytest.approx(2000 / 2500)


def test_prompt_sections_match_resolved_prompt(report):
    """프롬프트 분해는 리졸버가 합성한 segments 그대로여야 한다(빌더가 쓰는 것과 같은 원본)."""
    resolved = resolve(config(), registry()).resolved
    assert resolved is not None and resolved.prompt is not None
    assert report.prompt_hash == resolved.prompt.hash
    assert report.prompt_chars == len(resolved.prompt.system_text)
    assert [s.source for s in report.prompt_sections] == [s.source for s in resolved.prompt.segments]


def test_mcp_sent_to_api_matches_builder(report):
    """'API 로 전송됨' 표시가 build_request 의 실제 mcp_servers 와 일치해야 한다."""
    resolved = resolve(config(), registry()).resolved
    assert resolved is not None
    built = build_request(resolved, "안녕")
    sent_in_preview = {m.id for m in report.mcp_servers if m.sent_to_api}
    assert sent_in_preview == {m["name"] for m in built.mcp_servers}
    assert sent_in_preview == {"remote-mcp"}  # stdio 는 빠진다


def test_hook_timeline_carries_execution_semantics(report):
    steps = report.hooks["before_tool_call"]
    assert [s.id for s in steps] == ["scan-hook"]
    assert steps[0].blocking is True
    assert steps[0].sandbox == "restricted"
    assert steps[0].timeout_ms == 2000
    assert steps[0].has_command is False  # emit_command 없음 → eject 시 자리표시


def test_auth_marks_unsatisfied_scope():
    """permissions 로 축소값이 안 잡히면 satisfied=False — 실행 전에 보여야 할 결핍이다."""
    r = preview(config(permissions={}), registry())
    gh = next(a for a in r.auth if a.component_id == "github-mcp")
    assert gh.satisfied is False and gh.granted_scope is None

    r2 = preview(config(), registry())
    gh2 = next(a for a in r2.auth if a.component_id == "github-mcp")
    assert gh2.satisfied is True and gh2.granted_scope == "read-only"


# ── 경고는 리졸버 것을 그대로 나른다(재계산 금지) ──


def test_diagnostics_are_passed_through_not_recomputed():
    """프리뷰 진단이 resolve 진단과 **동일**해야 한다. 갈라지면 진실 원천이 둘이 된다."""
    cfg, reg = config(), registry()
    assert preview(cfg, reg).diagnostics == resolve(cfg, reg).diagnostics.items


def test_budget_overflow_surfaces_resolver_warning():
    r = preview(config(budget=Budget(context_tokens=100, added_tools=1)), registry())
    codes = {d.code for d in r.diagnostics}
    assert "token_budget_exceeded" in codes and "tool_budget_exceeded" in codes
    assert r.context_budget.over is True and r.tool_budget.over is True


def test_deprecated_component_flagged_in_both_places():
    """deprecated 는 진단(리졸버)과 컴포넌트 뷰(분해) 양쪽에 나타난다."""
    cfg = config(components=[ComponentSelection(ref="old-skill@0.9.0")])
    r = preview(cfg, registry())
    assert "deprecated" in {d.code for d in r.diagnostics}
    assert next(c for c in r.components if c.id == "old-skill").status == "deprecated"


def test_resolve_failure_still_returns_diagnostics():
    """resolve 가 깨져도 진단은 나와야 한다 — 빈 화면 대신 이유를 보여주는 게 프리뷰의 일이다."""
    r = preview(config(components=[ComponentSelection(ref="nope@1.0.0")]), registry())
    assert r.ok is False
    assert r.diagnostics and r.components == []
    assert any("resolve 실패" in n for n in r.notes)


# ── 해설 노트 ──


def test_notes_explain_stdio_and_empty_tools(report):
    joined = " ".join(report.notes)
    assert "추정치" in joined  # 토큰이 실측이 아님을 밝힌다
    assert "github-mcp" in joined and "eject" in joined  # stdio 는 API 에 안 실림
    assert "tools 목록은 비어" in joined  # 빈 tools 가 '도구 없음'으로 읽히지 않게


def test_note_explains_two_different_token_figures(report):
    """조각 합과 예산은 출처가 다르다(본문 실측 추정 vs 카탈로그 선언값). 나란히 두면 오해라 명시한다."""
    seg = sum(s.tokens for s in report.prompt_sections)
    assert seg and seg != report.context_budget.used  # 실제로 갈리는 픽스처인지 먼저 확인
    assert any("출처가 다릅니다" in n for n in report.notes)


# ── eject 미리보기 연계 ──


def test_eject_preview_included_when_target_given():
    r = preview(config(), registry(), eject_target="claude-code")
    assert r.eject_target == "claude-code"
    assert r.eject_files and any(p.endswith("CLAUDE.md") for p in r.eject_files)


def test_eject_preview_omitted_by_default(report):
    assert report.eject_target is None and report.eject_files is None


def test_unknown_eject_target_raises():
    with pytest.raises(ValueError, match="지원하지 않는"):
        preview(config(), registry(), eject_target="nope")


# ── 무호출 보증 ──


def test_preview_makes_no_model_call(monkeypatch):
    """프리뷰는 모델을 부르지 않는다. 러너가 불리면 실패한다(dry 분해 계약)."""
    import harness_runtime.runner as runner

    def boom(*_a, **_k):
        raise AssertionError("프리뷰가 모델을 호출했다")

    monkeypatch.setattr(runner.AnthropicRunner, "run", boom)
    assert preview(config(), registry()).ok is True
