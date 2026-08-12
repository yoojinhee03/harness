"""리졸버 — 8단계 순수 함수 검증 파이프라인.

설계: 리졸버 검증 로직 §2·§3. 동일 입력이면 동일 출력, 부작용 없음(테스트·캐싱 용이).

    resolve(config, registry) → ResolveResult
        .ok           # error 가 없으면 True (gap·warning 은 진행 가능)
        .resolved     # ok 일 때 ResolvedHarness, 아니면 None
        .diagnostics  # 누적된 error/warning/gap

gap(미충족 requires)은 하드 에러가 아니라 추천기로 되돌리는 신호다.
"""

from __future__ import annotations

import heapq
from collections import defaultdict

from pydantic import BaseModel

from .diagnostics import Diagnostics
from .merge import merge_harness_configs
from .models import (
    AuthNeed,
    Budget,
    Component,
    ComponentSelection,
    CostTotals,
    HarnessConfig,
    HarnessMetadata,
    HookStep,
    ResolvedComponent,
    ResolvedHarness,
    ResolvedSubAgent,
)
from .prompt import compose_prompt
from .registry import Registry


class ResolveResult(BaseModel):
    ok: bool
    resolved: ResolvedHarness | None
    diagnostics: Diagnostics


def resolve(config: HarnessConfig, registry: Registry) -> ResolveResult:
    diag = Diagnostics()

    # ── 2. 상속 병합 (extends) — 참조 해소 전에 유효 config 확정 ──
    effective = config
    if config.extends:
        base = registry.get_base(config.extends)
        if base is None:
            diag.warn("unknown_base", f"상속 베이스 '{config.extends}' 를 찾을 수 없음", base=config.extends)
        else:
            effective = merge_harness_configs(base, config)

    # ── 1. 참조 해소 (+ config_schema 검증, id 유일성) ──
    comps: list[Component] = []
    resolved_components: list[ResolvedComponent] = []
    seen_ids: set[str] = set()
    for sel in effective.components:
        if sel.id in seen_ids:
            diag.error("duplicate_component", f"컴포넌트 id '{sel.id}' 가 중복됨", id=sel.id)
            continue
        seen_ids.add(sel.id)

        c = registry.get(sel.id, sel.version)
        if c is None:
            diag.error(
                "unknown_component",
                f"카탈로그에 '{sel.ref}' 가 없거나 버전이 불일치",
                ref=sel.ref,
            )
            continue
        if c.status == "deprecated":
            diag.warn("deprecated", f"'{c.id}@{c.version}' 는 deprecated", id=c.id, version=c.version)

        merged_config = {**c.defaults, **sel.config}
        _validate_config(diag, c, sel, merged_config)

        comps.append(c)
        resolved_components.append(
            ResolvedComponent(
                id=c.id, type=c.type, version=c.version, name=c.name,
                config=merged_config, mcp=c.mcp, body=c.body,
            )
        )

    # ── 3. 능력 공급 맵 ──
    provided: dict[str, list[str]] = defaultdict(list)
    for c in comps:
        for cap in c.provides:
            provided[cap].append(c.id)

    # ── 4. 의존성 해소 (requires 충족; 전이는 평탄 능력이라 직접 매칭) ──
    for c in comps:
        for cap in c.requires:
            if cap not in provided:
                diag.gap(c.id, cap)

    # ── 5. 충돌 감지 (exclusive_group 중복 · conflicts_with 쌍) ──
    groups: dict[str, list[str]] = defaultdict(list)
    for c in comps:
        if c.constraints.exclusive_group:
            groups[c.constraints.exclusive_group].append(c.id)
    for group, members in groups.items():
        if len(members) > 1:
            diag.error(
                "exclusive_conflict",
                f"배타 그룹 '{group}' 에 컴포넌트가 여럿 선택됨: {members}",
                group=group,
                members=members,
            )
    ids = {c.id for c in comps}
    for c in comps:
        for other in c.conflicts_with:
            if other in ids:
                diag.error("conflict", f"'{c.id}' 와 '{other}' 는 충돌", a=c.id, b=other)

    # ── 6. 비용 예산 (초과는 error 아닌 warning) ──
    budget = effective.budget or Budget()
    tokens = sum(c.cost.context_tokens for c in comps)
    tools = sum(c.cost.added_tools for c in comps)
    if tokens > budget.context_tokens:
        diag.warn(
            "token_budget_exceeded",
            f"컨텍스트 토큰 {tokens} > 예산 {budget.context_tokens}",
            used=tokens,
            budget=budget.context_tokens,
        )
    if tools > budget.added_tools:
        diag.warn(
            "tool_budget_exceeded",
            f"추가 도구 {tools} > 예산 {budget.added_tools}",
            used=tools,
            budget=budget.added_tools,
        )

    # ── 7. 훅 순서 (이벤트별 정렬 + depends_on 위상정렬 + blocking 우선) ──
    hook_plan = _order_hooks([c for c in comps if c.type == "hook"])

    # ── 8. 권한 수집 + 축소(narrowing) 검증 ──
    auth_needs: list[AuthNeed] = []
    for c in comps:
        if c.auth and c.auth.required:
            granted = next((effective.permissions[cap] for cap in c.provides if cap in effective.permissions), None)
            auth_needs.append(
                AuthNeed(component_id=c.id, type=c.auth.type, scopes=c.auth.scopes, granted_scope=granted)
            )
    for cap in effective.permissions:
        if cap not in provided:
            diag.warn(
                "permission_for_unprovided_capability",
                f"permissions 에 선언된 '{cap}' 를 제공하는 컴포넌트가 선택 집합에 없음",
                capability=cap,
            )

    # ── 9. 프롬프트 합성 (Phase 10) — 시스템 프롬프트를 명시적 아티팩트로 승격 ──
    #    authored 레이어 없이도(= prompt 블록 미지정) 컴포넌트 기여만 합성 → 기존 조립과 동치.
    #    on_conflict=error 인 중복 등은 여기서 error 를 낼 수 있어 아래 has_errors 로 차단된다.
    resolved_prompt = compose_prompt(effective.prompt, resolved_components, registry, diag)

    # ── 10. 서브에이전트(팀) 재귀 해소 (멀티에이전트) — 이름 유일성 + 각 역할 검증 ──
    resolved_subagents = _resolve_subagents(effective, registry, diag)

    if diag.has_errors():
        return ResolveResult(ok=False, resolved=None, diagnostics=diag)

    resolved = ResolvedHarness(
        metadata=effective.metadata,
        model=effective.model,
        permissions=effective.permissions,
        components=resolved_components,
        provided=dict(provided),
        hook_plan=hook_plan,
        auth_needs=auth_needs,
        cost=CostTotals(context_tokens=tokens, added_tools=tools),
        prompt=resolved_prompt,
        subagents=resolved_subagents,
    )
    return ResolveResult(ok=True, resolved=resolved, diagnostics=diag)


