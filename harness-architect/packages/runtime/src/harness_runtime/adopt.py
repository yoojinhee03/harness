"""역방향 adopt — 런타임 네이티브 설정 → HarnessConfig(IR). eject 의 역함수 (진행 플랜 Phase 7).

기존 `.claude/`·`.cursor/` 트리를 읽어 검증·이식 가능한 harness.yaml 로 되돌린다. eject 가 손실
변환이므로 adopt 는 **구조적으로 식별 가능한 것만** 복원한다(환각 금지):
- `.mcp.json` / `.cursor/mcp.json` mcpServers → 카탈로그에 있으면 `ref`, 없으면 unknown(=①수확 후보)
- `.claude/settings.json` model → `model.name`
- `CLAUDE.md` / `.cursor/rules/*.mdc` 본문 → `prompt.system` inline (컴포넌트 구조는 텍스트로 흡수)

결과 config 는 다시 resolve·eject 가능 → 라운드트립(eject∘adopt ≈ 식별 가능부 항등).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from harness_resolver import (
    ComponentSelection,
    HarnessConfig,
    HarnessMetadata,
    ModelConfig,
    PromptLayer,
    PromptSpec,
    Registry,
)
from pydantic import BaseModel

_GEN_HEADER = re.compile(r"^<!--.*?-->\n*", re.S)  # eject 가 CLAUDE.md 에 넣는 생성 헤더
_MDC_FRONTMATTER = re.compile(r"^---\n.*?\n---\n*", re.S)  # .cursor .mdc frontmatter
_SKILL_KEY = re.compile(r"^\.claude/skills/([^/]+)/SKILL\.md$")  # 스킬 파일 경로 → id 추출

# Claude Code 훅 이벤트 → 하네스 이벤트(eject 역방향). eject 가 after_request 를 드롭하므로
# 그 이벤트는 라운드트립 복원이 불가하다(claude_code._HOOK_EVENT_MAP 의 역, MAPPING.md).
_CC_HOOK_REVERSE = {
    "PreToolUse": "before_tool_call",
    "PostToolUse": "after_tool_call",
    "UserPromptSubmit": "before_request",
    "Stop": "after_response",
}


class AdoptResult(BaseModel):
    config: HarnessConfig
    unknown_mcp: list[str]  # 카탈로그에 없는 서버 id(=①레지스트리 수확 후보)
    unknown_skills: list[str] = []  # 카탈로그에 없는 SKILL.md id(=수확/저작 후보)
    hooks: list[str] = []  # 흡수한 훅 이벤트(역매핑) — 카탈로그 id 가 없어 컴포넌트로는 미해석
    notes: list[str] = []


def _mcp_servers(files: dict[str, str]) -> dict[str, object]:
    for path in (".mcp.json", ".cursor/mcp.json"):
        raw = files.get(path)
        if raw:
            servers = json.loads(raw).get("mcpServers", {})
            return dict(servers) if isinstance(servers, dict) else {}
    return {}


def _model(files: dict[str, str]) -> ModelConfig:
    raw = files.get(".claude/settings.json")
    if raw:
        name = json.loads(raw).get("model")
        if name:
            return ModelConfig(name=str(name))
    return ModelConfig()


def _prompt_body(files: dict[str, str]) -> str:
    md = files.get("CLAUDE.md")
    if md is not None:
        return _GEN_HEADER.sub("", md).strip()
    for path, content in files.items():
        if path.endswith(".mdc"):
            return _MDC_FRONTMATTER.sub("", content).strip()
    return ""


def _skill_ids(files: dict[str, str]) -> list[str]:
    """`.claude/skills/<id>/SKILL.md` 경로에서 id 를 뽑는다(디렉터리명 = 네이티브 스킬 id)."""
    ids = [m.group(1) for path in files if (m := _SKILL_KEY.match(path))]
    return sorted(set(ids))


def _adopt_hooks(files: dict[str, str]) -> tuple[list[str], list[str]]:
    """`.claude/settings.json` 의 hooks → (역매핑된 하네스 이벤트, notes). 값은 데이터로만 취급.

    Claude Code 이벤트를 하네스 이벤트로 역매핑한다. 훅엔 카탈로그 id 가 없어 컴포넌트로는 해석하지
    않고(환각 금지) 이벤트만 흡수한다. after_request 는 eject 가 드롭해 복원 불가(MAPPING.md).
    """
    raw = files.get(".claude/settings.json")
    if not raw:
        return [], []
    try:
        hooks = json.loads(raw).get("hooks", {})
    except (ValueError, AttributeError):
        return [], []
    if not isinstance(hooks, dict):
        return [], []
    events: list[str] = []
    notes: list[str] = []
    for cc_event in hooks:
        mapped = _CC_HOOK_REVERSE.get(cc_event)
        if mapped:
            events.append(mapped)
        else:
            notes.append(f"훅 이벤트 '{cc_event}' 는 하네스 이벤트로 역매핑 불가 — 스킵")
    if events:
        notes.append(
            f"훅 {len(events)}개 이벤트 흡수({', '.join(events)}) — 카탈로그 id 없음(수확/저작 후보). "
            "after_request 는 eject 가 드롭해 복원 불가"
        )
    return sorted(set(events)), notes


def adopt(files: dict[str, str], registry: Registry, harness_id: str = "adopted") -> AdoptResult:
    """네이티브 파일 트리(상대경로→내용)를 HarnessConfig 로 흡수한다."""
    notes: list[str] = []
    components: list[ComponentSelection] = []
    unknown: list[str] = []

    for sid in _mcp_servers(files):
        comp = registry.get(sid, None)
        if comp is not None:
            components.append(ComponentSelection(ref=f"{sid}@{comp.version}"))
        else:
            unknown.append(sid)
    if unknown:
        notes.append(f"카탈로그에 없는 MCP 서버 {len(unknown)}개 — 레지스트리 수확 후보: {unknown}")

    # SKILL.md → 카탈로그 매칭이면 ref(재사용), 아니면 unknown(수확/저작 후보). 이산 파일이라 안전. (5a)
    unknown_skills: list[str] = []
    for skid in _skill_ids(files):
        comp = registry.get(skid, None)
        if comp is not None and comp.type == "skill":
            components.append(ComponentSelection(ref=f"{skid}@{comp.version}"))
        else:
            unknown_skills.append(skid)
    if unknown_skills:
        notes.append(f"카탈로그에 없는 스킬 {len(unknown_skills)}개 — 수확/저작 후보: {unknown_skills}")

    # settings hooks → 이벤트만 역매핑 흡수(카탈로그 id 없어 컴포넌트 미해석, 손실적). (5a)
    hook_events, hook_notes = _adopt_hooks(files)
    notes.extend(hook_notes)

    body = _prompt_body(files)
    prompt = PromptSpec(system=[PromptLayer(inline=body)]) if body else None
    if body:
        # CLAUDE.md/.mdc 본문은 inline 프롬프트로 통째 보존한다 — 섹션→context 분해는 경계를 지어낼
        # 위험이 있어(환각) 기본은 inline. (5a: best-effort 이나 불확실하면 inline 이 안전)
        notes.append("CLAUDE.md/.mdc 본문은 inline prompt 로 보존(섹션→context 분해는 하지 않음)")
    else:
        notes.append("프롬프트 본문 없음(CLAUDE.md/.mdc 미발견) — prompt 블록 생략")

    config = HarnessConfig(
        metadata=HarnessMetadata(id=harness_id, name="adopted harness"),
        model=_model(files),
        components=components,
        prompt=prompt,
    )
    return AdoptResult(
        config=config,
        unknown_mcp=unknown,
        unknown_skills=unknown_skills,
        hooks=hook_events,
        notes=notes,
    )


def read_native_tree(source: str | Path) -> dict[str, str]:
    """디스크 디렉터리에서 알려진 네이티브 설정 파일을 읽어 {상대경로: 내용}. (adopt/verify 공용 입력)"""
    root = Path(source)
    files: dict[str, str] = {}
    for rel in ("CLAUDE.md", ".mcp.json", ".claude/settings.json", ".cursor/mcp.json"):
        p = root / rel
        if p.is_file():
            files[rel] = p.read_text(encoding="utf-8")
    rules = root / ".cursor" / "rules"
    if rules.is_dir():
        for mdc in sorted(rules.glob("*.mdc")):
            files[f".cursor/rules/{mdc.name}"] = mdc.read_text(encoding="utf-8")
    skills = root / ".claude" / "skills"
    if skills.is_dir():
        for skill_md in sorted(skills.glob("*/SKILL.md")):
            files[f".claude/skills/{skill_md.parent.name}/SKILL.md"] = skill_md.read_text(encoding="utf-8")
    return files


def adopt_dir(source: str | Path, registry: Registry, harness_id: str = "adopted") -> AdoptResult:
    """디스크 디렉터리에서 알려진 네이티브 파일을 읽어 adopt."""
    return adopt(read_native_tree(source), registry, harness_id)
