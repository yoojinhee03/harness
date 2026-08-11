"""리졸버 테스트 — 자체 완결형(카탈로그 자산 비의존).

카탈로그 시드 셋(PR 리뷰 봇 경로)의 리졸브 트레이스와 gap 데모를 코드 내 픽스처로 재현한다.
설계: 리졸버 검증 로직 §2·§3, 카탈로그 시드 셋 문서의 성공/gap 케이스.
"""

from __future__ import annotations

import pytest
from harness_resolver import (
    Auth,
    Budget,
    Component,
    ComponentSelection,
    Cost,
    HarnessConfig,
    HarnessMetadata,
    InMemoryRegistry,
    ModelConfig,
    resolve,
)

# ─────────────────────────── 픽스처: 시드 4 컴포넌트 ───────────────────────────


def github_mcp() -> Component:
    return Component(
        id="github-mcp",
        type="mcp",
        name="GitHub",
        version="1.4.0",
        status="stable",
        summary="GitHub 저장소·이슈·PR 접근",
        use_when=["코드 리뷰나 PR 관련 작업이 필요할 때"],
        capability_tags=["vcs.code-hosting", "vcs.issue-tracking", "vcs.code-review"],
        cost=Cost(context_tokens=0, added_tools=12, latency="medium"),
        provides=["vcs.code-hosting", "vcs.issue-tracking", "vcs.code-review"],
        conflicts_with=["gitlab-mcp"],
        constraints={"exclusive_group": "vcs"},
        auth=Auth(required=True, type="oauth", scopes=["repo:read"]),
        config_schema={"type": "object", "properties": {"repo_filter": {"type": "string"}}},
        defaults={"repo_filter": "*"},
    )


def pr_review_skill() -> Component:
    return Component(
        id="pr-review-skill",
        type="skill",
        name="PR 리뷰 절차",
        version="2.1.0",
        summary="PR diff를 받아 구조화된 리뷰 코멘트를 생성",
        capability_tags=["review.code"],
        cost=Cost(context_tokens=1800, added_tools=0, latency="low"),
        provides=["review.code"],
        requires=["vcs.code-hosting", "vcs.code-review"],
        entrypoint="skills/pr-review/SKILL.md",
        injection_mode="context",
    )


def coding_convention_ctx() -> Component:
    return Component(
        id="coding-convention-ctx",
        type="context",
        name="코딩 컨벤션",
        version="1.0.0",
        summary="팀 코딩 스타일 가이드를 컨텍스트로 주입",
        capability_tags=["convention.coding"],
        cost=Cost(context_tokens=1200, added_tools=0, latency="low"),
        provides=["convention.coding"],
        source="file",
        size_estimate=1200,
        refresh="static",
        config_schema={
            "type": "object",
            "properties": {"style_guide": {"type": "string", "enum": ["google", "airbnb", "pep8"]}},
        },
        defaults={"style_guide": "google"},
    )


def secret_scan_hook() -> Component:
    return Component(
        id="secret-scan-hook",
        type="hook",
        name="시크릿 스캔 가드레일",
        version="1.2.0",
        summary="도구 호출 전 노출된 자격증명·비밀을 차단",
        capability_tags=["lifecycle.guardrail"],
        cost=Cost(context_tokens=0, added_tools=0, latency="low"),
        provides=["lifecycle.guardrail"],
        events=["before_tool_call"],
        sandbox="restricted",
        blocking=True,
        failure="fail_closed",
        timeout_ms=2000,
    )


@pytest.fixture
def registry() -> InMemoryRegistry:
    return InMemoryRegistry(
        [github_mcp(), pr_review_skill(), coding_convention_ctx(), secret_scan_hook()]
    )