def _resolve_subagents(effective: HarnessConfig, registry: Registry, diag: Diagnostics) -> list[ResolvedSubAgent]:
    """서브에이전트 팀을 재귀 해소한다(1레벨). 이름 중복은 error, 각 역할은 resolve 로 검증."""
    out: list[ResolvedSubAgent] = []
    seen: set[str] = set()
    for sub in effective.subagents:
        if sub.name in seen:
            diag.error("duplicate_subagent", f"서브에이전트 이름 '{sub.name}' 가 중복됨", name=sub.name)
            continue
        seen.add(sub.name)
        sub_config = HarnessConfig(
            metadata=HarnessMetadata(id=f"{effective.metadata.id}:{sub.name}"),
            model=effective.model,
            components=sub.components,
            prompt=sub.prompt,
        )
        sub_result = resolve(sub_config, registry)  # 재귀(sub_config 엔 subagents 없음 → 종료)
        if not sub_result.ok or sub_result.resolved is None:
            for e in sub_result.diagnostics.errors:
                diag.error("subagent_error", f"서브에이전트 '{sub.name}': {e.message}", name=sub.name)
            continue
        out.append(
            ResolvedSubAgent(
                name=sub.name,
                description=sub.description,
                components=sub_result.resolved.components,
                prompt=sub_result.resolved.prompt,
            )
        )
    return out


