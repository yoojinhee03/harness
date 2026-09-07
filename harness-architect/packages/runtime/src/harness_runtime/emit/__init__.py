"""eject — ResolvedHarness 를 각 런타임 네이티브 포맷으로 컴파일한다(Phase 5).

    from harness_runtime.emit import emit, available_targets
    tree = emit(resolved, "claude-code")   # {상대경로: 내용}

타깃 추가는 Emitter 프로토콜을 만족하는 클래스를 _EMITTERS 에 등록하면 끝(가법적).
"""

from __future__ import annotations

from harness_resolver import ResolvedHarness

from .base import Emitter, FileTree, Loss
from .claude_code import ClaudeCodeEmitter
from .cursor import CursorEmitter
from .harness_protocol import HarnessProtocolEmitter

_EMITTERS: dict[str, type] = {
    ClaudeCodeEmitter.target: ClaudeCodeEmitter,
    CursorEmitter.target: CursorEmitter,
    HarnessProtocolEmitter.target: HarnessProtocolEmitter,
}


def available_targets() -> list[str]:
    return sorted(_EMITTERS)


def emit(resolved: ResolvedHarness, target: str) -> FileTree:
    """resolved 를 target 런타임 포맷으로 방출. 미지원 타깃은 ValueError."""
    emitter = _make(target)
    return emitter.emit(resolved)


def target_losses(resolved: ResolvedHarness, target: str) -> list[Loss]:
    """resolved 를 target 으로 방출할 때의 이식 손실(이미터가 선언한 것, IR 기준). verify 가 소비."""
    emitter = _make(target)
    return emitter.losses(resolved)


def _make(target: str) -> Emitter:
    emitter_cls = _EMITTERS.get(target)
    if emitter_cls is None:
        raise ValueError(f"지원하지 않는 eject 타깃: {target!r} (가능: {available_targets()})")
    emitter: Emitter = emitter_cls()
    return emitter


__all__ = [
    "ClaudeCodeEmitter",
    "CursorEmitter",
    "Emitter",
    "FileTree",
    "HarnessProtocolEmitter",
    "Loss",
    "available_targets",
    "emit",
    "target_losses",
]
