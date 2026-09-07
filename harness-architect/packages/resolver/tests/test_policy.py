"""정책 as code 테스트 (Phase 8) — 조직 규칙을 리졸버가 강제하는가.

핵심 두 가지를 고정한다:
  1. **정책 미지정 시 동작 완전 불변** — 이 기능 도입만으로 기존 레포가 달라지면 안 된다.
  2. **위반은 차단이고 gap 과 구분된다** — gap 은 추천기로 되돌릴 신호, 정책 위반은 생성 차단.
"""

from __future__ import annotations

import pytest
from harness_resolver import (
    Component,
    ComponentSelection,
    HarnessConfig,
    HarnessMetadata,
    InMemoryRegistry,
    Policy,
    PolicyAuth,
    PolicyBudget,
    PolicyForbid,
    PolicyRequire,
    policy_from_document,
    resolve,
)
from harness_resolver.models import Auth, Cost, McpServerSpec
from harness_resolver.policy import matches


def registry() -> InMemoryRegistry:
    return InMemoryRegistry(
        [
            Component(
                id="github-mcp", type="mcp", name="GitHub", version="1.4.0",
                provides=["vcs.code-hosting"], cost=Cost(context_tokens=400, added_tools=12),
                auth=Auth(required=True, type="oauth", scopes=["repo"]),
                mcp=McpServerSpec(transport="stdio", command="npx"),
            ),
            Component(
                id="secret-scan-hook", type="hook", name="시크릿 스캔", version="1.2.0",
                provides=["lifecycle.guardrail"],
                events=["before_tool_call"], blocking=True, sandbox="restricted",
                failure="fail_closed", timeout_ms=2000,
            ),
            Component(
                id="loose-hook", type="hook", name="격리 없는 훅", version="1.0.0",
                provides=["lifecycle.logging"],
                events=["after_response"], sandbox="none",
                failure="fail_open", timeout_ms=1000,
            ),
            Component(
                id="io.github.randomdev/sketchy", type="mcp", name="미검증", version="0.1.0",
                provides=["web.fetch"], cost=Cost(context_tokens=100, added_tools=4),
                mcp=McpServerSpec(transport="stdio", command="npx"),
            ),
            Component(
                id="heavy-ctx", type="context", name="무거운 컨텍스트", version="1.0.0",
                provides=["convention.coding"], cost=Cost(context_tokens=9000), body="본문",
            ),
        ]
    )


def config(refs: list[str], **kw) -> HarnessConfig:
    base = dict(
        metadata=HarnessMetadata(id="bot"),
        components=[ComponentSelection(ref=r) for r in refs],
    )
    return HarnessConfig(**{**base, **kw})


def violations(result) -> dict[str, list]:
    """rule → 위반 목록."""
    out: dict[str, list] = {}
    for d in result.diagnostics.policy_violations:
        out.setdefault(d.detail["rule"], []).append(d)
    return out


# ── 1. 정책 미지정 시 완전 불변 (가장 중요한 회귀 방어) ──


@pytest.mark.parametrize("policy", [None, Policy()])
def test_no_policy_and_empty_policy_change_nothing(policy):
    """None 이든 빈 정책이든 진단이 한 줄도 늘지 않아야 한다."""
    cfg, reg = config(["github-mcp@1.4.0", "secret-scan-hook@1.2.0"]), registry()
    baseline = resolve(cfg, reg)
    withp = resolve(cfg, reg, policy)
    assert withp.ok == baseline.ok
    assert withp.diagnostics.items == baseline.diagnostics.items
    assert withp.diagnostics.policy_violations == []


def test_empty_policy_is_detected_as_empty():
    assert Policy().is_empty
    assert not Policy(require=PolicyRequire(components=["x"])).is_empty


# ── 2. require ──


def test_require_capability_blocks_when_absent():
    p = Policy(require=PolicyRequire(capabilities=["lifecycle.guardrail"]))
    r = resolve(config(["github-mcp@1.4.0"]), registry(), p)
    assert r.ok is False and r.resolved is None  # 차단
    assert "require.capabilities" in violations(r)


