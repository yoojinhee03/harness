"""레시피 테스트 (Phase 9-3) — 시작점이 실제로 작동하는가.

**깨진 레시피는 없는 것보다 나쁘다.** 처음 쓰는 사람이 맨 먼저 만나는 게 레시피인데 그게
resolve 도 안 되면 제품 신뢰가 거기서 끝난다. 그래서 시드 카탈로그에 대고 전부 실행해 본다.
"""

from __future__ import annotations

import pytest
import yaml
from harness_catalog import build_registry, load_recipe, load_recipes
from harness_catalog.recipes import resolve_recipes_dir
from harness_resolver import resolve


@pytest.fixture(scope="module")
def recipes():
    return load_recipes()


@pytest.fixture(scope="module")
def registry():
    return build_registry()


def test_seed_recipes_exist(recipes):
    """플랜이 요구한 3 시나리오 — PR 리뷰·이슈 분류·문서 초안."""
    assert {r.meta.name for r in recipes} >= {"pr-review", "issue-triage", "doc-draft"}


def test_every_recipe_resolves_cleanly(recipes, registry):
    """모든 레시피가 시드 카탈로그에서 에러 없이 resolve 돼야 한다."""
    broken = []
    for r in recipes:
        result = resolve(r.config, registry)
        if not result.ok:
            broken.append((r.meta.name, [d.message for d in result.diagnostics.errors]))
    assert broken == []


def test_no_recipe_has_gaps(recipes, registry):
    """gap 있는 레시피를 시작점으로 주면 '만들자마자 미충족'을 만난다 — 큐레이션 실패다."""
    with_gaps = {
        r.meta.name: [g.capability for g in resolve(r.config, registry).diagnostics.gaps]
        for r in recipes
        if resolve(r.config, registry).diagnostics.gaps
    }
    assert with_gaps == {}


def test_recipes_only_reference_catalog_components(recipes, registry):
    """레시피는 카탈로그 위의 큐레이션이다 — 새 컴포넌트를 지어내면 안 된다."""
    for r in recipes:
        for sel in r.config.components:
            version = sel.ref.split("@", 1)[1] if "@" in sel.ref else None
            assert registry.get(sel.id, version) is not None, f"{r.meta.name}: {sel.ref} 없음"


def test_recipe_components_are_pinned(recipes):
    """시작점은 버전을 박아 준다 — 미핀이면 만들자마자 doctor 가 드리프트로 잡는다."""
    for r in recipes:
        for sel in r.config.components:
            assert "@" in sel.ref, f"{r.meta.name}: '{sel.ref}' 에 버전이 없다"


def test_recipe_metadata_is_usable(recipes):
    """목록 화면이 쓸 최소 정보 — 제목·설명이 비면 카드가 빈칸이 된다."""
    for r in recipes:
        assert r.meta.title and r.meta.description, r.meta.name
        assert r.meta.name == r.meta.name.strip().lower()


def test_load_recipe_by_name(registry):
    r = load_recipe("pr-review")
    assert r.meta.title == "PR 리뷰 봇"
    assert resolve(r.config, registry).ok


def test_missing_recipe_lists_alternatives():
    """조용한 빈 결과 대신 가능한 이름을 알려준다."""
    with pytest.raises(KeyError, match="pr-review"):
        load_recipe("nope")


def test_non_recipe_file_is_rejected(tmp_path):
    """`harness:` 블록 없는 파일을 레시피로 읽지 않는다(오투입 방어)."""
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump({"metadata": {"id": "x"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="레시피 형식"):
        load_recipes(tmp_path)


def test_recipes_dir_is_beside_the_catalog():
    """컴포넌트와 같은 생애주기를 갖도록 카탈로그 옆에 둔다(ref 가 함께 움직여야 한다)."""
    d = resolve_recipes_dir()
    assert d.name == "recipes" and d.parent.name == "harness-catalog"
