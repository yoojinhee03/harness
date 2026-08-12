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

    @classmethod
    def from_component(cls, c: Component) -> CatalogItem:
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


class RegisterBody(BaseModel):
    """사용자 등록 — handle 로 계정 생성, 토큰 발급(멀티테넌시 신원)."""

    handle: str = Field(min_length=1, max_length=64)


class TeamCreateBody(BaseModel):
    """자가서브 팀 생성 — 생성자가 owner·첫 멤버."""

    name: str = Field(min_length=1, max_length=64)


class MemberBody(BaseModel):
    """팀 멤버 초대 — handle 로 지정."""

    handle: str = Field(min_length=1)


class RunRequest(ResolveRequest):
    """런타임 dry-run — 선택 구성 + 사용자 메시지로 요청을 조립하고(키 있으면) 전송.

    `message` 는 사용자 입력(대화 메시지)이다 — harness 의 시스템 프롬프트 블록(`prompt`,
    ResolveRequest 상속)과는 다른 것이라 이름을 분리한다.
    """

    message: str = Field(min_length=1)
