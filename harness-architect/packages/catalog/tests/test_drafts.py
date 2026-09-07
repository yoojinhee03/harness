"""결핍 → 컴포넌트 초안 (`verify --fix` 코어).

**초안은 발명이 아니라 옮겨 적기다.** 레포가 이미 가진 실행 스펙(`.mcp.json`)과 본문(`SKILL.md`)을
카탈로그 형식으로 바꾸는 것뿐이다. 없는 정보(설명 등)는 비워 두고 사람이 채우게 한다 —
지어내면 카탈로그가 오정보로 오염되고, 카탈로그는 이 제품의 최우선 자산이다.
"""

from __future__ import annotations

import yaml
from harness_catalog import draft_mcp, draft_skill, drafts_from_native

MCP_JSON = """{"mcpServers": {
  "known-mcp": {"command": "npx", "args": ["-y", "known"]},
  "internal-jira-mcp": {"command": "node", "args": ["./jira.js"], "env": {"JIRA_TOKEN": "${JIRA_TOKEN}"}},
  "remote-mcp": {"url": "https://mcp.internal/x"}
}}"""

SKILL_MD = """---
description: 스테이징 확인 후 태그를 밀어 배포한다
---
# 배포 런북
1. 스테이징 헬스체크
"""

TREE = {
    ".mcp.json": MCP_JSON,
    ".claude/skills/deploy-runbook/SKILL.md": SKILL_MD,
}


# ── 옮겨 적기: 레포의 실행 스펙이 그대로 보존되는가 ──


def test_mcp_draft_preserves_exact_run_spec():
    """command·args·env 가 손실 없이 옮겨져야 한다 — 안 그러면 초안이 안 돈다."""
    c = draft_mcp("internal-jira-mcp", {"command": "node", "args": ["./jira.js"], "env": {"T": "${T}"}})
    assert c.type == "mcp" and c.id == "internal-jira-mcp"
    assert c.mcp is not None
    assert c.mcp.command == "node" and c.mcp.args == ["./jira.js"]
    assert c.mcp.env == {"T": "${T}"}


def test_mcp_draft_keeps_env_placeholder_not_value():
    """`${VAR}` 표기를 그대로 둔다 — 값을 박으면 초안이 비밀을 품는다."""
    text = drafts_from_native(TREE, ["internal-jira-mcp"], [])["internal-jira-mcp.yaml"]
    assert "${JIRA_TOKEN}" in text


def test_remote_mcp_draft_uses_url_transport():
    c = draft_mcp("remote-mcp", {"url": "https://mcp.internal/x"})
    assert c.mcp is not None and c.mcp.url == "https://mcp.internal/x"
    assert c.mcp.transport in ("http", "sse")


def test_mcp_draft_leaves_description_empty():
    """레포에 설명이 없다 — 지어내지 않고 비워 둬서 사람이 채우게 한다."""
    c = draft_mcp("internal-jira-mcp", {"command": "node"})
    assert c.description == "" and c.summary == ""


def test_skill_draft_takes_summary_from_frontmatter_and_keeps_body():
    c = draft_skill("deploy-runbook", SKILL_MD)
    assert c.type == "skill"
    assert c.summary == "스테이징 확인 후 태그를 밀어 배포한다"
    assert c.body is not None and "스테이징 헬스체크" in c.body
    assert "---" not in c.body  # frontmatter 는 본문에서 제거
    assert c.entrypoint == "skills/deploy-runbook/SKILL.md"


def test_skill_draft_falls_back_to_first_body_line():
    c = draft_skill("no-fm", "# 제목\n\n첫 문단이 요약이 된다\n")
    assert c.summary == "첫 문단이 요약이 된다"


# ── 대상 선택 ──


def test_only_unknown_components_are_drafted():
    """카탈로그가 아는 건 초안으로 뜨지 않는다 — verify 가 미지 목록을 준다."""
    out = drafts_from_native(TREE, ["internal-jira-mcp"], ["deploy-runbook"])
    assert set(out) == {"internal-jira-mcp.yaml", "deploy-runbook.yaml"}
    assert "known-mcp.yaml" not in out


def test_omitting_unknown_lists_drafts_everything_in_tree():
    """verify 없이도 쓸 수 있게 — 목록 생략 시 트리 전체."""
    out = drafts_from_native(TREE)
    assert set(out) == {"known-mcp.yaml", "internal-jira-mcp.yaml", "remote-mcp.yaml", "deploy-runbook.yaml"}


def test_unknown_without_spec_in_tree_is_skipped():
    """트리에 스펙이 없으면 옮겨 적을 게 없다 — 빈 껍데기를 만들지 않는다."""
    assert drafts_from_native(TREE, ["ghost-mcp"], []) == {}


def test_slashed_id_is_filename_safe():
    """연합 레지스트리 역DNS id(`ns/name`)가 경로를 만들지 않게."""
    tree = {".mcp.json": '{"mcpServers": {"io.github.acme/srv": {"command": "npx"}}}'}
    out = drafts_from_native(tree)
    assert set(out) == {"io.github.acme__srv.yaml"}


# ── 견고성 ──


def test_broken_mcp_json_does_not_crash():
    """깨진 JSON 때문에 --fix 가 죽으면 안 된다(스킬 초안은 계속 나와야 한다)."""
    tree = {".mcp.json": "{not json", ".claude/skills/s/SKILL.md": "# s\n본문\n"}
    out = drafts_from_native(tree)
    assert set(out) == {"s.yaml"}


def test_cursor_mcp_json_is_also_read():
    tree = {".cursor/mcp.json": '{"mcpServers": {"c-mcp": {"command": "npx"}}}'}
    assert set(drafts_from_native(tree)) == {"c-mcp.yaml"}


def test_drafts_are_valid_catalog_yaml():
    """초안이 카탈로그 스키마로 다시 읽혀야 한다 — 아니면 옮겨 붙일 수 없다."""
    from harness_resolver import Component

    for text in drafts_from_native(TREE).values():
        Component.model_validate(yaml.safe_load(text))
