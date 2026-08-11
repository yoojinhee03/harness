"""병합/상속 규칙 — 설계: 리졸버 검증 로직 §4.

- 스칼라 (version, latency, model.* 등): 자식이 부모를 오버라이드.
- 리스트 (선택 목록 등): 기본 합집합(union).
- 맵 (config, permissions): 깊은 병합(deep merge), 자식 키 우선.
- 제약 (conflicts_with, exclusive_group): 항상 합집합(안전 우선).

harness.yaml `extends` 는 base harness 를 자식이 오버라이드하는 형태로 병합한다.
"""

from __future__ import annotations

from typing import Any

from .models import HarnessConfig


def deep_merge_map(base: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """맵 깊은 병합 — 자식 키 우선. 중첩 dict 는 재귀 병합."""
    out = dict(base)
    for k, v in child.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge_map(out[k], v)
        else:
            out[k] = v
    return out


def merge_harness_configs(base: HarnessConfig, child: HarnessConfig) -> HarnessConfig:
    """base 를 child 가 오버라이드해 병합한 새 HarnessConfig 를 만든다.

    - components: id 기준 합집합. 같은 id 는 자식이 이김(version/config 오버라이드).
    - model: 스칼라 오버라이드(자식 필드가 이김).
    - permissions: 맵 깊은 병합(자식 우선). 축소 방향 검증은 리졸버 8단계에서.
    - budget: 자식이 있으면 자식, 없으면 base.
    """
    # components — id 기준 병합, 자식 우선
    merged_components = {sel.id: sel for sel in base.components}
    for sel in child.components:
        merged_components[sel.id] = sel

    # model — child 가 *명시한 필드만* base 위에 오버라이드한다. child 가 model 블록을 아예
    #   안 주면 base 를 그대로 유지. (ModelConfig 는 전부 기본값이라 `child.model` 을 통째로
    #   채택하면 base.model 이 항상 폐기되는 버그가 있었다 — budget/prompt 와 동일한 병합 의미로 교정.)
    if "model" in child.model_fields_set:
        merged_model = base.model.model_copy(update=child.model.model_dump(exclude_unset=True))
    else:
        merged_model = base.model

    merged_permissions = deep_merge_map(base.permissions, child.permissions)

    return HarnessConfig(
        apiVersion=child.apiVersion,
        kind=child.kind,
        metadata=child.metadata,
        extends=None,  # 병합 후엔 상속 해소됨
        model=merged_model,
        permissions=merged_permissions,
        components=list(merged_components.values()),
        budget=child.budget or base.budget,
        prompt=child.prompt or base.prompt,  # 자식 prompt 블록이 있으면 우선, 없으면 base
    )