def pr_bot_config(refs: list[str] | None = None) -> HarnessConfig:
    """harness.yaml 스펙 §2 의 PR 리뷰 봇 설정."""
    refs = refs or [
        "github-mcp@1.4.0",
        "pr-review-skill@2.1.0",
        "coding-convention-ctx@1.0.0",
        "secret-scan-hook@1.2.0",
    ]
    return HarnessConfig(
        metadata=HarnessMetadata(id="pr-review-bot", name="PR 자동 리뷰 봇", version="0.3.0"),
        permissions={"vcs.code-hosting": "read-only"},
        components=[ComponentSelection(ref=r) for r in refs],
        budget=Budget(context_tokens=8000, added_tools=30),
    )


# ─────────────────────────── 성공 트레이스 ───────────────────────────


def test_success_trace(registry: InMemoryRegistry) -> None:
    result = resolve(pr_bot_config(), registry)

    assert result.ok is True
    assert result.resolved is not None
    assert result.diagnostics.errors == []
    assert result.diagnostics.gaps == []

    r = result.resolved
    # 능력 공급 맵
    assert r.provided["vcs.code-hosting"] == ["github-mcp"]
    assert r.provided["review.code"] == ["pr-review-skill"]
    assert r.provided["convention.coding"] == ["coding-convention-ctx"]
    assert r.provided["lifecycle.guardrail"] == ["secret-scan-hook"]
    # 비용: 1800 + 1200 = 3000 < 8000, 도구 12 < 30
    assert r.cost.context_tokens == 3000
    assert r.cost.added_tools == 12
    # 훅 계획: before_tool_call 에 secret-scan-hook
    assert [s.id for s in r.hook_plan["before_tool_call"]] == ["secret-scan-hook"]
    # 권한: github oauth, permissions 로 read-only 축소 표면화
    gh_auth = next(a for a in r.auth_needs if a.component_id == "github-mcp")
    assert gh_auth.granted_scope == "read-only"
    # config: defaults 병합
    gh = next(c for c in r.components if c.id == "github-mcp")
    assert gh.config["repo_filter"] == "*"


# ─────────────────────────── gap 데모 (화면 C→B) ───────────────────────────


def test_gap_when_github_removed(registry: InMemoryRegistry) -> None:
    """github-mcp 를 빼면 pr-review-skill 의 requires 가 gap 으로 뜬다."""
    config = pr_bot_config(
        refs=["pr-review-skill@2.1.0", "coding-convention-ctx@1.0.0", "secret-scan-hook@1.2.0"]
    )
    result = resolve(config, registry)

    # gap 은 하드 에러가 아니다 — 여전히 ok(생성 차단 없음), 추천기로 되돌릴 신호만 남김
    assert result.ok is True
    gap_caps = {g.capability for g in result.diagnostics.gaps}
    assert gap_caps == {"vcs.code-hosting", "vcs.code-review"}
    assert all(g.component_id == "pr-review-skill" for g in result.diagnostics.gaps)


# ─────────────────────────── 충돌 ───────────────────────────


def test_exclusive_group_and_conflict(registry: InMemoryRegistry) -> None:
    registry.add(
        Component(
            id="gitlab-mcp",
            type="mcp",
            name="GitLab",
            version="1.0.0",
            provides=["vcs.code-hosting"],
            constraints={"exclusive_group": "vcs"},
        )
    )
    config = pr_bot_config(refs=["github-mcp@1.4.0", "gitlab-mcp@1.0.0"])
    result = resolve(config, registry)

    assert result.ok is False
    codes = {d.code for d in result.diagnostics.errors}
    assert "exclusive_conflict" in codes  # 같은 vcs 그룹 둘
    assert "conflict" in codes  # github.conflicts_with = [gitlab-mcp]


# ─────────────────────────── 미지 컴포넌트 / 버전 불일치 ───────────────────────────


def test_unknown_component(registry: InMemoryRegistry) -> None:
    config = pr_bot_config(refs=["nonexistent-mcp@9.9.9"])
    result = resolve(config, registry)
    assert result.ok is False
    assert any(d.code == "unknown_component" for d in result.diagnostics.errors)


