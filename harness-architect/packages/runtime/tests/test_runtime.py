"""Phase 2 — 런타임 실연동 테스트 (네트워크 없이).

요청 조립 · Anthropic 러너(dry_run/fake) · 훅 엔진(sandbox·timeout·권한 강제)을 검증한다.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from harness_resolver import Diagnostics, InMemoryRegistry, compose_prompt
from harness_resolver.models import (
    CostTotals,
    HarnessMetadata,
    HookStep,
    ModelConfig,
    ResolvedComponent,
    ResolvedHarness,
    ResolvedPrompt,
)
from harness_runtime import AnthropicRunner, HookEngine, build_request


def make_resolved(
    *, components=None, hook_plan=None, model=None
) -> ResolvedHarness:
    return ResolvedHarness(
        metadata=HarnessMetadata(id="t"),
        model=model or ModelConfig(),
        permissions={},
        components=components or [],
        provided={},
        hook_plan=hook_plan or {},
        auth_needs=[],
        cost=CostTotals(),
    )


def step(id: str, **kw) -> HookStep:
    base = dict(
        event="before_tool_call",
        blocking=False,
        can_modify_request=False,
        can_modify_response=False,
        sandbox="none",
        failure="fail_open",
        timeout_ms=None,
    )
    base.update(kw)
    return HookStep(id=id, **base)  # type: ignore[arg-type]


# ─────────────────────────── build_request ───────────────────────────


def test_build_request_assembles_system_and_mcp():
    resolved = make_resolved(
        components=[
            ResolvedComponent(
                id="ctx", type="context", version="1.0.0", name="컨벤션",
                config={"style_guide": "google"},
            ),
            ResolvedComponent(id="skill", type="skill", version="2.1.0", name="PR 리뷰", config={}),
            ResolvedComponent(id="gh", type="mcp", version="1.4.0", name="GitHub", config={"repo_filter": "*"}),
        ],
        hook_plan={"before_tool_call": [step("secret-scan", blocking=True)]},
        model=ModelConfig(name="claude-sonnet-5", max_tokens=1000, temperature=0.1),
    )
    built = build_request(resolved, "이 PR 리뷰해줘")
    assert built.model == "claude-sonnet-5"
    assert "컨벤션" in built.system and "PR 리뷰" in built.system
    assert [m["id"] for m in built.mcp_servers] == ["gh"]
    assert built.hook_plan["before_tool_call"] == ["secret-scan"]
    assert built.messages[0]["content"] == "이 PR 리뷰해줘"


def test_build_request_uses_composed_prompt_when_present():
    """prompt(ResolvedPrompt)가 있으면 system 은 그 system_text 를 그대로 쓴다."""
    resolved = make_resolved(
        components=[ResolvedComponent(id="ctx", type="context", version="1.0.0", name="C", config={})]
    )
    resolved.prompt = ResolvedPrompt(system_text="합성된 시스템 프롬프트", hash="sha256:x")
    assert build_request(resolved, "hi").system == "합성된 시스템 프롬프트"


def test_composed_prompt_matches_builder_fallback():
    """compose_prompt(None,…) 결과 == prompt 없는 build_request 폴백 (동치 회귀)."""
    comps = [
        ResolvedComponent(id="ctx", type="context", version="1.0.0", name="컨벤션", config={}),
        ResolvedComponent(id="pr", type="skill", version="2.1.0", name="PR 리뷰", config={}),
    ]
    composed = compose_prompt(None, comps, InMemoryRegistry([]), Diagnostics())

    resolved_fallback = make_resolved(components=comps)  # prompt=None → 폴백 조립
    resolved_composed = make_resolved(components=comps)
    resolved_composed.prompt = composed

    assert build_request(resolved_fallback, "x").system == build_request(resolved_composed, "x").system
    assert build_request(resolved_fallback, "x").system == composed.system_text


# ─────────────────────────── AnthropicRunner ───────────────────────────


def test_runner_dry_run_without_key():
    runner = AnthropicRunner(api_key=None)
    result = runner.run(build_request(make_resolved(), "hi"))
    assert result.dry_run is True
    assert result.text is None


def test_runner_with_fake_client():
    class FakeMessages:
        def create(self, **kw):
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="리뷰 결과입니다")],
                stop_reason="end_turn",
            )

    fake = SimpleNamespace(messages=FakeMessages())
    runner = AnthropicRunner(client=fake)
    result = runner.run(build_request(make_resolved(), "hi"))
    assert result.dry_run is False
    assert result.text == "리뷰 결과입니다"
    assert result.stop_reason == "end_turn"


# ─────────────────────────── HookEngine: 권한 강제 ───────────────────────────


def test_blocking_hook_blocks():
    engine = HookEngine(make_resolved(hook_plan={"before_tool_call": [step("guard", blocking=True)]}))
    engine.register("guard", lambda _p: False)
    out = engine.run("before_tool_call", {"x": 1})
    assert out.allowed is False


def test_non_blocking_block_is_ignored():
    """blocking 미선언 훅이 False 를 반환해도 차단하지 않는다(상한 강제)."""
    engine = HookEngine(make_resolved(hook_plan={"before_tool_call": [step("log", blocking=False)]}))
    engine.register("log", lambda _p: False)
    out = engine.run("before_tool_call", {"x": 1})
    assert out.allowed is True
    assert any("무시" in n for n in out.notes)


def test_modify_hook_transforms_payload():
    engine = HookEngine(
        make_resolved(hook_plan={"before_tool_call": [step("redact", can_modify_request=True)]})
    )
    engine.register("redact", lambda p: {**p, "secret": "***"})
    out = engine.run("before_tool_call", {"secret": "abc"})
    assert out.payload["secret"] == "***"


def test_unmodifiable_hook_change_ignored():
    engine = HookEngine(
        make_resolved(hook_plan={"before_tool_call": [step("peek", can_modify_request=False)]})
    )
    engine.register("peek", lambda p: {**p, "secret": "***"})
    out = engine.run("before_tool_call", {"secret": "abc"})
    assert out.payload["secret"] == "abc"  # 변형 무시
    assert any("변형 무시" in n for n in out.notes)


# ─────────────────────────── HookEngine: failure 정책 ───────────────────────────


def test_fail_closed_on_exception_blocks():
    engine = HookEngine(
        make_resolved(hook_plan={"before_tool_call": [step("g", blocking=True, failure="fail_closed")]})
    )

    def boom(_p):
        raise ValueError("터짐")

    engine.register("g", boom)
    out = engine.run("before_tool_call", {})
    assert out.allowed is False


def test_fail_open_on_exception_continues():
    engine = HookEngine(
        make_resolved(hook_plan={"before_tool_call": [step("log", failure="fail_open")]})
    )

    def boom(_p):
        raise ValueError("터짐")

    engine.register("log", boom)
    out = engine.run("before_tool_call", {})
    assert out.allowed is True


# ─────────────────────────── HookEngine: timeout (restricted) ───────────────────────────


def test_timeout_fail_closed_blocks():
    engine = HookEngine(
        make_resolved(
            hook_plan={
                "before_tool_call": [
                    step("slow", sandbox="restricted", blocking=True, failure="fail_closed", timeout_ms=50)
                ]
            }
        )
    )
    engine.register("slow", lambda _p: time.sleep(0.3))
    out = engine.run("before_tool_call", {})
    assert out.allowed is False
    assert any("timeout" in n for n in out.notes)


def test_timeout_fail_open_continues():
    engine = HookEngine(
        make_resolved(
            hook_plan={"before_tool_call": [step("slow", sandbox="restricted", failure="fail_open", timeout_ms=50)]}
        )
    )
    engine.register("slow", lambda _p: time.sleep(0.3))
    out = engine.run("before_tool_call", {})
    assert out.allowed is True
