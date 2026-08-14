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


class AdoptResult(BaseModel):
    config: HarnessConfig
    unknown_mcp: list[str]  # 카탈로그에 없는 서버 id(=①레지스트리 수확 후보)
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

    body = _prompt_body(files)
    prompt = PromptSpec(system=[PromptLayer(inline=body)]) if body else None
    if not body:
        notes.append("프롬프트 본문 없음(CLAUDE.md/.mdc 미발견) — prompt 블록 생략")

    config = HarnessConfig(
        metadata=HarnessMetadata(id=harness_id, name="adopted harness"),
        model=_model(files),
        components=components,
        prompt=prompt,
    )
    return AdoptResult(config=config, unknown_mcp=unknown, notes=notes)


def adopt_dir(source: str | Path, registry: Registry, harness_id: str = "adopted") -> AdoptResult:
    """디스크 디렉터리에서 알려진 네이티브 파일을 읽어 adopt."""
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
    return adopt(files, registry, harness_id)