def test_version_mismatch_is_unknown(registry: InMemoryRegistry) -> None:
    config = pr_bot_config(refs=["github-mcp@9.9.9"])
    result = resolve(config, registry)
    assert result.ok is False
    assert any(d.code == "unknown_component" for d in result.diagnostics.errors)


def test_version_omitted_picks_latest_stable(registry: InMemoryRegistry) -> None:
    config = pr_bot_config(refs=["github-mcp"])  # 버전 생략
    result = resolve(config, registry)
    assert result.ok is True
    assert result.resolved is not None
    assert result.resolved.components[0].version == "1.4.0"


# ─────────────────────────── deprecated 경고 ───────────────────────────


def test_deprecated_warning(registry: InMemoryRegistry) -> None:
    registry.add(
        Component(
            id="old-mcp",
            type="mcp",
            name="Old",
            version="0.1.0",
            status="deprecated",
            provides=["vcs.code-hosting"],
        )
    )
    config = pr_bot_config(refs=["old-mcp@0.1.0"])
    result = resolve(config, registry)
    assert result.ok is True  # 경고이지 에러 아님
    assert any(d.code == "deprecated" for d in result.diagnostics.warnings)


# ─────────────────────────── 예산 초과 경고 ───────────────────────────


def test_token_budget_exceeded_warning(registry: InMemoryRegistry) -> None:
    config = pr_bot_config()
    config.budget = Budget(context_tokens=1000, added_tools=30)  # 3000 > 1000
    result = resolve(config, registry)
    assert result.ok is True  # 예산 초과는 warning
    assert any(d.code == "token_budget_exceeded" for d in result.diagnostics.warnings)


# ─────────────────────────── config_schema 위반 ───────────────────────────


def test_config_schema_violation(registry: InMemoryRegistry) -> None:
    config = pr_bot_config()
    # coding-convention-ctx 의 style_guide enum 위반
    for sel in config.components:
        if sel.id == "coding-convention-ctx":
            sel.config = {"style_guide": "not-a-valid-guide"}
    result = resolve(config, registry)
    assert result.ok is False
    assert any(d.code == "config_schema_violation" for d in result.diagnostics.errors)


# ─────────────────────────── 훅 순서 (depends_on + blocking) ───────────────────────────


def test_hook_ordering_depends_on_and_blocking() -> None:
    log_hook = Component(
        id="log-hook",
        type="hook",
        name="Logger",
        version="1.0.0",
        provides=["lifecycle.logging"],
        events=["before_tool_call"],
        blocking=False,
        failure="fail_open",
        depends_on=[],
    )
    guard = Component(
        id="guard-hook",
        type="hook",
        name="Guard",
        version="1.0.0",
        provides=["lifecycle.guardrail"],
        events=["before_tool_call"],
        blocking=True,
        failure="fail_closed",
        depends_on=[],
    )
    dependent = Component(
        id="after-guard",
        type="hook",
        name="AfterGuard",
        version="1.0.0",
        provides=["lifecycle.transform"],
        events=["before_tool_call"],
        blocking=False,
        depends_on=["guard-hook"],  # guard 뒤에 와야 함
    )
    reg = InMemoryRegistry([log_hook, guard, dependent])
    config = HarnessConfig(
        metadata=HarnessMetadata(id="h"),
        components=[
            ComponentSelection(ref="log-hook@1.0.0"),
            ComponentSelection(ref="guard-hook@1.0.0"),
            ComponentSelection(ref="after-guard@1.0.0"),
        ],
    )
    result = resolve(config, reg)
    assert result.resolved is not None
    order = [s.id for s in result.resolved.hook_plan["before_tool_call"]]
    # blocking(guard) 우선, log 는 등록 순, after-guard 는 guard 뒤(위상정렬)
    assert order.index("guard-hook") < order.index("after-guard")
    assert order.index("guard-hook") < order.index("log-hook")  # blocking 우선


