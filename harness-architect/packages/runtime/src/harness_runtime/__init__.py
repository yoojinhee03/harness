"""harness_runtime — 런타임 레이어.

ResolvedHarness → 요청 빌더(system/tools/mcp 조립) + 훅 엔진(이벤트 미들웨어, sandbox·timeout)
→ Anthropic 러너. 진짜 프로세스/WASM 격리와 실제 API 응답은 키·인프라가 있을 때 활성.
"""

from __future__ import annotations

from .builder import BuiltRequest, build_request
from .hooks import HookEngine, HookOutcome
from .runner import AnthropicRunner, RunResult
from .sandbox import Executor, InProcessExecutor, ThreadIsolatedExecutor, default_executors

__all__ = [
    "AnthropicRunner",
    "BuiltRequest",
    "Executor",
    "HookEngine",
    "HookOutcome",
    "InProcessExecutor",
    "RunResult",
    "ThreadIsolatedExecutor",
    "build_request",
    "default_executors",
]
