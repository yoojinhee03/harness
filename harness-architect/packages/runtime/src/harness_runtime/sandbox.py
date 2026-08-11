"""훅 실행기 (sandbox 수준) — 설계: 훅 실행 모델 §3·§5.

step.sandbox 에 맞는 실행기를 골라 핸들러를 `timeout_ms` 안에서 실행한다.
- none                 : InProcessExecutor — 인프로세스 직접 실행(격리·timeout 없음). 신뢰 1st-party 만.
- restricted / external : TimeoutBoundExecutor — 데몬 스레드 + 벽시계 timeout 강제.

⚠️ **정직성 경계 — 여기엔 격리가 없다.** `restricted` 와 `external` 은 현재 *동일한*
실행기(TimeoutBoundExecutor)로 매핑되며, 프로세스/WASM 격리도 네트워크·FS 차단(seccomp 등)도
하지 않는다. 이 실행기가 실제로 강제하는 유일한 것은 **벽시계 timeout** 이다. 진짜 격리는 후속
증분(subprocess/WASM)에서 붙인다. 그때까지 `restricted`/`external` 은 "시간 상한이 걸린
인프로세스 실행"으로만 이해할 것 — 신뢰할 수 없는 코드를 여기서 돌리면 안 된다.

스레드는 강제 종료가 불가하므로, timeout 시 워커를 **데몬 스레드로 버리고 즉시 반환**한다(결과
폐기, 호출부가 failure 정책으로 처리). 이전 구현은 `ThreadPoolExecutor` 를 컨텍스트 매니저로
써서 timeout 후에도 `shutdown(wait=True)` 로 워커 종료까지 블록됐다 — 그 경우 timeout 이
관측상 무의미했다(핸들러가 끝날 때까지 벽시계로 기다림). 데몬 스레드 방식은 그 hang 을 없앤다.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Protocol

HookHandler = Callable[[Any], Any]


class Executor(Protocol):
    def run(self, fn: HookHandler, payload: Any, timeout_ms: int | None) -> Any: ...


class InProcessExecutor:
    """sandbox=none — 인프로세스 직접 실행. 신뢰된 1st-party 훅만(격리·timeout 없음)."""

    def run(self, fn: HookHandler, payload: Any, timeout_ms: int | None) -> Any:
        return fn(payload)


class TimeoutBoundExecutor:
    """sandbox=restricted/external — 데몬 스레드 + 벽시계 timeout 강제(격리는 아님).

    timeout_ms 초과 시 워커 스레드를 버리고 `TimeoutError` 를 올린다(호출부가 failure 정책으로
    처리). 워커는 daemon 이라 인터프리터 종료를 막지 않는다. 핸들러가 올린 예외는 그대로 전파한다.
    """

    def run(self, fn: HookHandler, payload: Any, timeout_ms: int | None) -> Any:
        if not timeout_ms:
            return fn(payload)

        box: dict[str, Any] = {}
        done = threading.Event()

        def worker() -> None:
            try:
                box["value"] = fn(payload)
            except BaseException as exc:  # noqa: BLE001 - 워커 예외를 호출 스레드로 전달
                box["error"] = exc
            finally:
                done.set()

        thread = threading.Thread(target=worker, name="hook-worker", daemon=True)
        thread.start()
        if not done.wait(timeout=timeout_ms / 1000.0):
            # 워커는 계속 돌 수 있으나 daemon 이라 버려도 안전 — 결과를 무시하고 즉시 반환.
            raise TimeoutError(f"훅 timeout {timeout_ms}ms 초과")
        if "error" in box:
            raise box["error"]
        return box.get("value")


def default_executors() -> dict[str, Executor]:
    shared = TimeoutBoundExecutor()  # restricted/external 은 현재 동작이 동일(위 경계 참고)
    return {
        "none": InProcessExecutor(),
        "restricted": shared,
        "external": shared,
    }
