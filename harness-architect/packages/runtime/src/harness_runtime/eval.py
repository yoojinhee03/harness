"""프롬프트 eval — 설계: 진행 플랜 Phase 11 (경험적 검증).

리졸버의 *구조적* 검증을 넘어, "하네스가 붙었을 때 출력이 실제로 낫는가"를 잰다.
`build_request`(Phase 10) → 러너(Phase 2, 주입가능) → **결정적 채점기**로 케이스를 채점한다.

원칙(문서 §검증 한계): 결정적 체크가 1급(재현성). LLM-judge 는 보조(후속). 키 없으면
러너가 dry_run 이라 출력이 없어 채점을 스킵하되 폴백 경로는 불변 — 클라이언트를 주입하면
(테스트의 fake, 실사용의 anthropic) 그대로 채점된다.
"""

from __future__ import annotations

import re
from typing import Any

from harness_resolver import HarnessConfig, ResolvedHarness
from pydantic import BaseModel, Field

from .builder import build_request
from .runner import AnthropicRunner


class EvalExpect(BaseModel):
    """결정적 기대 — 출력에 대한 재현 가능한 체크(모두 통과해야 케이스 통과)."""

    contains: list[str] = Field(default_factory=list)
    not_contains: list[str] = Field(default_factory=list)
    regex: list[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    name: str
    input: str
    expect: EvalExpect = Field(default_factory=EvalExpect)


class CheckResult(BaseModel):
    kind: str  # "contains" | "not_contains" | "regex"
    target: str
    passed: bool


class EvalCaseResult(BaseModel):
    name: str
    scored: bool  # 출력이 있어 채점됐는가(키 없으면 dry_run → False)
    passed: bool
    score: float  # 통과한 체크 비율 0..1 (미채점 시 0.0)
    checks: list[CheckResult] = Field(default_factory=list)
    dry_run: bool = False
    note: str = ""


class EvalReport(BaseModel):
    cases: list[EvalCaseResult]
    scored_count: int
    mean_score: float | None  # 채점된 케이스 평균(없으면 None — 키 없음)


def check_expectations(output: str, expect: EvalExpect) -> list[CheckResult]:
    """출력을 기대와 대조한 결정적 체크 결과 목록(순수 함수)."""
    results: list[CheckResult] = []
    for s in expect.contains:
        results.append(CheckResult(kind="contains", target=s, passed=s in output))
    for s in expect.not_contains:
        results.append(CheckResult(kind="not_contains", target=s, passed=s not in output))
    for pat in expect.regex:
        results.append(CheckResult(kind="regex", target=pat, passed=re.search(pat, output) is not None))
    return results


def run_eval(resolved: ResolvedHarness, cases: list[EvalCase], client: Any | None = None) -> EvalReport:
    """각 케이스를 하네스로 실행·채점한다. client 미주입 시 env 키로 live, 없으면 dry_run(스킵)."""
    runner = AnthropicRunner(client=client)
    results: list[EvalCaseResult] = []
    for case in cases:
        run = runner.run(build_request(resolved, case.input))
        if run.dry_run or run.text is None:
            results.append(
                EvalCaseResult(
                    name=case.name,
                    scored=False,
                    passed=False,
                    score=0.0,
                    dry_run=run.dry_run,
                    note="출력 없음 — 결정적 체크 스킵. live 채점엔 ANTHROPIC_API_KEY(또는 client 주입) 필요.",
                )
            )
            continue
        checks = check_expectations(run.text, case.expect)
        passed = all(c.passed for c in checks) if checks else True
        score = (sum(c.passed for c in checks) / len(checks)) if checks else 1.0
        results.append(
            EvalCaseResult(name=case.name, scored=True, passed=passed, score=round(score, 4), checks=checks)
        )
    scored = [r for r in results if r.scored]
    mean = round(sum(r.score for r in scored) / len(scored), 4) if scored else None
    return EvalReport(cases=results, scored_count=len(scored), mean_score=mean)


# ─────────────────────────── ablation (컴포넌트 기여도) ───────────────────────────


class AblationResult(BaseModel):
    component_id: str
    full: EvalReport
    ablated: EvalReport
    delta_mean: float | None  # full.mean − ablated.mean (양수면 그 컴포넌트가 품질에 기여)


def drop_component(config: HarnessConfig, component_id: str) -> HarnessConfig:
    """config 에서 특정 컴포넌트를 뺀 새 config(ablation 대상 조립용)."""
    kept = [c for c in config.components if c.id != component_id]
    return config.model_copy(update={"components": kept})


def run_ablation(
    full: ResolvedHarness,
    ablated: ResolvedHarness,
    cases: list[EvalCase],
    component_id: str,
    client: Any | None = None,
) -> AblationResult:
    """같은 eval 셋을 full vs (컴포넌트 제거) 로 돌려 품질 델타를 낸다.

    delta_mean 이 양수면 그 컴포넌트가 출력 품질에 기여한다는 경험적 근거 → 카탈로그 랭킹의
    품질 신호 후보(Phase 9). 채점된 케이스가 없으면(키 없음) delta 는 None.
    """
    fr = run_eval(full, cases, client)
    ar = run_eval(ablated, cases, client)
    delta = (
        round(fr.mean_score - ar.mean_score, 4)
        if fr.mean_score is not None and ar.mean_score is not None
        else None
    )
    return AblationResult(component_id=component_id, full=fr, ablated=ar, delta_mean=delta)