def test_require_capability_passes_when_present():
    p = Policy(require=PolicyRequire(capabilities=["lifecycle.guardrail"]))
    r = resolve(config(["github-mcp@1.4.0", "secret-scan-hook@1.2.0"]), registry(), p)
    assert r.ok is True and r.diagnostics.policy_violations == []


def test_require_component_by_id():
    p = Policy(require=PolicyRequire(components=["secret-scan-hook"]))
    assert not resolve(config(["github-mcp@1.4.0"]), registry(), p).ok
    assert resolve(config(["secret-scan-hook@1.2.0"]), registry(), p).ok


# ── 3. forbid ──


def test_forbid_component_exact_id():
    p = Policy(forbid=PolicyForbid(components=["io.github.randomdev/sketchy"]))
    r = resolve(config(["io.github.randomdev/sketchy@0.1.0"]), registry(), p)
    assert not r.ok and "forbid.components" in violations(r)


def test_forbid_component_namespace_glob():
    """연합 레지스트리 네임스페이스 차단 — 미검증 발행자를 통째로 막는 실사용 패턴."""
    p = Policy(forbid=PolicyForbid(components=["io.github.randomdev/*"]))
    r = resolve(config(["io.github.randomdev/sketchy@0.1.0", "github-mcp@1.4.0"]), registry(), p)
    assert not r.ok
    hit = violations(r)["forbid.components"][0]
    assert hit.detail["component_id"] == "io.github.randomdev/sketchy"
    # github-mcp 은 걸리지 않는다(과잉 차단 방지).
    assert len(violations(r)["forbid.components"]) == 1


@pytest.mark.parametrize(
    ("pattern", "cid", "expected"),
    [
        ("a/b", "a/b", True),
        ("a/b", "a/bc", False),  # 접두가 아니라 정확 일치
        ("a/*", "a/b", True),
        ("a/*", "ab/c", False),
        ("*", "anything", True),
    ],
)
def test_matches_is_exact_or_prefix_glob(pattern, cid, expected):
    assert matches(pattern, cid) is expected


def test_forbid_capability_names_the_supplier():
    p = Policy(forbid=PolicyForbid(capabilities=["web.fetch"]))
    r = resolve(config(["io.github.randomdev/sketchy@0.1.0"]), registry(), p)
    hit = violations(r)["forbid.capabilities"][0]
    assert hit.detail["component_id"] == "io.github.randomdev/sketchy"


def test_forbid_unsandboxed_hooks():
    """sandbox=none 훅 차단 — 공유 카탈로그 승격 게이트와 같은 공급망 근거."""
    p = Policy(forbid=PolicyForbid(unsandboxed_hooks=True))
    r = resolve(config(["loose-hook@1.0.0"]), registry(), p)
    assert not r.ok and "forbid.unsandboxed_hooks" in violations(r)
    # 격리된 훅은 통과한다.
    assert resolve(config(["secret-scan-hook@1.2.0"]), registry(), p).ok


# ── 4. budget — 같은 수치라도 누가 정했느냐로 강도가 갈린다 ──


def test_policy_budget_blocks_where_harness_budget_only_warns():
    """harness 자신의 예산 초과는 warning(스스로 정한 목표), 정책 상한 초과는 차단(조직이 정한 선)."""
    cfg = config(["heavy-ctx@1.0.0"])  # 9000 토큰, 기본 harness 예산 8000
    baseline = resolve(cfg, registry())
    assert baseline.ok is True  # warning 일 뿐 차단 아님
    assert "token_budget_exceeded" in {d.code for d in baseline.diagnostics.warnings}

    r = resolve(cfg, registry(), Policy(budget=PolicyBudget(context_tokens=8000)))
    assert r.ok is False and "budget.context_tokens" in violations(r)


