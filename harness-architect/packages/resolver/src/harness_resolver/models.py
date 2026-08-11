"""카탈로그 컴포넌트 · harness.yaml · ResolvedHarness 데이터 모델.

설계: 카탈로그 스키마 §2·§3, 설계: harness.yaml 스펙 §2·§3.
필드는 두 소비자로 나뉜다 — 검색/랭킹용(RAG, 퍼지)과 계약용(리졸버/빌더, 엄격).
이 모듈은 자산(카탈로그 YAML)에 의존하지 않는다 — 순수 타입 정의.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ComponentType = Literal["skill", "mcp", "context", "hook"]
Status = Literal["stable", "beta", "deprecated"]
Latency = Literal["low", "medium", "high"]
HookEvent = Literal[
    "before_request",
    "after_request",
    "before_tool_call",
    "after_tool_call",
    "after_response",
]
Sandbox = Literal["none", "restricted", "external"]
Failure = Literal["fail_open", "fail_closed"]
InjectionMode = Literal["context", "tool"]
Refresh = Literal["static", "per_session"]


class Cost(BaseModel):
    """랭킹 신호 — 관련성 대비 비용."""

    context_tokens: int = 0
    added_tools: int = 0
    latency: Latency = "low"


class Auth(BaseModel):
    required: bool = False
    type: str | None = None
    scopes: list[str] = Field(default_factory=list)


class Constraints(BaseModel):
    exclusive_group: str | None = None


class McpServerSpec(BaseModel):
    """MCP 서버 실행 스펙 — `.mcp.json`(및 러너) 방출의 단일 원본.

    transport 별로 필요한 필드가 갈린다:
    - stdio      : `command`(+ `args`, `env`) — 로컬 프로세스로 서버를 띄운다.
    - http / sse : `url` — 원격 엔드포인트에 접속한다.

    비밀값은 파일에 박지 말고 `${ENV_VAR}` 확장 표기를 쓴다(Claude Code 가 확장).
    """

    model_config = ConfigDict(extra="forbid")

    transport: Literal["stdio", "http", "sse"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> McpServerSpec:
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport 는 command 가 필요합니다")
        if self.transport in ("http", "sse") and not self.url:
            raise ValueError(f"{self.transport} transport 는 url 이 필요합니다")
        return self


class Component(BaseModel):
    """카탈로그 컴포넌트. 공통 베이스 + 타입별 델타(optional).

    검증은 리졸버가 `type` 에 맞는 델타 필드를 소비할 때 이뤄진다.
    """

    model_config = ConfigDict(extra="forbid")

    # ── 식별 ──
    id: str
    type: ComponentType
    name: str
    version: str
    status: Status = "stable"

    # ── 검색/랭킹용 (RAG, 퍼지) ──
    summary: str = ""
    description: str = ""
    use_when: list[str] = Field(default_factory=list)
    capability_tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)

    # ── 랭킹 신호 ──
    cost: Cost = Field(default_factory=Cost)
    usage_count: int = 0
    retention_score: float = 0.0

    # ── 의존성/제약 (리졸버, 엄격) ──
    provides: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)

    # ── 실행/설정 (빌더, 엄격) ──
    auth: Auth | None = None
    config_schema: dict[str, Any] | None = None
    defaults: dict[str, Any] = Field(default_factory=dict)

    # ── 타입 델타: skill ──
    entrypoint: str | None = None
    injection_mode: InjectionMode | None = None

    # ── 타입 델타: mcp ──
    mcp: McpServerSpec | None = None  # 서버 실행 스펙 — .mcp.json/러너 방출의 단일 원본

    # ── 타입 델타: context ──
    source: str | None = None
    size_estimate: int | None = None
    refresh: Refresh | None = None
    body: str | None = None  # 프롬프트 조각 본문 — prompt.system[].ref 로 주입되는 실제 텍스트

    # ── 타입 델타: hook ──
    events: list[HookEvent] = Field(default_factory=list)
    sandbox: Sandbox | None = None
    blocking: bool = False
    can_modify_request: bool = False
    can_modify_response: bool = False
    failure: Failure | None = None
    timeout_ms: int | None = None
    depends_on: list[str] = Field(default_factory=list)
    emit_command: str | None = None  # eject 시 방출할 실제 셸 명령(없으면 자리표시). 훅 실행 모델 §eject

    def embedding_document(self) -> str:
        """임베딩용 합성 문서 — summary + description + use_when + tags + examples."""
        parts = [self.summary, self.description, *self.use_when, *self.capability_tags, *self.examples]
        return "\n".join(p.strip() for p in parts if p and p.strip())


# ─────────────────────────── harness.yaml (선언) ───────────────────────────


class HarnessMetadata(BaseModel):
    id: str
    name: str = ""
    version: str = "0.1.0"
    description: str = ""


class ModelConfig(BaseModel):
    """스코프 결정: 컴포넌트 아닌 harness.yaml 최상위 선언 필드."""

    provider: str = "anthropic"
    name: str = "claude-sonnet-5"
    max_tokens: int = 4096
    temperature: float = 0.2


class Budget(BaseModel):
    context_tokens: int = 8000
    added_tools: int = 30


class ComponentSelection(BaseModel):
    """harness.yaml components[] 항목 — `id@version` 참조 + config 오버라이드."""

    ref: str  # "id@version" (version 생략 시 최신 stable)
    config: dict[str, Any] = Field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.ref.split("@", 1)[0]

    @property
    def version(self) -> str | None:
        parts = self.ref.split("@", 1)
        return parts[1] if len(parts) == 2 else None


# ─────────────────────────── prompt 블록 (합성 선언) ───────────────────────────

VarType = Literal["string", "number", "boolean"]
OnConflict = Literal["warn", "error", "last_wins"]


class PromptVariable(BaseModel):
    """prompt.variables[<name>] — 선언적 변수. 값은 default 로 해소, 없으면 미해결(경고)."""

    type: VarType = "string"
    default: Any | None = None
    required: bool = False
    description: str = ""


class PromptCompose(BaseModel):
    """합성 규칙 — 중복 제거·충돌 정책·토큰 예산."""

    dedup: bool = True
    on_conflict: OnConflict = "warn"
    budget_tokens: int | None = None  # None = 예산 없음


class PromptLayer(BaseModel):
    """system 레이어 항목 — `ref`(카탈로그 조각) 또는 `inline`(텍스트) 중 정확히 하나."""

    model_config = ConfigDict(extra="forbid")

    ref: str | None = None  # "id@version" — context 프롬프트 조각 참조
    inline: str | None = None  # 인라인 텍스트

    @model_validator(mode="after")
    def _exactly_one(self) -> PromptLayer:
        if bool(self.ref) == bool(self.inline):
            raise ValueError("PromptLayer 는 ref 또는 inline 중 정확히 하나여야 합니다")
        return self

    @property
    def component_id(self) -> str | None:
        return self.ref.split("@", 1)[0] if self.ref else None

    @property
    def version(self) -> str | None:
        if not self.ref:
            return None
        parts = self.ref.split("@", 1)
        return parts[1] if len(parts) == 2 else None


class PromptSpec(BaseModel):
    """harness.yaml prompt 블록 — 시스템 프롬프트 합성 선언."""

    system: list[PromptLayer] = Field(default_factory=list)
    variables: dict[str, PromptVariable] = Field(default_factory=dict)
    compose: PromptCompose = Field(default_factory=PromptCompose)


class HarnessConfig(BaseModel):
    """harness.yaml — 저작 레이어의 산출물이자 리졸버의 입력."""

    model_config = ConfigDict(populate_by_name=True)

    apiVersion: str = Field(default="harness/v1", alias="apiVersion")
    kind: str = "Harness"
    metadata: HarnessMetadata
    extends: str | None = None
    model: ModelConfig = Field(default_factory=ModelConfig)
    permissions: dict[str, str] = Field(default_factory=dict)
    components: list[ComponentSelection] = Field(default_factory=list)
    budget: Budget | None = None
    prompt: PromptSpec | None = None


# ─────────────────────────── ResolvedHarness (실행 명세) ───────────────────────────


class HookStep(BaseModel):
    """훅 실행 계획의 한 스텝 — 이벤트별 정렬 결과."""

    id: str
    event: HookEvent
    blocking: bool
    can_modify_request: bool
    can_modify_response: bool
    sandbox: Sandbox | None
    failure: Failure | None
    timeout_ms: int | None
    emit_command: str | None = None  # eject 시 방출할 실제 셸 명령(카탈로그가 제공, 없으면 자리표시)


class AuthNeed(BaseModel):
    component_id: str
    type: str | None
    scopes: list[str]
    granted_scope: str | None = None  # harness permissions 로 축소된 값


class ResolvedComponent(BaseModel):
    """리졸브된 컴포넌트 — 카탈로그 정의 + 확정된 config(defaults ⊕ override)."""

    id: str
    type: ComponentType
    version: str
    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    mcp: McpServerSpec | None = None  # mcp 타입일 때 실행 스펙(이젝트·러너가 소비)
    body: str | None = None  # skill/context 본문 — 시스템 프롬프트(CLAUDE.md)에 주입되는 실제 텍스트


class CostTotals(BaseModel):
    context_tokens: int = 0
    added_tools: int = 0


class PromptSegment(BaseModel):
    """합성된 시스템 프롬프트의 한 조각 — provenance(누가 뭘 기여했나)."""

    source: str  # "inline" | "prompt:<id>@<ver>" | "component:<id>"
    layer: int  # 합성 순서(0-base)
    tokens: int  # 추정 토큰 기여(실측 아님)
    text: str = ""  # 변수 치환 후 텍스트


class ResolvedPrompt(BaseModel):
    """리졸버가 합성한 시스템 프롬프트(실행 명세). 빌더·프리뷰·eject 의 단일 원본."""

    system_text: str = ""
    segments: list[PromptSegment] = Field(default_factory=list)
    variables_resolved: dict[str, Any] = Field(default_factory=dict)
    hash: str = ""  # "sha256:…" — 드리프트·캐시 키(system_text 기준, 결정적)


class ResolvedHarness(BaseModel):
    """리졸버 출력(성공) — 실행 가능한 명세. 런타임 빌더의 입력."""

    metadata: HarnessMetadata
    model: ModelConfig
    permissions: dict[str, str]
    components: list[ResolvedComponent]
    provided: dict[str, list[str]]  # capability → [제공 컴포넌트 id]
    hook_plan: dict[str, list[HookStep]]  # event → 정렬된 훅 스텝
    auth_needs: list[AuthNeed]
    cost: CostTotals
    prompt: ResolvedPrompt | None = None  # 합성된 시스템 프롬프트(resolve 는 항상 채움)
