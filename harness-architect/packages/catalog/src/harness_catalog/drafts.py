"""결핍 → 카탈로그 컴포넌트 초안 (`verify --fix` 의 코어).

`verify` 가 내는 결핍은 두 종류인데 **고칠 수 있는 것은 한 종류뿐이다.**

  · `unknown_mcp` / `unknown_skills` — 레포에 있는데 카탈로그가 모르는 것. 레포가 **데이터를
    이미 갖고 있으므로**(`.mcp.json` 항목, `SKILL.md` 본문) 기계적으로 초안을 만들 수 있다.
    지어내는 게 아니라 **옮겨 적는 것**이다.
  · `capability_gap` — 아무도 제공하지 않는 능력. 이건 새 컴포넌트를 *발명*해야 하므로 여기서
    다루지 않는다. 시딩 큐(GapDemand)와 스튜디오 저작 루프의 몫이다.

**초안이지 등록이 아니다.** 카탈로그에 자동으로 넣지 않는다 — 무엇을 공유 카탈로그에 올릴지는
큐레이션 결정이고, 수확 휴리스틱이 붙인 caps 는 사람이 검토해야 한다(doctor 가 제안만 하고
고치지 않는 것과 같은 이유).

**순수하다.** 파일 트리(dict)와 미지 id 목록을 받아 {경로: YAML} 을 돌려준다. 디스크를 모른다.
"""

from __future__ import annotations

import json
import re

from harness_resolver import Component

from .harvest import ServerDescriptor, component_to_yaml, harvest_component
from .vocabulary import extract_capabilities_heuristic

# adopt 가 스킬 id 를 뽑는 경로와 같은 규칙(`.claude/skills/<id>/SKILL.md`).
_SKILL_PATH = re.compile(r"^\.claude/skills/([^/]+)/SKILL\.md$")
# SKILL.md frontmatter 의 description(있으면 summary 로).
_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?", re.S)
_DESC_LINE = re.compile(r"^\s*description\s*:\s*(.+?)\s*$", re.M)


def _mcp_servers(files: dict[str, str]) -> dict[str, dict[str, object]]:
    """`.mcp.json`/`.cursor/mcp.json` 의 mcpServers. 깨진 JSON 은 빈 dict(초안 생성이 죽지 않게)."""
    for path in (".mcp.json", ".cursor/mcp.json"):
        raw = files.get(path)
        if not raw:
            continue
        try:
            servers = json.loads(raw).get("mcpServers", {})
        except (ValueError, AttributeError):
            continue
        if isinstance(servers, dict):
            return {str(k): v for k, v in servers.items() if isinstance(v, dict)}
    return {}


def draft_mcp(server_id: str, entry: dict[str, object]) -> Component:
    """`.mcp.json` 항목 → mcp 컴포넌트 초안. 레포에 있는 실행 스펙을 그대로 옮긴다."""
    args = entry.get("args")
    env = entry.get("env")
    desc = ServerDescriptor(
        id=server_id,
        name=server_id,
        # 설명은 레포에 없다 — 지어내지 않고 비워 두고, 사람이 채우라고 표시한다.
        description="",
        command=str(entry["command"]) if entry.get("command") else None,
        args=[str(a) for a in args] if isinstance(args, list) else [],
        env={str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {},
        url=str(entry["url"]) if entry.get("url") else None,
    )
    return harvest_component(desc)


def _skill_summary(body: str) -> str:
    """SKILL.md frontmatter 의 description. 없으면 본문 첫 줄."""
    m = _FRONTMATTER.match(body)
    if m:
        d = _DESC_LINE.search(m.group(1))
        if d:
            return d.group(1).strip().strip("\"'")[:120]
    for line in _FRONTMATTER.sub("", body).splitlines():
        if line.strip() and not line.startswith("#"):
            return line.strip()[:120]
    return ""


def draft_skill(skill_id: str, body: str) -> Component:
    """`SKILL.md` → skill 컴포넌트 초안. 본문을 그대로 담고 caps 는 휴리스틱 추론(검토 필요)."""
    summary = _skill_summary(body)
    stripped = _FRONTMATTER.sub("", body).strip()
    return Component(
        id=skill_id,
        type="skill",
        name=skill_id,
        version="0.1.0",
        summary=summary,
        description=summary,
        capability_tags=extract_capabilities_heuristic(f"{skill_id} {summary} {stripped[:500]}"),
        entrypoint=f"skills/{skill_id}/SKILL.md",
        body=stripped,
    )


def drafts_from_native(
    files: dict[str, str],
    unknown_mcp: list[str] | None = None,
    unknown_skills: list[str] | None = None,
) -> dict[str, str]:
    """미지 컴포넌트 → {파일명: 카탈로그 YAML} 초안.

    `unknown_*` 를 생략하면 트리에서 발견되는 전부를 대상으로 한다(verify 없이도 쓸 수 있게).
    id 에 슬래시가 있으면 파일명에서 `__` 로 바꾼다(연합 레지스트리 역DNS id 대비).
    """
    servers = _mcp_servers(files)
    mcp_ids = list(unknown_mcp) if unknown_mcp is not None else list(servers)

    skills_in_tree = {m.group(1): files[p] for p in files if (m := _SKILL_PATH.match(p))}
    skill_ids = list(unknown_skills) if unknown_skills is not None else list(skills_in_tree)

    out: dict[str, str] = {}
    for sid in sorted(set(mcp_ids)):
        entry = servers.get(sid)
        if entry is None:
            continue  # 트리에 스펙이 없으면 옮겨 적을 게 없다 — 지어내지 않는다.
        out[f"{_safe(sid)}.yaml"] = component_to_yaml(draft_mcp(sid, entry))
    for sid in sorted(set(skill_ids)):
        body = skills_in_tree.get(sid)
        if body is None:
            continue
        out[f"{_safe(sid)}.yaml"] = component_to_yaml(draft_skill(sid, body))
    return out


def _safe(component_id: str) -> str:
    return component_id.replace("/", "__")