def _validate_config(
    diag: Diagnostics, component: Component, sel: ComponentSelection, merged_config: dict[str, object]
) -> None:
    """config 가 대상 컴포넌트 config_schema 를 준수하는지 검증 (harness.yaml §6)."""
    if not component.config_schema:
        return
    try:
        import jsonschema

        jsonschema.validate(instance=merged_config, schema=component.config_schema)
    except ModuleNotFoundError:  # pragma: no cover - jsonschema 는 의존성
        return
    except Exception as exc:  # jsonschema.ValidationError
        diag.error(
            "config_schema_violation",
            f"'{component.id}' 의 config 가 스키마를 위반: {getattr(exc, 'message', str(exc))}",
            id=component.id,
        )


def _order_hooks(hooks: list[Component]) -> dict[str, list[HookStep]]:
    """이벤트별로 훅을 정렬한다.

    동일 이벤트 내: (1) depends_on 위상정렬 → (2) blocking 우선 → (3) 등록 순.
    변형(can_modify) 훅은 파이프라인으로 연쇄(정렬 순서가 곧 연쇄 순서).
    """
    reg_index = {h.id: i for i, h in enumerate(hooks)}
    events: list[str] = []
    for h in hooks:
        for e in h.events:
            if e not in events:
                events.append(e)

    plan: dict[str, list[HookStep]] = {}
    for event in events:
        subset = [h for h in hooks if event in h.events]
        ordered = _topo_sort(subset, reg_index)
        plan[event] = [
            HookStep(
                id=h.id,
                event=event,  # type: ignore[arg-type]
                blocking=h.blocking,
                can_modify_request=h.can_modify_request,
                can_modify_response=h.can_modify_response,
                sandbox=h.sandbox,
                failure=h.failure,
                timeout_ms=h.timeout_ms,
                emit_command=h.emit_command,
            )
            for h in ordered
        ]
    return plan


def _topo_sort(subset: list[Component], reg_index: dict[str, int]) -> list[Component]:
    """Kahn 위상정렬 + 타이브레이크(blocking 우선, 그다음 등록 순).

    depends_on 은 "이 훅보다 먼저 실행돼야 하는 훅 id" 목록. subset 밖의 의존성은 무시.
    """
    by_id = {h.id: h for h in subset}
    ids = set(by_id)
    indeg: dict[str, int] = {h.id: 0 for h in subset}
    edges: dict[str, list[str]] = defaultdict(list)  # dep → [dependents]
    for h in subset:
        for dep in h.depends_on:
            if dep in ids:
                edges[dep].append(h.id)
                indeg[h.id] += 1

    def priority(hid: str) -> tuple[int, int]:
        h = by_id[hid]
        return (0 if h.blocking else 1, reg_index.get(hid, 0))

    ready = [hid for hid, d in indeg.items() if d == 0]
    heap = [(priority(hid), hid) for hid in ready]
    heapq.heapify(heap)
    out: list[Component] = []
    while heap:
        _, hid = heapq.heappop(heap)
        out.append(by_id[hid])
        for dependent in edges[hid]:
            indeg[dependent] -= 1
            if indeg[dependent] == 0:
                heapq.heappush(heap, (priority(dependent), dependent))

    if len(out) < len(subset):  # 순환 의존 — 남은 것은 등록 순으로 뒤에 붙임
        remaining = sorted((h for h in subset if h not in out), key=lambda h: reg_index.get(h.id, 0))
        out.extend(remaining)
    return out
