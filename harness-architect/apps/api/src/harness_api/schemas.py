"""API 요청/응답 스키마 — 화면 A·B·C·E 계약."""

from __future__ import annotations

from typing import Any

from harness_resolver import Component, ComponentSelection, HarnessConfig, HarnessMetadata, PromptSpec
from pydantic import BaseModel, Field


class CatalogItem(BaseModel):
    """카탈로그 목록/상세 (화면 E)."""

    id: str
    type: str
    name: str
    version: str
    status: str
    summary: str
    capability_tags: list[str]
    provides: list[str]
    requires: list[str]
    conflicts_with: list[str]
    exclusive_group: str | None
    context_tokens: int
    added_tools: int
    auth_required: bool
    # ── 프로비넌스(신뢰 등급) ──
    trust: str = "community"  # curated(손큐레이션) | official(공식 소스) | community(미검증 외부)
    source: str | None = None  # 출처 URL/경로(있으면) — 프로비넌스 표시용.

    @classmethod
    def from_component(cls, c: Component, *, trust: str = "community") -> CatalogItem:
        return cls(
            id=c.id,
            type=c.type,
            name=c.name,
            version=c.version,
            status=c.status,
            summary=c.summary,
            capability_tags=c.capability_tags,
            provides=c.provides,
            requires=c.requires,
            conflicts_with=c.conflicts_with,
            exclusive_group=c.constraints.exclusive_group,
            context_tokens=c.cost.context_tokens,
            added_tools=c.cost.added_tools,
            auth_required=bool(c.auth and c.auth.required),
            trust=trust,
            source=c.source,
        )


class RecommendRequest(BaseModel):
    """화면 A — 프로젝트 자연어 설명."""

    description: str = Field(min_length=1)
    top_k: int = 6


class KeyUpdate(BaseModel):
    """설정 화면 — 런타임 API 키 설정/수정(빈 값/None 은 변경 없음)."""

    anthropic_api_key: str | None = None
    voyage_api_key: str | None = None


class SelectionInput(BaseModel):
    ref: str
    config: dict[str, Any] = Field(default_factory=dict)


class ResolveRequest(BaseModel):
    """화면 C — 선택된 구성으로 검증(dry-run). metadata 는 선택."""

    metadata: HarnessMetadata | None = None
    extends: str | None = None
    model: dict[str, Any] | None = None
    permissions: dict[str, str] = Field(default_factory=dict)
    components: list[SelectionInput] = Field(default_factory=list)
    budget: dict[str, int] | None = None
    prompt: PromptSpec | None = None  # 시스템 프롬프트 합성 블록(Phase 10) — harness.yaml prompt 와 동일 형태

    def to_config(self) -> HarnessConfig:
        data: dict[str, Any] = {
            "metadata": self.metadata or HarnessMetadata(id="untitled-harness"),
            "extends": self.extends,
            "permissions": self.permissions,
            "components": [ComponentSelection(ref=s.ref, config=s.config) for s in self.components],
        }
        if self.model:
            data["model"] = self.model
        if self.budget:
            data["budget"] = self.budget
        if self.prompt is not None:
            data["prompt"] = self.prompt
        return HarnessConfig.model_validate(data)


class GenerateResponse(BaseModel):
    yaml: str
    ok: bool
    gaps: int
    warnings: int
    errors: int


class HarnessSaveBody(BaseModel):
    """공유 하네스 저장소 upsert 본문 — 웹·VSCode 확장이 같은 백엔드로 저장/동기화.
    스코프(personal|team:<id>)는 쿼리 파라미터로 받는다."""

    name: str = ""
    description: str = ""
    yaml: str = Field(min_length=1)


class ComponentAuthorBody(BaseModel):
    """자연어 → 카탈로그 컴포넌트 초안(스튜디오 빌더). type 으로 skill|mcp|context|hook 선택."""

    prompt: str = Field(min_length=1)
    type: str = "context"
    prior_id: str | None = None


class StudioChatBody(BaseModel):
    """스튜디오 대화 한 턴 — 사용자 메시지. forced_type 은 타입 자동분류를 사용자가 덮어쓸 때(탈출구)."""

    message: str = Field(min_length=1)
    forced_type: str | None = None  # context|skill|mcp|hook — 지정 시 라우터 추론을 무시


class StudioCommitBody(BaseModel):
    """대화의 현재 초안을 카탈로그 구성요소로 저장. type 은 분류 덮어쓰기, name 은 이름 덮어쓰기(선택)."""

    type: str | None = None
    name: str = ""


class StudioRunMsg(BaseModel):
    role: str  # user | assistant
    content: str


class StudioRunBody(BaseModel):
    """조립된 에이전트를 대화로 실행(멀티턴 미리보기) — messages 마지막이 새 user 턴."""

    messages: list[StudioRunMsg] = Field(min_length=1)


class LlmSettingsBody(BaseModel):
    """앱 LLM/임베딩 키 저장. 키는 생략(None)=유지 · ""=삭제 · 값=교체(암호화 저장).
    provider 는 LLM provider(anthropic|openai). 임베딩은 OpenAI 고정(embedding_key)."""

    provider: str | None = None
    llm_key: str | None = None
    embedding_key: str | None = None
    search_key: str | None = None  # 웹검색(Tavily) 키 — None=유지·""=삭제·값=교체


class ComponentSaveBody(BaseModel):
    """유저 컴포넌트 저장 upsert 본문 — data 는 Component 필드 dict. 스코프는 쿼리 파라미터."""

    name: str = ""
    description: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class TokenCreateBody(BaseModel):
    """PAT 발급 — VSCode·기계 연결용 개인 액세스 토큰. 이름으로 식별(원문은 1회 노출)."""

    name: str = Field(default="", max_length=128)


class DevLoginBody(BaseModel):
    """개발용 로그인(HARNESS_DEV_AUTH=on) — 실제 OAuth 앱 없이 이메일로 세션 발급."""

    email: str = Field(min_length=3, max_length=320)


class TeamCreateBody(BaseModel):
    """자가서브 팀 생성 — 생성자가 owner·첫 멤버."""

    name: str = Field(min_length=1, max_length=64)


class MemberBody(BaseModel):
    """팀 멤버 초대 — email + 역할(owner/editor/viewer, 기본 editor)."""

    email: str = Field(min_length=3)
    role: str = "editor"


class RunRequest(ResolveRequest):
    """런타임 dry-run — 선택 구성 + 사용자 메시지로 요청을 조립하고(키 있으면) 전송.

    `message` 는 사용자 입력(대화 메시지)이다 — harness 의 시스템 프롬프트 블록(`prompt`,
    ResolveRequest 상속)과는 다른 것이라 이름을 분리한다.
    """

    message: str = Field(min_length=1)
