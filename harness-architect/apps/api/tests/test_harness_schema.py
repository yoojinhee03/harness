"""harness.yaml 자기식별 + Harness Protocol v1 거부 (하드닝 TASK 4)."""

from __future__ import annotations

import pytest
import yaml
from harness_api.harness_build import HARNESS_SCHEMA, parse_harness_yaml, to_harness_yaml
from harness_resolver import HarnessConfig, HarnessMetadata


def _cfg() -> HarnessConfig:
    return HarnessConfig(metadata=HarnessMetadata(id="t", name="T"))


def test_emits_schema_and_roundtrips() -> None:
    doc = yaml.safe_load(to_harness_yaml(_cfg()))
    assert doc["$schema"] == HARNESS_SCHEMA
    assert doc["apiVersion"] == "harness/v1" and doc["kind"] == "Harness"
    # 라운드트립 — $schema 는 무시되고 정상 파싱된다
    assert parse_harness_yaml(to_harness_yaml(_cfg())).metadata.id == "t"


def test_rejects_hp_v1_schema() -> None:
    hp = (
        "$schema: https://harnessprotocol.io/schema/v1/harness.schema.json\n"
        'version: "1"\nmetadata:\n  name: x\n'
    )
    with pytest.raises(ValueError, match="Harness Protocol"):
        parse_harness_yaml(hp)


def test_rejects_version_only_no_apiversion() -> None:
    with pytest.raises(ValueError, match="알 수 없는 harness"):
        parse_harness_yaml('version: "1"\nmetadata:\n  name: x\n')


def test_backward_compat_no_schema() -> None:
    # $schema 없는 구 문서(apiVersion/kind 보유)도 그대로 파싱된다(하위호환)
    old = "apiVersion: harness/v1\nkind: Harness\nmetadata:\n  id: t\n  name: T\n"
    assert parse_harness_yaml(old).metadata.id == "t"
