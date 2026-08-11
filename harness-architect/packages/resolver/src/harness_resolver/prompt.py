"""프롬프트 합성 — 설계: 진행 플랜 Phase 10 (Prompt Composition & Lifecycle).

시스템 프롬프트를 컴포넌트에서 emergent 하게 조립하던 것을 **명시적·검증 가능한 1급
아티팩트**로 승격한다. `compose_prompt` 는 순수 함수로,

    prompt.system 레이어(ref/inline) → 변수 치환 → 컴포넌트(context/skill) 기여
    → dedup/충돌 → 예산 → provenance(segments) + 결정적 hash

를 거쳐 `ResolvedPrompt` 를 만든다. 진단(미해결 변수·중복·예산·미지 조각)은 리졸버 진단
어휘(`Diagnostics`)로 누적한다.
"""

from __future__ import annotations

import hashlib
import re

from .diagnostics import Diagnostics
from .models import (
    PromptCompose,
    PromptSegment,
    PromptSpec,
    ResolvedComponent,
    ResolvedPrompt,
)
from .registry import Registry

# {{ var_name }} — 앞뒤 공백 허용, 식별자만.
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def estimate_tokens(text: str) -> int:
    """러프 토큰 추정 — 실측 아님(문자수/4 근사). 검증 한계: Phase 10 문서 참조."""
    return (len(text) + 3) // 4 if text else 0


def _component_segment_text(comp: ResolvedComponent) -> str | None:
    """context/skill 컴포넌트가 시스템 프롬프트에 기여하는 텍스트.

    NOTE: `harness_runtime.builder._assemble_system_fallback` 과 **글자까지 동일**해야
    한다(동치 회귀). 한쪽을 바꾸면 다른 쪽·회귀 테스트도 함께 갱신할 것.
    """
    if comp.type == "context":
        return f"## 컨텍스트: {comp.name} ({comp.id})\n[주입된 컨텍스트 — config={comp.config}]"
    if comp.type == "skill":
        return f"## 스킬 절차: {comp.name} ({comp.id})\n[주입된 절차 — config={comp.config}]"
    return None


def _resolve_variables(spec: PromptSpec | None) -> dict[str, object]:
    """변수 값을 해소한다 — 현재는 default 만(값 주입은 후속). default 없으면 미포함."""
    if spec is None:
        return {}
    return {name: v.default for name, v in spec.variables.items() if v.default is not None}


def _type_ok(declared: str, value: object) -> bool:
    """값이 선언 타입과 맞는지. bool 은 int 하위형이므로 number 에서 배제한다."""
    if declared == "string":
        return isinstance(value, str)
    if declared == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    return True


def _check_variable_declarations(
    spec: PromptSpec | None, values: dict[str, object], diag: Diagnostics
) -> None:
    """선언된 변수의 required/type 계약을 검증한다(값은 default 로 해소된 것 기준).

    - required=True 인데 값이 없으면 경고(recoverable — 값·default 를 주면 해소, gap 성격).
    - 값이 선언 타입과 불일치하면 경고.
    """
    if spec is None:
        return
    for name, v in spec.variables.items():
        if name not in values:
            if v.required:
                diag.warn(
                    "required_variable_unset",
                    f"필수 변수 '{name}' 에 값(default)이 없음 — default 를 주거나 값을 지정하세요",
                    variable=name,
                )
            continue
        if not _type_ok(v.type, values[name]):
            diag.warn(
                "variable_type_mismatch",
                f"변수 '{name}' 의 값이 선언 타입 '{v.type}' 과 불일치",
                variable=name,
                declared=v.type,
            )


def _substitute(text: str, values: dict[str, object]) -> tuple[str, set[str]]:
    """`{{name}}` 치환. 값 없는 참조는 placeholder 를 남기고 이름을 미해결로 반환."""
    unresolved: set[str] = set()

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in values:
            return str(values[name])
        unresolved.add(name)
        return m.group(0)

    return _VAR_RE.sub(repl, text), unresolved


