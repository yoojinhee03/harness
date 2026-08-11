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
    McpServerSpec,
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
            ResolvedComponent(
                id="gh", type="mcp", version="1.4.0", name="GitHub", config={"repo_filter": "*"},
                mcp=McpServerSpec(transport="http", url="https://mcp.example/gh"),
            ),
        ],
        hook_plan={"before_tool_call": [step("secret-scan", blocking=True)]},
        model=ModelConfig(name="claude-sonnet-5", max_tokens=1000, temperature=0.1),
    )
    built = build_request(resolved, "이 PR 리뷰해줘")
    assert built.model == "claude-sonnet-5"
    assert "컨벤션" in built.system and "PR 리뷰" in built.system
    # 원격(URL) MCP 서버는 API 커넥터 형태로 실린다.
    assert [m["name"] for m in built.mcp_servers] == ["gh"]
    assert built.mcp_servers[0] == {"type": "url", "url": "https://mcp.example/gh", "name": "gh"}
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


def test_build_request_omits_stdio_mcp_from_api():
    """stdio MCP 서버는 API 로 못 띄우므로 요청 mcp_servers 에서 제외된다(eject 몫)."""
    resolved = make_resolved(
        components=[
            ResolvedComponent(
                id="gh", type="mcp", version="1.4.0", name="GitHub",
                mcp=McpServerSpec(transport="stdio", command="npx", args=["-y", "server-github"]),
            ),
        ]
    )
    assert build_request(resolved, "hi").mcp_servers == []


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


def test_runner_forwards_mcp_servers_via_beta():
    """회귀: 조립된 원격 MCP 서버를 드롭하지 않고 beta 커넥터로 실제 전송한다."""
    captured: dict[str, object] = {}

    class BetaMessages:
        def create(self, **kw):
            captured.update(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], stop_reason="end_turn")

    class PlainMessages:
        def create(self, **kw):  # mcp 없을 때만 여기로 와야 함
            captured["_plain"] = True
            return SimpleNamespace(content=[], stop_reason=None)

    fake = SimpleNamespace(messages=PlainMessages(), beta=SimpleNamespace(messages=BetaMessages()))
    resolved = make_resolved(
        components=[
            ResolvedComponent(
                id="gh", type="mcp", version="1.4.0", name="GitHub",
                mcp=McpServerSpec(transport="http", url="https://mcp.example/gh"),
            )
        ]
    )
    result = AnthropicRunner(client=fake).run(build_request(resolved, "hi"))
    assert result.text == "ok"
    assert "_plain" not in captured  # 원격 MCP 있으면 beta 경로로 갔어야 함
    assert captured["mcp_servers"] == [{"type": "url", "url": "https://mcp.example/gh", "name": "gh"}]
    assert captured["betas"] == ["mcp-client-2025-04-04"]


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


def test_modify_hook_accepts_falsy_payload():
    """회귀: 0/1 같은 falsy 페이로드도 변형으로 반영돼야 한다(이전엔 0==False 로 삼켜짐)."""
    engine = HookEngine(
        make_resolved(hook_plan={"before_tool_call": [step("zero", can_modify_request=True)]})
    )
    engine.register("zero", lambda _p: 0)  # 정수 0 을 변형 결과로 반환
    out = engine.run("before_tool_call", {"x": 1})
    assert out.allowed is True
    assert out.payload == 0  # 삼켜지지 않고 그대로 반영
    assert any("변형" in n and "무시" not in n for n in out.notes)


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


def test_timeout_returns_at_bound_not_after_handler():
    """회귀: timeout 은 핸들러 종료까지 블록하지 않고 상한 시각에 반환해야 한다.

    이전 구현은 `with ThreadPoolExecutor()` 의 `shutdown(wait=True)` 때문에 timeout 후에도
    핸들러(여기선 1.0s)가 끝날 때까지 벽시계로 블록됐다. 상한(50ms)에 반환하는지 벽시계로 확인.
    """
    engine = HookEngine(
        make_resolved(
            hook_plan={"before_tool_call": [step("hang", sandbox="restricted", failure="fail_open", timeout_ms=50)]}
        )
    )
    engine.register("hang", lambda _p: time.sleep(1.0))
    start = time.monotonic()
    out = engine.run("before_tool_call", {})
    elapsed = time.monotonic() - start
    assert out.allowed is True
    assert elapsed < 0.5  # 핸들러 1.0s 를 다 기다리면 실패 — 상한에 반환됐음을 보장