# ─────────────────────────── extends 병합 ───────────────────────────


def test_extends_merges_base_components(registry: InMemoryRegistry) -> None:
    base = HarnessConfig(
        metadata=HarnessMetadata(id="base/code-project"),
        components=[ComponentSelection(ref="secret-scan-hook@1.2.0")],
    )
    reg = InMemoryRegistry(
        [github_mcp(), pr_review_skill(), coding_convention_ctx(), secret_scan_hook()],
        bases={"base/code-project": base},
    )
    child = HarnessConfig(
        metadata=HarnessMetadata(id="pr-review-bot"),
        extends="base/code-project",
        components=[
            ComponentSelection(ref="github-mcp@1.4.0"),
            ComponentSelection(ref="pr-review-skill@2.1.0"),
        ],
    )
    result = resolve(child, reg)
    assert result.ok is True
    assert result.resolved is not None
    ids = {c.id for c in result.resolved.components}
    # 베이스의 secret-scan-hook + 자식의 github/skill 이 합쳐짐
    assert ids == {"secret-scan-hook", "github-mcp", "pr-review-skill"}


def test_extends_preserves_base_model_and_merges_child_fields() -> None:
    """회귀: base.model 이 통째로 폐기되면 안 된다.

    - 자식이 model 을 아예 안 주면 base.model 유지.
    - 자식이 일부 필드만 주면 그 필드만 오버라이드하고 나머지는 base 유지.
    """
    base = HarnessConfig(
        metadata=HarnessMetadata(id="base/m"),
        model=ModelConfig(name="base-model", temperature=0.9, max_tokens=8000),
        components=[],
    )
    reg = InMemoryRegistry([github_mcp()], bases={"base/m": base})

    # ① 자식이 model 미지정 → base.model 그대로
    child_no_model = HarnessConfig(
        metadata=HarnessMetadata(id="c1"), extends="base/m",
        components=[ComponentSelection(ref="github-mcp@1.4.0")],
    )
    r1 = resolve(child_no_model, reg)
    assert r1.ok and r1.resolved is not None
    assert r1.resolved.model.name == "base-model"
    assert r1.resolved.model.temperature == 0.9
    assert r1.resolved.model.max_tokens == 8000

    # ② 자식이 name 만 오버라이드 → name 은 자식, temperature/max_tokens 는 base 유지
    child_partial = HarnessConfig(
        metadata=HarnessMetadata(id="c2"), extends="base/m",
        model=ModelConfig(name="child-model"),
        components=[ComponentSelection(ref="github-mcp@1.4.0")],
    )
    r2 = resolve(child_partial, reg)
    assert r2.ok and r2.resolved is not None
    assert r2.resolved.model.name == "child-model"
    assert r2.resolved.model.temperature == 0.9  # base 에서 보존


def test_unknown_base_warns(registry: InMemoryRegistry) -> None:
    config = pr_bot_config()
    config.extends = "base/does-not-exist"
    result = resolve(config, registry)
    assert any(d.code == "unknown_base" for d in result.diagnostics.warnings)


# ─────────────────────────── permissions 축소 검증 ───────────────────────────


def test_permission_for_unprovided_capability_warns(registry: InMemoryRegistry) -> None:
    config = pr_bot_config()
    config.permissions = {"comms.messaging": "read-only"}  # 아무도 제공 안 함
    result = resolve(config, registry)
    assert any(d.code == "permission_for_unprovided_capability" for d in result.diagnostics.warnings)


# ─────────────────────────── 순수성 (동일 입력 → 동일 출력) ───────────────────────────


def test_pure_function_determinism(registry: InMemoryRegistry) -> None:
    a = resolve(pr_bot_config(), registry)
    b = resolve(pr_bot_config(), registry)
    assert a.model_dump() == b.model_dump()
