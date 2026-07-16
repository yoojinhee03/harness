"""컴포넌트 레지스트리 — 이름(id@version)으로 컴포넌트를 참조하는 중앙 저장소.

리졸버는 순수 함수이므로 레지스트리를 인자로 받는다. 카탈로그 패키지가 YAML 을 로드해
`InMemoryRegistry` 를 채워 넘긴다. `extends` 를 위한 base harness 저장소도 겸한다.
"""

from __future__ import annotations

from typing import Protocol

from .models import Component, HarnessConfig


def _semver_key(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in version.split("."))
    except ValueError:
        return (0,)


class Registry(Protocol):
    def get(self, component_id: str, version: str | None = None) -> Component | None: ...
    def all(self) -> list[Component]: ...
    def get_base(self, name: str) -> HarnessConfig | None: ...


class InMemoryRegistry:
    """딕셔너리 기반 레지스트리. version 생략 시 최신 stable 을 고정한다."""

    def __init__(
        self,
        components: list[Component] | None = None,
        bases: dict[str, HarnessConfig] | None = None,
    ) -> None:
        self._by_id: dict[str, list[Component]] = {}
        self._bases: dict[str, HarnessConfig] = bases or {}
        for c in components or []:
            self.add(c)

    def add(self, component: Component) -> None:
        self._by_id.setdefault(component.id, []).append(component)

    def get(self, component_id: str, version: str | None = None) -> Component | None:
        versions = self._by_id.get(component_id)
        if not versions:
            return None
        if version is not None:
            for c in versions:
                if c.version == version:
                    return c
            return None  # 버전 불일치
        # version 생략 → 최신 stable 고정 (없으면 최신)
        stable = [c for c in versions if c.status == "stable"]
        pool = stable or versions
        return max(pool, key=lambda c: _semver_key(c.version))

    def all(self) -> list[Component]:
        return [c for versions in self._by_id.values() for c in versions]

    def get_base(self, name: str) -> HarnessConfig | None:
        return self._bases.get(name)
