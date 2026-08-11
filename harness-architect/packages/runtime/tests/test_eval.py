"""Phase 11 — eval 엔진 테스트 (네트워크 없이).

결정적 채점기 단위 + 주입 클라이언트(fake)로 채점 관통 + 키 없을 때 dry_run 스킵.
"""

from __future__ import annotations

from types import SimpleNamespace

from harness_resolver.models import (
    CostTotals,
    HarnessMetadata,
    ModelConfig,
    ResolvedHarness,
)
from harness_runtime import EvalCase, EvalExpect, check_expectations, run_eval


def make_resolved() -> ResolvedHarness:
    return ResolvedHarness(
        metadata=HarnessMetadata(id="t"),
        model=ModelConfig(),
        permissions={},
        components=[],
        provided={},
        hook_plan={},
        auth_needs=[],
        cost=CostTotals(),
    )


def fake_client(text: str) -> object:
    class Messages:
        def create(self, **_kw):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn")

    return SimpleNamespace(messages=Messages())


# ─────────────────────────── 결정적 채점기 ───────────────────────────


def test_check_expectations_pass_and_fail():
    expect = EvalExpect(contains=["리뷰", "없음"], not_contains=["secret"], regex=[r"\d+/\d+"])
    checks = check_expectations("리뷰 결과: 3/5 통과, 문제 없음", expect)
    by = {(c.kind, c.target): c.passed for c in checks}
    assert by[("contains", "리뷰")] is True
    assert by[("contains", "없음")] is True
    assert by[("not_contains", "secret")] is True
    assert by[("regex", r"\d+/\d+")] is True


def test_check_expectations_detects_violation():
    expect = EvalExpect(contains=["필수"], not_contains=["ghp_"])
    checks = check_expectations("토큰 ghp_leaked 노출", expect)
    by = {(c.kind, c.target): c.passed for c in checks}
    assert by[("contains", "필수")] is False  # 없음
    assert by[("not_contains", "ghp_")] is False  # 노출됨


# ─────────────────────────── run_eval (fake client) ───────────────────────────


def test_run_eval_scores_with_fake_client():
    cases = [
        EvalCase(name="c1", input="이 PR 리뷰해줘", expect=EvalExpect(contains=["리뷰"], not_contains=["ghp_"])),
        EvalCase(name="c2", input="다시", expect=EvalExpect(contains=["없는문자열"])),
    ]
    report = run_eval(make_resolved(), cases, client=fake_client("리뷰 결과입니다"))
    assert report.scored_count == 2
    r1 = next(c for c in report.cases if c.name == "c1")
    r2 = next(c for c in report.cases if c.name == "c2")
    assert r1.passed is True and r1.score == 1.0
    assert r2.passed is False and r2.score == 0.0
    assert report.mean_score == 0.5


def test_run_eval_dry_run_skips_scoring(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cases = [EvalCase(name="c1", input="x", expect=EvalExpect(contains=["리뷰"]))]
    report = run_eval(make_resolved(), cases, client=None)  # 키 없음 → dry_run
    assert report.scored_count == 0
    assert report.mean_score is None
    assert report.cases[0].scored is False and report.cases[0].dry_run is True


def test_run_eval_no_checks_passes():
    """expect 가 비면(체크 0개) 케이스는 통과로 본다(출력만 확인)."""
    report = run_eval(make_resolved(), [EvalCase(name="c", input="x")], client=fake_client("아무 출력"))
    assert report.cases[0].passed is True and report.cases[0].score == 1.0
