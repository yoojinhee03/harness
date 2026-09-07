"""실행 전 프리뷰 — 조립 분해 뷰(진행 플랜 Phase 6). CLI·API 공용 코어.

`POST /run` 의 dry_run 은 데이터일 뿐 표면이 없었다. 여기서 "실행하면 무슨 일이 벌어지는지"를
**모델 호출 없이** 구조화해 낸다 — 시스템 프롬프트가 어떤 조각으로 조립됐는지, 어떤 MCP 가
실제로 API 로 전송되는지, 훅이 어떤 순서로 도는지, 토큰이 예산 대비 얼마인지.

**경고는 계산하지 않는다** — 리졸버가 이미 낸다(`token_budget_exceeded`·`tool_budget_exceeded`·
`conflict`·`exclusive_conflict`·`deprecated`·`permission_for_unprovided_capability`). 프리뷰가
같은 판정을 다시 짜면 진실 원천이 둘로 갈라져 드리프트가 난다. 그래서 여기선 리졸버 진단을
**그대로 실어 나르고**, 진단이 안 주는 *분해*(누가 얼마를 기여했나)만 새로 만든다.

**토큰은 추정치다** — 카탈로그 `cost.context_tokens` 합이지 실제 토크나이저 계수가 아니다.
`estimated=True` 로 표시해 UI 가 근사임을 밝히게 한다. 실측은 실호출(키) 경로에서만 가능하다.
"""

from __future__ import annotations

from typing import Any

from harness_resolver import (
    Budget,
    Diagnostic,
    HarnessConfig,
    Registry,
    ResolvedHarness,
    resolve,
)
from pydantic import BaseModel, Field

from .emit import emit


class PromptSectionView(BaseModel):
    """시스템 프롬프트 한 조각 — 누가(source) 몇 번째로(layer) 얼마나(tokens) 기여했나."""

    source: str  # "inline" | "prompt:<id>@<ver>" | "component:<id>"
    layer: int
    tokens: int
    chars: int
    excerpt: str  # 앞부분 발췌(전문은 system_text)


class ComponentCostView(BaseModel):
    """컴포넌트별 비용 기여 — 총량만 있던 CostTotals 를 누가 얼마나 썼는지로 쪼갠다."""

    id: str
    type: str
    name: str
    version: str
    context_tokens: int
    added_tools: int
    status: str = "stable"  # deprecated 강조용
    share: float = 0.0  # 컨텍스트 토큰 점유율(0~1) — 무엇을 빼야 예산이 도는지 보여준다


class BudgetView(BaseModel):
    used: int
    limit: int
    estimated: bool = True

    @property
    def over(self) -> bool:
        return self.used > self.limit


class McpServerView(BaseModel):
    """MCP 서버 — **API 로 전송되는지**가 핵심이다(원격만 전송, stdio 는 eject 몫)."""

    id: str
    transport: str
    endpoint: str | None = None  # url(원격) 또는 command(로컬)
    sent_to_api: bool = False


class HookStepView(BaseModel):
    id: str
    blocking: bool
    sandbox: str | None = None
    timeout_ms: int | None = None
    failure: str | None = None
    modifies: list[str] = Field(default_factory=list)  # request/response 변형 여부
    has_command: bool = False  # emit_command 없으면 eject 시 자리표시로 나간다


class AuthView(BaseModel):
    component_id: str
    type: str | None = None
    scopes: list[str] = Field(default_factory=list)
    granted_scope: str | None = None
    satisfied: bool = False  # harness permissions 로 축소 값이 잡혔는가


class PreviewReport(BaseModel):
    """조립 분해 결과. 실제 모델 호출 없음."""

    ok: bool
    harness_id: str = ""
    model: dict[str, Any] = Field(default_factory=dict)

    prompt_hash: str = ""
    prompt_chars: int = 0
    prompt_sections: list[PromptSectionView] = Field(default_factory=list)

    components: list[ComponentCostView] = Field(default_factory=list)
    context_budget: BudgetView | None = None
    tool_budget: BudgetView | None = None

    mcp_servers: list[McpServerView] = Field(default_factory=list)
    hooks: dict[str, list[HookStepView]] = Field(default_factory=dict)
    auth: list[AuthView] = Field(default_factory=list)
    permissions: dict[str, str] = Field(default_factory=dict)

    # 리졸버가 낸 진단 그대로(프리뷰는 재계산하지 않는다).
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    eject_target: str | None = None
    eject_files: dict[str, str] | None = None

    notes: list[str] = Field(default_factory=list)


_EXCERPT = 280