def compose_prompt(
    spec: PromptSpec | None,
    resolved_components: list[ResolvedComponent],
    registry: Registry,
    diag: Diagnostics,
) -> ResolvedPrompt:
    """시스템 프롬프트를 합성해 `ResolvedPrompt`(텍스트+provenance+변수+hash)를 만든다.

    spec 이 None 이면 authored 레이어 없이 컴포넌트 기여만 합성 → 기존 build_request 조립과 동치.
    """
    values = _resolve_variables(spec)
    _check_variable_declarations(spec, values, diag)

    # ── 1) 원시 조각 수집: authored 레이어(ref/inline) → 컴포넌트(context/skill) ──
    raw: list[tuple[str, str]] = []  # (source, text)
    if spec is not None:
        for item in spec.system:
            if item.ref:
                fragment = registry.get(item.component_id or "", item.version)
                if fragment is None:
                    diag.warn(
                        "unknown_prompt_fragment",
                        f"프롬프트 조각 '{item.ref}' 를 카탈로그에서 찾을 수 없음",
                        ref=item.ref,
                    )
                    continue
                if fragment.status == "deprecated":
                    diag.warn(
                        "deprecated_prompt_fragment",
                        f"프롬프트 조각 '{fragment.id}@{fragment.version}' 는 deprecated",
                        id=fragment.id,
                        version=fragment.version,
                    )
                text = fragment.body or ""
                if not text.strip():
                    diag.warn(
                        "empty_prompt_fragment",
                        f"프롬프트 조각 '{fragment.id}@{fragment.version}' 에 body 텍스트가 없음",
                        id=fragment.id,
                    )
                    continue
                source = f"prompt:{fragment.id}@{fragment.version}"
            else:
                text = item.inline or ""
                source = "inline"
            raw.append((source, text))

    for comp in resolved_components:
        t = _component_segment_text(comp)
        if t is not None:
            raw.append((f"component:{comp.id}", t))

    # ── 2) 변수 치환 + 미해결 수집 ──
    subbed: list[tuple[str, str]] = []
    unresolved: set[str] = set()
    for source, text in raw:
        st, un = _substitute(text, values)
        unresolved |= un
        subbed.append((source, st))
    for name in sorted(unresolved):
        diag.warn(
            "unresolved_variable",
            f"프롬프트 변수 '{{{{{name}}}}}' 의 값이 없음 — default 를 주거나 값을 지정하세요",
            variable=name,
        )

    # ── 3) dedup / 충돌 정책 ──
    compose = spec.compose if spec is not None else PromptCompose()
    final: list[tuple[str, str]] = []
    for source, text in subbed:
        dup_idx = next((i for i, (_, t) in enumerate(final) if t == text), None)
        if compose.dedup and dup_idx is not None:
            if compose.on_conflict == "error":
                diag.error(
                    "duplicate_prompt_segment",
                    f"중복 프롬프트 조각(on_conflict=error): {source}",
                    source=source,
                )
                continue
            kept = "마지막 우선" if compose.on_conflict == "last_wins" else "첫 항목 유지"
            diag.warn(
                "duplicate_prompt_segment",
                f"중복 프롬프트 조각 — {kept}: {source}",
                source=source,
            )
            if compose.on_conflict == "last_wins":
                final.pop(dup_idx)
                final.append((source, text))
            continue
        final.append((source, text))

    # ── 4) provenance + 예산 + hash ──
    segments = [
        PromptSegment(source=s, layer=i, tokens=estimate_tokens(t), text=t)
        for i, (s, t) in enumerate(final)
    ]
    system_text = "\n\n".join(t for _, t in final)

    total = sum(seg.tokens for seg in segments)
    if compose.budget_tokens is not None and total > compose.budget_tokens:
        diag.warn(
            "prompt_budget_exceeded",
            f"프롬프트 토큰 추정 {total} > 예산 {compose.budget_tokens}",
            used=total,
            budget=compose.budget_tokens,
        )

    digest = hashlib.sha256(system_text.encode("utf-8")).hexdigest()
    return ResolvedPrompt(
        system_text=system_text,
        segments=segments,
        variables_resolved=dict(values),
        hash=f"sha256:{digest}",
    )
