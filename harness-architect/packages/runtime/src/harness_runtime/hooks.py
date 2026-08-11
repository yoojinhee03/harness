"""훅 엔진 — 설계: 훅 실행 모델.

리졸버가 만든 이벤트별 정렬 계획(hook_plan)을 받아 라이프사이클 이벤트마다 훅을 순서대로
실행한다. step.sandbox 에 맞는 실행기로 `timeout_ms` 안에서 돌리고, blocking·can_modify·
failure 의미론을 강제한다(카탈로그 선언 = 상한: 미선언 차단/변형은 무시).
미등록 훅은 no-op 통과.
"""

from __future__ import annotations

from typing import Any

from harness_resolver import ResolvedHarness
from harness_resolver.models import HookStep
from pydantic import BaseModel

from .sandbox import Executor, HookHandler, default_executors


class HookOutcome(BaseModel):
    allowed: bool
    payload: Any = None
    notes: list[str] = []


class HookEngine:
    def __init__(
        self,
        resolved: ResolvedHarness,
        executors: dict[str, Executor] | None = None,
    ) -> None:
        self._plan: dict[str, list[HookStep]] = resolved.hook_plan
        self._handlers: dict[str, HookHandler] = {}
        self._executors = executors or default_executors()

    def register(self, hook_id: str, handler: HookHandler) -> None:
        self._handlers[hook_id] = handler

    def _executor_for(self, step: HookStep) -> Executor:
        key = step.sandbox or "restricted"
        return self._executors.get(key, self._executors["restricted"])

    def run(self, event: str, payload: Any) -> HookOutcome:
        """한 이벤트의 훅 체인을 실행. 변형 훅은 파이프라인으로 연쇄."""
        notes: list[str] = []
        current = payload
        for step in self._plan.get(event, []):
            handler = self._handlers.get(step.id)
            if handler is None:
                continue  # 미등록 → no-op 통과(스켈레톤 잔재)

            try:
                result = self._executor_for(step).run(handler, current, step.timeout_ms)
            except TimeoutError as exc:
                if step.failure == "fail_closed":
                    notes.append(f"{step.id} timeout → 차단(fail_closed): {exc}")
                    return HookOutcome(allowed=False, payload=current, notes=notes)
                notes.append(f"{step.id} timeout → 진행(fail_open): {exc}")
                continue
            except Exception as exc:  # noqa: BLE001
                if step.failure == "fail_closed":
                    notes.append(f"{step.id} 실패 → 차단(fail_closed): {exc}")
                    return HookOutcome(allowed=False, payload=current, notes=notes)
                notes.append(f"{step.id} 실패 → 진행(fail_open): {exc}")
                continue

            # 차단 신호 — blocking 선언된 훅만 실제로 차단(상한 강제).
            if result is False:
                if step.blocking:
                    notes.append(f"{step.id} 가 요청 차단")
                    return HookOutcome(allowed=False, payload=current, notes=notes)
                notes.append(f"{step.id} 차단 시도 무시(blocking 미선언)")
                continue

            # 변형 — can_modify_* 선언된 훅만 반영(상한 강제).
            # identity 비교(is)로 판정: `not in (True, False, None)` 은 `==` 라 0/1 같은
            # 페이로드가 False/True 와 매칭돼 삼켜졌다(0 == False, 1 == True). 여기 도달 시
            # result 는 이미 not-False(위에서 처리)이므로 True/None 만 배제하면 된다.
            if result is not True and result is not None:
                if step.can_modify_request or step.can_modify_response:
                    current = result
                    notes.append(f"{step.id} 가 페이로드 변형")
                else:
                    notes.append(f"{step.id} 변형 무시(can_modify 미선언)")

        return HookOutcome(allowed=True, payload=current, notes=notes)
