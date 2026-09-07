"""harness.yaml 직렬화 — HarnessConfig → yaml 텍스트, 그리고 초안 구성요소들 → 에이전트(하네스).

main 과 orchestrator 가 함께 쓰므로 순환 import 를 피해 여기로 뺐다. 스튜디오의 '하네스 조립'은
대화에서 만든 여러 구성요소(초안)를 components 로 선택하는 harness.yaml 을 생성하는 것이다.
"""

from __future__ import annotations

from typing import Any, cast

import yaml
from harness_resolver import Component, ComponentSelection, HarnessConfig, HarnessMetadata

from .store import safe_id

# 자기식별 스키마 태그 — Harness Protocol v1(harnessprotocol.io) 과 같은 파일명(harness.yaml)을
# 쓰더라도 포맷을 명확히 구별한다. apiVersion/kind 로도 구별되지만 $schema 는 명시적 방어다(URN —
# 가짜 URL 을 만들지 않고 네임스페이스 식별자만 쓴다).
HARNESS_SCHEMA = "urn:harness-architect:harness:v1"


def to_harness_yaml(config: HarnessConfig) -> str:
    """HarnessConfig → harness.yaml 텍스트 (스펙 §2 구조). 최상단 $schema 로 자기식별."""
    doc: dict[str, Any] = {
        "$schema": HARNESS_SCHEMA,
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
    """harness.yaml 텍스트 → HarnessConfig. Harness Protocol v1 파일은 명확한 에러로 거부한다.

    같은 파일명(harness.yaml)이라도 HP v1 은 스키마가 완전히 다르다($schema=harnessprotocol.io,
    version:"1"). 그런 파일을 조용히 파싱 시도하면 엉뚱한 결과가 나므로 설명적 에러로 거부한다.
    우리 포맷은 apiVersion: harness/v1 · kind: Harness 이며 $schema 는 있어도 없어도 된다(하위호환).
    """
    data = yaml.safe_load(text) or {}
    if isinstance(data, dict):
        schema = str(data.get("$schema") or "")
        if "harnessprotocol.io" in schema:
            raise ValueError(
                "Harness Protocol v1 파일로 보입니다($schema=harnessprotocol.io) — 이 도구의 harness.yaml"
                "(apiVersion: harness/v1, kind: Harness)이 아닙니다. harness-kit 으로 여세요."
            )
        if "version" in data and not ("apiVersion" in data or "kind" in data):
            raise ValueError(
                "알 수 없는 harness 포맷 — 'version' 만 있고 apiVersion/kind 가 없습니다"
                "(Harness Protocol v1 로 추정). 이 도구는 apiVersion: harness/v1 · kind: Harness 를 씁니다."
            )
    return HarnessConfig.model_validate(data)


def build_harness_yaml(components: list[Component], name: str, description: str = "") -> str:
    """초안 구성요소들 → 이들을 components 로 선택하는 harness.yaml (에이전트 스펙)."""
    meta = HarnessMetadata(id=safe_id(name) or "agent", name=name or "에이전트", description=description)
    config = HarnessConfig(
        metadata=meta,
        components=[ComponentSelection(ref=f"{c.id}@{c.version}") for c in components],
    )
    return to_harness_yaml(config)