def test_policy_budget_none_means_unconstrained():
    r = resolve(config(["heavy-ctx@1.0.0"]), registry(), Policy(budget=PolicyBudget(added_tools=99)))
    assert r.ok is True  # context_tokens 는 None → 제약 없음


def test_policy_budget_added_tools():
    p = Policy(budget=PolicyBudget(added_tools=5))
    r = resolve(config(["github-mcp@1.4.0"]), registry(), p)  # 12개
    assert not r.ok and violations(r)["budget.added_tools"][0].detail["used"] == 12


# ── 5. auth ──


def test_require_narrowed_blocks_unscoped_auth():
    p = Policy(auth=PolicyAuth(require_narrowed=True))
    r = resolve(config(["github-mcp@1.4.0"]), registry(), p)  # permissions 없음
    assert not r.ok and "auth.require_narrowed" in violations(r)

    ok = resolve(
        config(["github-mcp@1.4.0"], permissions={"vcs.code-hosting": "read-only"}), registry(), p
    )
    assert ok.ok is True


def test_allowed_scopes_whitelist():
    p = Policy(auth=PolicyAuth(allowed_scopes=["read-only"]))
    bad = resolve(
        config(["github-mcp@1.4.0"], permissions={"vcs.code-hosting": "write"}), registry(), p
    )
    assert not bad.ok
    assert violations(bad)["auth.allowed_scopes"][0].detail["granted_scope"] == "write"

    good = resolve(
        config(["github-mcp@1.4.0"], permissions={"vcs.code-hosting": "read-only"}), registry(), p
    )
    assert good.ok is True


# ── 6. gap 과의 구분 ──


def test_policy_violation_is_distinct_from_gap():
    """gap 은 진행 가능(추천기로 되돌릴 신호), 정책 위반은 차단. 둘이 섞이면 안 된다."""
    reg = InMemoryRegistry(
        [
            Component(
                id="needy-skill", type="skill", name="의존 스킬", version="1.0.0",
                provides=["review.code"], requires=["vcs.code-hosting"], body="x",
            )
        ]
    )
    cfg = config(["needy-skill@1.0.0"])

    plain = resolve(cfg, reg)
    assert plain.ok is True  # gap 이 있어도 차단은 아니다
    assert plain.diagnostics.gaps and plain.diagnostics.policy_violations == []

    blocked = resolve(cfg, reg, Policy(require=PolicyRequire(components=["secret-scan-hook"])))
    assert blocked.ok is False
    assert blocked.diagnostics.gaps  # gap 은 여전히 보고된다
    assert blocked.diagnostics.policy_violations  # 차단 사유는 정책
    assert all(d.code == "policy_violation" for d in blocked.diagnostics.policy_violations)


# ── 7. 문서 로딩 — 기존 severity 전용 파일과의 하위호환 ──


def test_policy_from_document_ignores_severity_only_file():
    """verify 심각도만 있는 기존 `.harness/policy.yaml` 은 정책 미지정으로 읽혀야 한다."""
    assert policy_from_document({"severity": {"capability_gap": "ignore"}}) is None
    assert policy_from_document({}) is None
    assert policy_from_document(None) is None
    assert policy_from_document("not a dict") is None


def test_policy_from_document_reads_governance_section():
    p = policy_from_document(
        {
            "version": 1,
            "name": "security-baseline",
            "severity": {"capability_gap": "ignore"},  # verify 용 — 정책은 무시한다
            "require": {"capabilities": ["lifecycle.guardrail"]},
            "forbid": {"unsandboxed_hooks": True},
        }
    )
    assert p is not None
    assert p.name == "security-baseline"
    assert p.require.capabilities == ["lifecycle.guardrail"]
    assert p.forbid.unsandboxed_hooks is True


def test_unknown_policy_key_is_rejected():
    """오타를 조용히 삼키면 '정책을 걸었다고 믿는데 안 걸린' 최악의 실패가 된다."""
    with pytest.raises(ValueError):
        policy_from_document({"require": {"capabilties": ["x"]}})  # 오타
