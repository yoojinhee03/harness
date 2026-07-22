"""eject — ResolvedHarness 를 각 런타임 네이티브 포맷으로 컴파일한다(Phase 5).

    from harness_runtime.emit import emit, available_targets
    tree = emit(resolved, "claude-code")   # {상대경로: 내용}

타깃 추가는 Emitter 프로토콜을 만족하는 클래스를 _EMITTERS 에 등록하면 끝(가법적).
"""

from __future__ import annotations

from harness_resolver import ResolvedHarness

from .base import Emitter, FileTree
from .claude_code import ClaudeCodeEmitter

_EMITTERS: dict[str, type] = {ClaudeCodeEmitter.target: ClaudeCodeEmitter}


def available_targets() -> list[str]:
    return sorted(_EMITTERS)


def emit(resolved: ResolvedHarness, target: str) -> FileTree:
    """resolved 를 target 런타임 포맷으로 방출. 미지원 타깃은 ValueError."""
    emitter_cls = _EMITTERS.get(target)
    if emitter_cls is None:
        raise ValueError(f"지원하지 않는 eject 타깃: {target!r} (가능: {available_targets()})")
    emitter: Emitter = emitter_cls()
    return emitter.emit(resolved)


__all__ = ["ClaudeCodeEmitter", "Emitter", "FileTree", "available_targets", "emit"]
