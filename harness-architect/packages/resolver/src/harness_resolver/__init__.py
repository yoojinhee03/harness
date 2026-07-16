"""harness_resolver — 순수 함수 리졸버.

harness.yaml(선언) + 카탈로그 레지스트리 → ResolvedHarness(실행 명세) 또는 진단.
"""

from __future__ import annotations

from .diagnostics import Diagnostic, Diagnostics
from .merge import merge_harness_configs
from .models import (
    Auth,
    Budget,
    Component,
    ComponentSelection,
    Cost,
    HarnessConfig,
    HarnessMetadata,
    ModelConfig,
    ResolvedComponent,
    ResolvedHarness,
)
from .registry import InMemoryRegistry, Registry
from .resolver import ResolveResult, resolve

__all__ = [
    "Auth",
    "Budget",
    "Component",
    "ComponentSelection",
    "Cost",
    "Diagnostic",
    "Diagnostics",
    "HarnessConfig",
    "HarnessMetadata",
    "InMemoryRegistry",
    "ModelConfig",
    "Registry",
    "ResolveResult",
    "ResolvedComponent",
    "ResolvedHarness",
    "merge_harness_configs",
    "resolve",
]
