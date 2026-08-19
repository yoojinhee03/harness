"""harness MCP 서버 — 에디터 안에서 recommend → resolve → eject.

설계: 진행 플랜 배포(MCP). 백엔드(FastAPI) 없이 in-process 로 패키지(resolver·catalog·
runtime)를 감싼다. `POST /recommend·/resolve·/eject` 와 같은 로직을 MCP 툴로 노출해,
Claude Code·Cursor·Claude Desktop 등 어떤 MCP 클라이언트에서도 호출할 수 있게 한다.
eject 산출물(`.claude/`)이 떨어지는 바로 그 에디터 안에서 루프가 닫힌다.

카탈로그는 `CATALOG_DIR` → 옆 폴더(`../harness-catalog/components`) → `catalog-data/components`
순으로 자동 탐색한다(loader 규약). 못 찾으면 빈 레지스트리로 기동한다(recommend 는 빈 결과).

노출 툴:
    recommend_harness(description, top_k)          설명 → 카탈로그 근거 추천
    list_catalog(type, capability)                 컴포넌트 카탈로그 나열/필터
    resolve_harness(harness_yaml)                  harness.yaml 검증(진단)
    eject_harness(harness_yaml, target, out_dir)   네이티브 포맷 컴파일(옵션: 디스크에 쓰기)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from harness_catalog import LiveRecommender, Recommender, build_registry, federate, resolve_catalog_dir
from harness_resolver import HarnessConfig, InMemoryRegistry, Registry, resolve
from harness_runtime import available_targets, emit
from mcp.server.mcpserver import MCPServer

log = logging.getLogger("harness_mcp")

mcp = MCPServer(name="harness", version="0.1.0")

# 레지스트리·추천기는 임베딩 인덱스 비용이 있어 프로세스당 한 번만 만든다(지연 초기화).
# 라이브 연동 시 LiveRecommender 가 레지스트리 generation 변화만큼만 재인덱싱한다.
_registry: Registry | None = None
_recommender: LiveRecommender | None = None


def get_registry() -> Registry:
    global _registry
    if _registry is None:
        try:
            catalog_dir = resolve_catalog_dir()
            local = build_registry(catalog_dir)
            log.info("카탈로그 로드: %d개 (%s)", len(local.all()), catalog_dir)
        except FileNotFoundError as exc:
            log.warning("카탈로그를 찾지 못함 — 빈 레지스트리로 기동: %s", exc)
            local = InMemoryRegistry([])
        # HARNESS_LIVE_REGISTRY=on 이면 공식 MCP 레지스트리를 라이브로 합친다(off 면 로컬 그대로).
        _registry = federate(local)
        if _registry is not local:
            log.info("라이브 레지스트리 연동: 총 %d개(로컬+공식 MCP 레지스트리)", len(_registry.all()))
    return _registry


def get_recommender() -> Recommender:
    global _recommender
    if _recommender is None:
        _recommender = LiveRecommender(get_registry())
    return _recommender.get()  # 라이브 내용이 바뀌었으면 재인덱싱, 아니면 캐시 재사용


def _load_config(harness_yaml: str) -> HarnessConfig:
    return HarnessConfig.model_validate(yaml.safe_load(harness_yaml))


def _diagnostics(d: Any) -> dict[str, list[dict[str, Any]]]:
    """Diagnostics 를 errors/gaps/warnings 3분류로 펼친다(내부 표현은 단일 items 리스트)."""
    return {
        "errors": [x.model_dump() for x in d.errors],
        "gaps": [x.model_dump() for x in d.gaps],
        "warnings": [x.model_dump() for x in d.warnings],
    }


def recommend_harness(description: str, top_k: int = 6) -> dict[str, Any]:
    """프로젝트를 자연어로 설명하면 카탈로그에 근거해 하네스 구성요소를 추천한다.

    Skill·MCP·Context·Hook 중 요구 능력에 맞는 후보를 검색·랭킹한다. 반환: 추출된 요구 능력,
    추천 목록(근거·점수·비용·충돌·auth 여부), `gaps`(카탈로그가 못 채운 요구 능력), 타입별 그룹.

    추천 후보는 **실제 카탈로그 컴포넌트뿐**이다(컴포넌트를 지어내지 않는다). 여기서 고른 id 들을
    harness.yaml 의 components[].ref 로 그대로 넘기면 된다. 카탈로그에 없는 능력은 발명하지 않고
    `gaps` 로 나온다 — 각 gap 은 필요한 capability·이유·이를 채울 컴포넌트 타입(suggested_type)을 담는다.
    "찾은 N개 + gap M개"의 부분 커버리지는 실패가 아니라 정상 응답이다.
    """
    result: dict[str, Any] = get_recommender().recommend(description, top_k=top_k).model_dump()
    return result


def list_catalog(type: str | None = None, capability: str | None = None) -> list[dict[str, Any]]:
    """추천 대상 컴포넌트 카탈로그를 나열한다.

    type 으로 종류(skill|mcp|context|hook)를, capability 로 제공/태그 능력을 필터한다.
    """
    comps = get_registry().all()
    if type:
        comps = [c for c in comps if c.type == type]
    if capability:
        comps = [c for c in comps if capability in c.provides or capability in c.capability_tags]
    return [
        {
            "id": c.id,
            "type": c.type,
            "name": c.name,
            "version": c.version,
            "summary": c.summary,
            "provides": c.provides,
            "requires": c.requires,
            "context_tokens": c.cost.context_tokens,
            "added_tools": c.cost.added_tools,
        }
        for c in comps
    ]


def resolve_harness(harness_yaml: str) -> dict[str, Any]:
    """harness.yaml 텍스트를 검증(진단)한다.

    참조 해소 → 상속 병합 → 능력 충족 → 충돌 감지 → 예산 확인 → 훅 순서 → 권한 수집을 순수
    함수로 확인한다. 반환: ok, diagnostics(errors/gaps/warnings), resolved 요약(컴포넌트·비용·
    프롬프트 해시). gap(미충족 requires)은 에러가 아니라 추천기로 되돌릴 신호다.
    """
    result = resolve(_load_config(harness_yaml), get_registry())
    out: dict[str, Any] = {"ok": result.ok, "diagnostics": _diagnostics(result.diagnostics)}
    if result.resolved is not None:
        r = result.resolved
        out["resolved"] = {
            "components": [rc.id for rc in r.components],
            "context_tokens": r.cost.context_tokens,
            "added_tools": r.cost.added_tools,
            "prompt_hash": r.prompt.hash if r.prompt is not None else None,
        }
    return out


def eject_harness(
    harness_yaml: str, target: str = "claude-code", out_dir: str | None = None
) -> dict[str, Any]:
    """검증된 하네스를 런타임 네이티브 포맷으로 컴파일한다.

    out_dir 을 주면 그 폴더에 파일을 쓴다(예: 현재 프로젝트에 `.claude/`·`.mcp.json`·`CLAUDE.md`
    생성). 없으면 파일 트리(경로→내용)를 반환한다. resolve 실패 시 진단만 돌려주고 쓰지 않는다.
    target 은 available_targets() 중 하나(현재 'claude-code').
    """
    if target not in available_targets():
        return {"ok": False, "error": f"지원하지 않는 타깃: {target}", "targets": available_targets()}
    result = resolve(_load_config(harness_yaml), get_registry())
    if not result.ok or result.resolved is None:
        return {
            "ok": False,
            "target": target,
            "diagnostics": _diagnostics(result.diagnostics),
            "files": None,
        }
    tree = emit(result.resolved, target)
    if out_dir is None:
        return {"ok": True, "target": target, "files": tree}
    out = Path(out_dir).expanduser()
    written: list[str] = []
    for path in sorted(tree):
        dest = out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(tree[path], encoding="utf-8")
        written.append(str(dest))
    return {"ok": True, "target": target, "out_dir": str(out), "written": written}


# 툴 등록 — 핵심 로직은 순수 함수로 두고(테스트 용이) 여기서 MCP 툴로 노출한다.
for _fn in (recommend_harness, list_catalog, resolve_harness, eject_harness):
    mcp.tool()(_fn)


def main() -> None:
    """stdio 트랜스포트로 MCP 서버를 기동한다(Claude Code 등이 프로세스로 띄운다)."""
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
