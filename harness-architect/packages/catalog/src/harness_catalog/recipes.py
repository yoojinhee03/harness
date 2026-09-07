"""레시피 — 검증된 시작점 (진행 플랜 Phase 9-3).

레시피는 **카탈로그 위의 큐레이션**이다. 새 컴포넌트를 만들지 않고 이미 있는 것들의 검증된
조합만 담는다. 콜드스타트("무엇부터 골라야 하나")를 없애는 게 목적이지, 정답을 주는 게 아니다 —
받아서 자기 팀에 맞게 고치라고 있는 것이다.

**데이터는 카탈로그 옆에 산다**(`harness-catalog/recipes/`). 컴포넌트와 같은 생애주기를 갖고,
레시피가 참조하는 ref 가 카탈로그와 함께 움직여야 하기 때문이다(어긋나면 `doctor` 가 잡는다).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from harness_resolver import HarnessConfig
from pydantic import BaseModel, Field


class RecipeMeta(BaseModel):
    """레시피 카드 한 장 분량 — 목록에서 고르는 데 필요한 것만."""

    name: str  # 파일명·CLI 인자와 같은 슬러그
    title: str = ""
    description: str = ""
    use_when: list[str] = Field(default_factory=list)


class Recipe(BaseModel):
    meta: RecipeMeta
    config: HarnessConfig


def resolve_recipes_dir(explicit: str | None = None) -> Path:
    """레시피 디렉터리를 찾는다. 탐색 규칙은 `loader.resolve_catalog_dir` 와 같은 결이다."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("RECIPES_DIR")
    if env:
        return Path(env).expanduser().resolve()
    for start in (Path.cwd(), Path(__file__).resolve()):
        for ancestor in [start, *start.parents]:
            for candidate in (
                ancestor / "harness-catalog" / "recipes",
                ancestor.parent / "harness-catalog" / "recipes",
            ):
                if candidate.is_dir():
                    return candidate.resolve()
    raise FileNotFoundError(
        "레시피 디렉터리를 찾을 수 없습니다 — RECIPES_DIR 를 설정하거나 "
        "harness-catalog/recipes 를 두세요."
    )


def _parse(path: Path) -> Recipe:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict) or "harness" not in doc:
        raise ValueError(f"{path}: 레시피 형식이 아닙니다(`harness:` 블록 필요).")
    meta_doc = doc.get("recipe") or {}
    meta_doc.setdefault("name", path.stem)
    return Recipe(meta=RecipeMeta.model_validate(meta_doc), config=HarnessConfig.model_validate(doc["harness"]))


def load_recipes(directory: str | Path | None = None) -> list[Recipe]:
    """디렉터리의 모든 레시피. 이름순."""
    d = directory if isinstance(directory, Path) else resolve_recipes_dir(directory)
    return [_parse(p) for p in sorted(Path(d).glob("*.yaml"))]


def load_recipe(name: str, directory: str | Path | None = None) -> Recipe:
    """이름으로 하나. 없으면 가능한 이름을 알려주며 실패한다(조용한 빈 결과보다 낫다)."""
    recipes = load_recipes(directory)
    for r in recipes:
        if r.meta.name == name:
            return r
    available = ", ".join(r.meta.name for r in recipes) or "(없음)"
    raise KeyError(f"레시피 '{name}' 를 찾을 수 없습니다. 가능: {available}")
