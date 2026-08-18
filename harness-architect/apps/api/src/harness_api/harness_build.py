"""harness.yaml 직렬화 — HarnessConfig → yaml 텍스트, 그리고 초안 구성요소들 → 에이전트(하네스).

main 과 orchestrator 가 함께 쓰므로 순환 import 를 피해 여기로 뺐다. 스튜디오의 '하네스 조립'은
대화에서 만든 여러 구성요소(초안)를 components 로 선택하는 harness.yaml 을 생성하는 것이다.
"""

from __future__ import annotations

from typing import Any, cast

import yaml
from harness_resolver import Component, ComponentSelection, HarnessConfig, HarnessMetadata

from .store import safe_id


def to_harness_yaml(config: HarnessConfig) -> str:
    """HarnessConfig → harness.yaml 텍스트 (스펙 §2 구조)."""
    doc: dict[str, Any] = {
        "apiVersion": config.apiVersion,
        "kind": config.kind,
        "metadata": config.metadata.model_dump(exclude_defaults=False),
    }
    if config.extends:
        doc["extends"] = config.extends
    doc["model"] = config.model.model_dump()
    if config.prompt is not None:
        doc["prompt"] = config.prompt.model_dump(exclude_defaults=True, exclude_none=True)
    if config.permissions:
        doc["permissions"] = config.permissions
    doc["components"] = [
        ({"ref": s.ref, "config": s.config} if s.config else {"ref": s.ref}) for s in config.components
    ]
    if config.budget:
        doc["budget"] = config.budget.model_dump()
    return cast(str, yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))


def parse_harness_yaml(text: str) -> HarnessConfig:
    """harness.yaml 텍스트 → HarnessConfig (검증·eject 를 저장된 하네스에 적용하려고 역파싱)."""
    return HarnessConfig.model_validate(yaml.safe_load(text) or {})


def build_harness_yaml(components: list[Component], name: str, description: str = "") -> str:
    """초안 구성요소들 → 이들을 components 로 선택하는 harness.yaml (에이전트 스펙)."""
    meta = HarnessMetadata(id=safe_id(name) or "agent", name=name or "에이전트", description=description)
    config = HarnessConfig(
        metadata=meta,
        components=[ComponentSelection(ref=f"{c.id}@{c.version}") for c in components],
    )
    return to_harness_yaml(config)
