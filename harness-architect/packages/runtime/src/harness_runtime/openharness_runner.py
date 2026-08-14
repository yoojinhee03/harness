"""OpenHarness 런타임 임베드 (선택적) — 설계: 진행 플랜 Phase 2 확장 / 이식성.

우리 `ResolvedHarness`(검증된 IR)를 오픈소스 **OpenHarness**(HKUDS/OpenHarness, MIT)의
`QueryEngine` 에 태워 **실제 에이전트 루프(Action·Observation)** 를 돌린다. 우리 시스템은
Tools·Knowledge·Permissions 를 그라운딩·검증해 찍고, 루프는 OpenHarness 가 준다 → 5요소 완성.

매핑:
    resolved.prompt.system_text → QueryEngine.system_prompt   (Knowledge)
    resolved.model.name/max_tokens → model/max_tokens
    (MCP 컴포넌트)               → ToolRegistry               (Tools; 등록은 후속)
    안전 기본 정책              → PermissionSettings          (Permissions)

openharness-ai 는 **선택적**이다 — 코어는 이것 없이도 오프라인으로 완주한다(러너는 stub).
설치해야 활성: `pip install openharness-ai`. 무겁고(v0.1.x, Claude Code 포트) API 가 아직
유동적이라 기본 의존성에 넣지 않고 런타임 지연 import 로 옵트인한다(anthropic/voyage 와 동일 패턴).
클라이언트 주입가능: 테스트는 fake(SupportsStreamingMessages), 실사용은 AnthropicApiClient(키).
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any

from harness_resolver import ResolvedHarness

from .runner import RunResult

# 방출 산출물과 정합하는 안전 기본 가드레일(capability-scope → 세밀 정책 매핑은 policy-as-code 후속).
_SAFE_DENIED_COMMANDS = ["rm -rf /", "rm -rf ~", "git push --force", ":(){ :|:& };:"]


def _load_openharness() -> SimpleNamespace:
    """필요한 OpenHarness 심볼을 지연 로드. 미설치 시 명확한 안내로 실패."""
    try:
        from openharness.api.client import AnthropicApiClient
        from openharness.commands.registry import PermissionChecker, PermissionMode, QueryEngine
        from openharness.config.settings import PermissionSettings
        from openharness.engine.stream_events import AssistantTextDelta
        from openharness.tools import ToolRegistry
    except ModuleNotFoundError as exc:  # pragma: no cover - 선택적 의존성
        raise RuntimeError(
            "OpenHarnessRunner 는 openharness-ai 가 필요합니다: pip install openharness-ai"
        ) from exc
    return SimpleNamespace(
        QueryEngine=QueryEngine,
        ToolRegistry=ToolRegistry,
        PermissionChecker=PermissionChecker,
        PermissionSettings=PermissionSettings,
        PermissionMode=PermissionMode,
        AssistantTextDelta=AssistantTextDelta,
        AnthropicApiClient=AnthropicApiClient,
    )


async def _drive(oh: SimpleNamespace, engine: Any, user_prompt: str) -> str:
    """submit_message 루프를 돌며 assistant 텍스트 델타를 이어붙인다."""
    parts: list[str] = []
    async for event in engine.submit_message(user_prompt):
        if isinstance(event, oh.AssistantTextDelta):
            parts.append(event.text)
    return "".join(parts)


class OpenHarnessRunner:
    """ResolvedHarness → OpenHarness QueryEngine 루프 실행기(주입가능 클라이언트)."""

    def __init__(
        self,
        client: Any | None = None,
        api_key: str | None = None,
        cwd: str = ".",
        max_turns: int = 8,
    ) -> None:
        self._client = client
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._cwd = cwd
        self._max_turns = max_turns

    def _api_client(self, oh: SimpleNamespace) -> Any | None:
        if self._client is not None:
            return self._client
        if not self._api_key:
            return None
        return oh.AnthropicApiClient(api_key=self._api_key)  # pragma: no cover - 네트워크 경로

    def _permissions(self, oh: SimpleNamespace) -> Any:
        # 안전 기본: 위험 명령 차단. 세밀한 capability-scope → path/command 매핑은 policy-as-code 후속.
        return oh.PermissionSettings(
            mode=oh.PermissionMode.DEFAULT,
            denied_commands=list(_SAFE_DENIED_COMMANDS),
        )

    def run(self, resolved: ResolvedHarness, user_prompt: str) -> RunResult:
        oh = _load_openharness()
        api_client = self._api_client(oh)
        if api_client is None:
            return RunResult(
                dry_run=True,
                model=resolved.model.name,
                notes=["ANTHROPIC_API_KEY/client 없음 — OpenHarness 루프 미실행(dry_run)"],
            )
        engine = oh.QueryEngine(
            api_client=api_client,
            tool_registry=oh.ToolRegistry(),  # MCP 컴포넌트 → 도구 등록은 후속 슬라이스
            permission_checker=oh.PermissionChecker(self._permissions(oh)),
            cwd=self._cwd,
            model=resolved.model.name,
            system_prompt=resolved.prompt.system_text if resolved.prompt is not None else "",
            max_tokens=resolved.model.max_tokens,
            max_turns=self._max_turns,
        )
        text = asyncio.run(_drive(oh, engine, user_prompt))
        return RunResult(dry_run=False, model=resolved.model.name, text=text)