def preview(
    config: HarnessConfig,
    registry: Registry,
    *,
    eject_target: str | None = None,
) -> PreviewReport:
    """harness.yaml(IR) → 조립 분해 뷰. resolve 실패 시에도 진단은 실어 낸다."""
    result = resolve(config, registry)
    diags = list(result.diagnostics.items)

    if result.resolved is None:
        return PreviewReport(
            ok=False,
            harness_id=config.metadata.id,
            diagnostics=diags,
            notes=["resolve 실패 — 분해할 실행 명세가 없습니다(진단을 먼저 해소하세요)."],
        )

    resolved = result.resolved
    budget = config.budget or Budget()
    report = PreviewReport(
        ok=result.ok,
        harness_id=resolved.metadata.id,
        model=resolved.model.model_dump(),
        permissions=resolved.permissions,
        diagnostics=diags,
        components=_component_costs(resolved, registry),
        context_budget=BudgetView(used=resolved.cost.context_tokens, limit=budget.context_tokens),
        tool_budget=BudgetView(used=resolved.cost.added_tools, limit=budget.added_tools),
        mcp_servers=_mcp_servers(resolved),
        hooks=_hooks(resolved),
        auth=[
            AuthView(
                component_id=a.component_id,
                type=a.type,
                scopes=a.scopes,
                granted_scope=a.granted_scope,
                satisfied=a.granted_scope is not None,
            )
            for a in resolved.auth_needs
        ],
        notes=_notes(resolved),  # 프롬프트 관련 노트는 아래에서 덧붙인다(segments 필요)
    )

    if resolved.prompt is not None:
        report.prompt_hash = resolved.prompt.hash
        report.prompt_chars = len(resolved.prompt.system_text)
        report.prompt_sections = [
            PromptSectionView(
                source=s.source,
                layer=s.layer,
                tokens=s.tokens,
                chars=len(s.text),
                excerpt=s.text[:_EXCERPT],
            )
            for s in resolved.prompt.segments
        ]

    # 두 토큰 수치의 출처가 달라 나란히 두면 혼란스럽다 — 조각은 본문에서 센 추정, 컴포넌트는
    # 카탈로그가 선언한 예산용 값이다. 실측(3000 vs 141)에서 자릿수가 갈리므로 명시한다.
    seg_tokens = sum(s.tokens for s in report.prompt_sections)
    if seg_tokens and report.context_budget and report.context_budget.used != seg_tokens:
        report.notes.append(
            f"프롬프트 조각 합({seg_tokens}토큰)과 컨텍스트 예산({report.context_budget.used}토큰)은 "
            "출처가 다릅니다 — 앞은 합성된 본문에서 센 추정, 뒤는 카탈로그가 선언한 예산용 값입니다."
        )

    if eject_target:
        # 방출 뷰 공유(Phase 5) — "이 하네스를 내보내면 이런 파일 트리". 미지원 타깃은 ValueError.
        report.eject_target = eject_target
        report.eject_files = dict(emit(resolved, eject_target))

    return report


def _component_costs(resolved: ResolvedHarness, registry: Registry) -> list[ComponentCostView]:
    """컴포넌트별 비용. cost·status 는 IR 에 없어 카탈로그에서 되읽는다(ResolvedComponent 미보유)."""
    total = max(resolved.cost.context_tokens, 1)
    out: list[ComponentCostView] = []
    for rc in resolved.components:
        c = registry.get(rc.id, None)
        tokens = c.cost.context_tokens if c else 0
        out.append(
            ComponentCostView(
                id=rc.id,
                type=rc.type,
                name=rc.name,
                version=rc.version,
                context_tokens=tokens,
                added_tools=c.cost.added_tools if c else 0,
                status=c.status if c else "stable",
                share=round(tokens / total, 4),
            )
        )
    # 무거운 것부터 — "무엇을 빼야 예산이 도는가"가 이 뷰의 용도다.
    out.sort(key=lambda v: -v.context_tokens)
    return out


def _mcp_servers(resolved: ResolvedHarness) -> list[McpServerView]:
    out: list[McpServerView] = []
    for rc in resolved.components:
        if rc.type != "mcp" or rc.mcp is None:
            continue
        spec = rc.mcp
        remote = spec.transport in ("http", "sse")
        out.append(
            McpServerView(
                id=rc.id,
                transport=spec.transport,
                endpoint=spec.url if remote else spec.command,
                sent_to_api=remote,
            )
        )
    return out


def _hooks(resolved: ResolvedHarness) -> dict[str, list[HookStepView]]:
    plan: dict[str, list[HookStepView]] = {}
    for event, steps in resolved.hook_plan.items():
        plan[event] = [
            HookStepView(
                id=s.id,
                blocking=s.blocking,
                sandbox=s.sandbox,
                timeout_ms=s.timeout_ms,
                failure=s.failure,
                modifies=[
                    m for m, on in (("request", s.can_modify_request), ("response", s.can_modify_response)) if on
                ],
                has_command=bool(s.emit_command),
            )
            for s in steps
        ]
    return plan


def _notes(resolved: ResolvedHarness) -> list[str]:
    """분해를 읽을 때 오해하기 쉬운 지점만 짚는다(경고가 아니라 해설)."""
    notes = ["컨텍스트 토큰은 카탈로그 추정치 합이며 실제 토크나이저 계수가 아닙니다."]

    local = [rc.id for rc in resolved.components if rc.type == "mcp" and rc.mcp and rc.mcp.transport == "stdio"]
    if local:
        notes.append(
            f"stdio MCP {len(local)}개({', '.join(local)})는 로컬 프로세스라 API 요청에 실리지 않습니다 "
            "— eject 한 클라이언트 런타임에서 뜹니다."
        )

    # 카탈로그에 도구 정의가 없어 build_request 의 tools 는 비어 있다. 빈 목록을 그대로 보여주면
    # '도구가 없다'로 읽히므로, added_tools 추정과 MCP 노출이라는 실제 구조를 밝힌다.
    if resolved.cost.added_tools:
        notes.append(
            f"도구 {resolved.cost.added_tools}개는 카탈로그 추정치입니다 — 실제 도구는 MCP 서버가 "
            "런타임에 노출하므로 요청 tools 목록은 비어 있습니다."
        )

    placeholders = [s.id for steps in resolved.hook_plan.values() for s in steps if not s.emit_command]
    if placeholders:
        notes.append(
            f"훅 {len(placeholders)}개({', '.join(sorted(set(placeholders)))})는 실행 명령이 없어 "
            "eject 시 자리표시로 나갑니다."
        )
    return notes
