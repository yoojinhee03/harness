"""MCP 레지스트리 자동수확 — 서버 디스크립터 → 카탈로그 컴포넌트 (진행 플랜: 카탈로그 생애주기).

공개 MCP 레지스트리(modelcontextprotocol/servers · Smithery · Glama · mcp.so 등)의 서버 메타를
우리 카탈로그 `Component`(type=mcp)로 변환한다. `capability_tags`/`provides` 는 통제 어휘
휴리스틱으로 **오프라인 추론**(LLM 업그레이드는 후속). 손큐레이션 13개 → 생태계 규모로 키우는
파이프라인 — "그라운딩된 추천"의 근거를 확장한다.
"""

from __future__ import annotations

from harness_resolver import Component
from harness_resolver.models import McpServerSpec
from pydantic import BaseModel, Field

from .vocabulary import extract_capabilities_heuristic


class ServerDescriptor(BaseModel):
    """레지스트리 서버 메타(공통 최소 형태). 레지스트리별 어댑터가 이 형태로 정규화한다."""

    id: str
    name: str = ""
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    version: str = "0.1.0"
    # 실행 스펙(둘 중 하나): stdio(command) 또는 remote(url)
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None


def _spec(desc: ServerDescriptor) -> McpServerSpec:
    if desc.url:
        return McpServerSpec(transport="http", url=desc.url)
    return McpServerSpec(transport="stdio", command=desc.command or "npx", args=desc.args, env=desc.env)


def harvest_component(desc: ServerDescriptor) -> Component:
    """디스크립터 → Component. capability 는 name+description+keywords 로 휴리스틱 추론."""
    text = " ".join([desc.name, desc.description, *desc.keywords])
    caps = extract_capabilities_heuristic(text)
    return Component(
        id=desc.id,
        type="mcp",
        name=desc.name or desc.id,
        version=desc.version,
        summary=desc.description[:120],
        description=desc.description,
        keywords=desc.keywords,
        capability_tags=caps,
        provides=caps,
        mcp=_spec(desc),
    )


def harvest(descriptors: list[ServerDescriptor]) -> list[Component]:
    return [harvest_component(d) for d in descriptors]


def uncovered(components: list[Component]) -> list[str]:
    """capability 를 하나도 추론하지 못한 컴포넌트 id — 어휘 확장/수동 큐레이션 후보(정직 표기)."""
    return [c.id for c in components if not c.capability_tags]


def component_to_yaml(component: Component) -> str:
    """수확된 Component → 카탈로그 YAML 텍스트(기본값·None 생략)."""
    import yaml

    doc = component.model_dump(exclude_defaults=True, exclude_none=True)
    text: str = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    return text
