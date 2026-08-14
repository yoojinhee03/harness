"""진단(Diagnostics) 모델 — 설계: 리졸버 검증 로직 §6.

세 종류:
- error   — 생성 차단. 존재하지 않는 컴포넌트, 충돌 등.
- warning — 진행 가능하나 주의. deprecated, 예산 초과 등.
- gap     — 충족되지 않은 requires. 리졸버 ↔ RAG 추천기 루프를 닫는 핵심 신호.
            하드 에러가 아니라 "재조정하면 풀리는 것" — 추천기로 되돌린다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["error", "warning", "gap"]


class Diagnostic(BaseModel):
    severity: Severity
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
    # gap 전용: 어떤 컴포넌트의 어떤 능력이 미충족인지 (추천기로 되돌릴 신호)
    component_id: str | None = None
    capability: str | None = None


class Diagnostics(BaseModel):
    """파이프라인 단계들이 누적하는 진단 목록."""

    items: list[Diagnostic] = Field(default_factory=list)

    def error(self, code: str, message: str, **detail: Any) -> None:
        self.items.append(Diagnostic(severity="error", code=code, message=message, detail=detail))

    def warn(self, code: str, message: str, **detail: Any) -> None:
        self.items.append(Diagnostic(severity="warning", code=code, message=message, detail=detail))

    def gap(self, component_id: str, capability: str, message: str | None = None) -> None:
        self.items.append(
            Diagnostic(
                severity="gap",
                code="unsatisfied_requires",
                message=message or f"'{component_id}' 가 요구하는 능력 '{capability}' 를 제공하는 컴포넌트가 없음",
                component_id=component_id,
                capability=capability,
            )
        )

    # ── 질의 ──
    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity == "warning"]

    @property
    def gaps(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity == "gap"]

    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self.items)
