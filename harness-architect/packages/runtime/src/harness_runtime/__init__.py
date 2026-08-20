"""harness_runtime — 런타임 레이어.

ResolvedHarness → 요청 빌더(system/tools/mcp 조립) + 훅 엔진(이벤트 미들웨어, sandbox·timeout)
→ Anthropic 러너. 진짜 프로세스/WASM 격리와 실제 API 응답은 키·인프라가 있을 때 활성.
"""

from __future__ import annotations

from .adopt import AdoptResult, adopt, adopt_dir, read_native_tree
from .builder import BuiltRequest, build_request
from .emit import (
    ClaudeCodeEmitter,
    CursorEmitter,
    Emitter,
    FileTree,
    HarnessProtocolEmitter,
    Loss,
    available_targets,
    emit,
    target_losses,
)
from .eval import (
    AblationResult,
    CheckResult,
    EvalCase,
    EvalCaseResult,
    EvalExpect,
    EvalReport,
    check_expectations,
    drop_component,
    run_ablation,
    run_eval,
)
from .guardrails import pii_redact_handler, presidio_redact
from .hooks import HookEngine, HookOutcome
from .openharness_runner import OpenHarnessRunner
from .runner import AnthropicRunner, RunResult
from .sandbox import Executor, InProcessExecutor, TimeoutBoundExecutor, default_executors
from .tracing import harness_span
from .verify import DEFAULT_SEVERITY, VerifyReport, verify, violations

__all__ = [
    "AblationResult",
    "AdoptResult",
    "AnthropicRunner",
    "DEFAULT_SEVERITY",
    "VerifyReport",
    "BuiltRequest",
    "CheckResult",
    "ClaudeCodeEmitter",
    "CursorEmitter",
    "Emitter",
    "EvalCase",
    "EvalCaseResult",
    "EvalExpect",
    "EvalReport",
    "Executor",
    "FileTree",
    "HarnessProtocolEmitter",
    "HookEngine",
    "HookOutcome",
    "InProcessExecutor",
    "Loss",
    "OpenHarnessRunner",
    "RunResult",
    "TimeoutBoundExecutor",
    "adopt",
    "adopt_dir",
    "available_targets",
    "build_request",
    "pii_redact_handler",
    "presidio_redact",
    "check_expectations",
    "default_executors",
    "drop_component",
    "emit",
    "target_losses",
    "harness_span",
    "read_native_tree",
    "run_ablation",
    "run_eval",
    "verify",
    "violations",
]
