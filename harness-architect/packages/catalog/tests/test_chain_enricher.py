"""ChainEnricher — 순서 적용·active 집계 (하드닝 TASK 3 배선)."""

from __future__ import annotations

from harness_catalog import ChainEnricher
from harness_resolver import Component


class _Fake:
    """enricher 규약(active·enrich)만 만족하는 테스트 더블."""

    def __init__(self, active: bool, tag: str) -> None:
        self._active = active
        self._tag = tag

    @property
    def active(self) -> bool:
        return self._active

    def enrich(self, comps: list[Component]) -> list[Component]:
        for c in comps:
            c.capability_tags = [*c.capability_tags, self._tag]
        return comps


def _comp() -> Component:
    return Component(id="x", type="mcp", name="X", version="1.0.0")


def test_chain_applies_in_order() -> None:
    c = _comp()
    ChainEnricher([_Fake(True, "a"), _Fake(True, "b")]).enrich([c])  # type: ignore[list-item]
    assert c.capability_tags == ["a", "b"]  # 제로샷 → LLM 순서 보존


def test_active_if_any() -> None:
    assert ChainEnricher([_Fake(False, "a"), _Fake(True, "b")]).active is True  # type: ignore[list-item]
    assert ChainEnricher([_Fake(False, "a")]).active is False  # type: ignore[list-item]
