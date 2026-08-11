"""Emitter 프로토콜 — 설계: 진행 플랜 Phase 5 (다중 런타임 컴파일).

`ResolvedHarness`(검증된 IR)를 각 에이전트 런타임의 네이티브 파일 트리로 방출한다.
타깃별 Emitter 는 이 프로토콜만 만족하면 되고, 추가는 가법적이다(dispatch 는 emit/__init__).
"""

from __future__ import annotations

from typing import Protocol

from harness_resolver import ResolvedHarness

# 상대경로 → 파일 내용. 디스크 쓰기(CLI)·아카이브 반환(API)이 모두 이 형태를 소비한다.
FileTree = dict[str, str]


class Emitter(Protocol):
    target: str

    def emit(self, resolved: ResolvedHarness) -> FileTree: ...
