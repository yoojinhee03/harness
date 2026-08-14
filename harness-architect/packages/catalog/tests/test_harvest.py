"""MCP 자동수확 테스트 — 서버 디스크립터 → 카탈로그 컴포넌트.

capability 를 vocab 휴리스틱으로 오프라인 추론하고, 결과가 카탈로그 스키마로 라운드트립되는지
(수확물이 그대로 로드 가능한지) 확인한다.
"""

from __future__ import annotations

from harness_catalog import ServerDescriptor, component_to_yaml, harvest, harvest_component, uncovered
from harness_resolver import Component


def test_harvest_infers_capabilities_from_text():
    """설명 텍스트로 capability 를 추론한다(gitlab → vcs.code-hosting)."""
    desc = ServerDescriptor(
        id="gitlab-mcp", name="GitLab", description="GitLab 저장소·이슈·머지 리퀘스트 접근",
        keywords=["gitlab", "git", "repo"], command="npx", args=["-y", "@x/gitlab"],
    )
    comp = harvest_component(desc)
    assert comp.type == "mcp"
    assert "vcs.code-hosting" in comp.capability_tags
    assert comp.provides == comp.capability_tags
    assert comp.mcp is not None and comp.mcp.transport == "stdio" and comp.mcp.command == "npx"


def test_harvest_remote_url_server():
    desc = ServerDescriptor(id="remote-mcp", name="Remote", description="웹 검색", url="https://mcp.example/x")
    comp = harvest_component(desc)
    assert comp.mcp is not None and comp.mcp.transport == "http" and comp.mcp.url == "https://mcp.example/x"


def test_uncovered_flags_unknown_capability():
    """어휘에 안 걸리는 서버는 uncovered 로 표기(수동 큐레이션/어휘 확장 후보)."""
    comps = harvest([ServerDescriptor(id="zzz-mcp", name="Zzz", description="블라블라 알 수 없는 도구")])
    assert "zzz-mcp" in uncovered(comps)


def test_harvested_component_roundtrips_schema():
    """수확 YAML 이 그대로 Component 스키마로 다시 로드된다(카탈로그 편입 가능)."""
    import yaml

    comp = harvest_component(
        ServerDescriptor(id="slack-mcp", name="Slack", description="슬랙 메시지 전송·알림", command="npx")
    )
    reloaded = Component.model_validate(yaml.safe_load(component_to_yaml(comp)))
    assert reloaded.id == "slack-mcp" and reloaded.type == "mcp"
    assert "comms.messaging" in reloaded.capability_tags
