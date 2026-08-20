"""정적 검증 코어 — adopt→resolve→판정. CLI(harness verify)·API(POST /verify) 공용(드리프트 방지).

파일 트리({경로: 내용}) + registry 를 받아 3종을 낸다:
  ① 능력 미충족 — 리졸버 gap + `--require` 통제어휘 멤버십.
  ② 이식 손실 — 지정 타깃 이미터가 선언한 손실(target_losses).
  ③ 리졸버 에러 — 훅 계약 위반·순환 등(resolve diagnostics.errors).
I/O·DB 없음(파일 읽기는 호출부 `read_native_tree`, gap/공출현 DB 기록은 API). caps 판정은
TASK 3(caps 커버리지) 완료 전 **잠정**(거짓 gap 가능)이라 기본 심각도는 warning.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from harness_resolver import Registry, resolve

from .adopt import adopt
from .emit import target_losses

# 기본 심각도(거짓양성 보수적). CLI 는 .harness/policy.yaml 로 오버라이드, API 는 이 기본을 쓴다.
DEFAULT_SEVERITY = {
    "resolve_error": "violation",  # 리졸버 하드 에러(훅 오용·순환 등)
    "required_missing": "violation",  # --require 로 명시 요구했는데 미충족
    "capability_gap": "warning",  # 흡수 컴포넌트의 미충족 requires (TASK 3 전 잠정)
    "portability_loss": "warning",
    "resolve_warning": "warning",
}


@dataclass
class VerifyReport:
    findings: dict[str, list[dict[str, Any]]]
    component_ids: list[str]  # 해소된 컴포넌트 id (공출현 기록용)
    gap_capabilities: list[str]  # gap + required_missing 능력 (GapDemand 기록용)
    unknown_mcp: list[str] = field(default_factory=list)
    unknown_skills: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def verify(
    files: dict[str, str],
    registry: Registry,
    require: Iterable[str] = (),
    target: str | None = None,
) -> VerifyReport:
    """네이티브 파일 트리를 adopt→resolve 로 정적 검증. target 미지원이면 target_losses 가 ValueError."""
    adopted = adopt(files, registry)
    result = resolve(adopted.config, registry)

    provided: set[str] = set()
    ids: list[str] = []
    for rc in result.resolved.components if result.resolved else []:
        ids.append(rc.id)
        comp = registry.get(rc.id)
        if comp is not None:
            provided |= set(comp.provides) | set(comp.capability_tags)
    required_missing = [c for c in require if c not in provided]

    losses: list[dict[str, Any]] = []
    if target and result.resolved is not None:
        losses = [
            {"feature": lo.feature, "fidelity": lo.fidelity, "detail": lo.detail}
            for lo in target_losses(result.resolved, target)
        ]

    findings: dict[str, list[dict[str, Any]]] = {
        "resolve_error": [{"code": d.code, "message": d.message} for d in result.diagnostics.errors],
        "capability_gap": [
            {"capability": g.capability, "component_id": g.component_id}
            for g in result.diagnostics.gaps
        ],
        "required_missing": [{"capability": c} for c in required_missing],
        "portability_loss": losses,
        "resolve_warning": [
            {"code": d.code, "message": d.message} for d in result.diagnostics.warnings
        ],
    }
    gap_caps = [g.capability for g in result.diagnostics.gaps if g.capability] + required_missing
    return VerifyReport(
        findings=findings,
        component_ids=ids,
        gap_capabilities=gap_caps,
        unknown_mcp=adopted.unknown_mcp,
        unknown_skills=adopted.unknown_skills,
        notes=adopted.notes,
    )


def violations(findings: dict[str, list[dict[str, Any]]], severity: dict[str, str]) -> list[str]:
    """severity 가 violation 인 카테고리 중 항목이 있는 것들."""
    return [cat for cat, items in findings.items() if items and severity.get(cat) == "violation"]
