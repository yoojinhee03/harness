"""훅 실행기 (sandbox 수준) — 설계: 훅 실행 모델 §3·§5.

step.sandbox 에 맞는 실행기를 골라 핸들러를 `timeout_ms` 안에서 실행한다.
- none       : InProcessExecutor — 인프로세스, 신뢰 1st-party 만(격리 없음).
- restricted : ThreadIsolatedExecutor — 워커 스레드 + 하드 timeout(기본값).
- external   : ThreadIsolatedExecutor — 원격 호출 가정, timeout 동일 적용.

⚠️ 경계: 진짜 프로세스/WASM 격리와 네트워크·FS 차단(seccomp 등)은 후속. 여기서는 설계의
필수 요건인 **timeout 강제**와 **실행기 선택**을 실제 동작으로 구현한다(스레드는 강제 종료가
불가하므로 timeout 시 결과를 버리고 진행 — 관찰 가능한 의미론은 동일).
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Protocol

HookHandler = Callable[[Any], Any]


class Executor(Protocol):
    def run(self, fn: HookHandler, payload: Any, timeout_ms: int | None) -> Any: ...


class InProcessExecutor:
    """sandbox=none — 인프로세스 직접 실행. 신뢰된 1st-party 훅만."""

    def run(self, fn: HookHandler, payload: Any, timeout_ms: int | None) -> Any:
        return fn(payload)


class ThreadIsolatedExecutor:
    """sandbox=restricted/external — 워커 스레드 + timeout 강제.

    timeout_ms 초과 시 `TimeoutError` 를 올린다(호출부가 failure 정책으로 처리).
    """

    def run(self, fn: HookHandler, payload: Any, timeout_ms: int | None) -> Any:
        if not timeout_ms:
            return fn(payload)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, payload)
            try:
                return future.result(timeout=timeout_ms / 1000.0)
            except FuturesTimeout as exc:
                raise TimeoutError(f"훅 timeout {timeout_ms}ms 초과") from exc


def default_executors() -> dict[str, Executor]:
    return {
        "none": InProcessExecutor(),
        "restricted": ThreadIsolatedExecutor(),
        "external": ThreadIsolatedExecutor(),
    }
