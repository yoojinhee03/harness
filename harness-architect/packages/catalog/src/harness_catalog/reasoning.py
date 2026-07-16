"""Reasoner — 요구사항 추출 + 랭킹 근거 생성의 LLM 경계.

recommender 가 구현체(Claude/휴리스틱)에 비의존하도록 프로토콜로 감싼다.
- NullReasoner  : 두 메서드 모두 None 반환 → recommender 가 휴리스틱으로 폴백.
- ClaudeReasoner: Claude Sonnet 5 로 추출·근거 생성. 실패 시 None 반환(폴백).

주입 가능 — 테스트는 fake Reasoner 를 넣어 품질 모드 경로를 네트워크 없이 검증한다.
"""

from __future__ import annotations

import json
from typing import Protocol

from . import llm
from .settings import Settings, load_settings
from .vocabulary import CAPABILITY_VOCAB


class Reasoner(Protocol):
    name: str

    def extract_requirements(self, description: str) -> list[str] | None: ...

    def rank_reasons(
        self, description: str, items: list[tuple[str, str, list[str]]]
    ) -> dict[str, str] | None: ...


class NullReasoner:
    """휴리스틱 폴백 신호 — 항상 None(호출부가 휴리스틱을 쓴다)."""

    name = "heuristic"

    def extract_requirements(self, description: str) -> list[str] | None:
        return None

    def rank_reasons(
        self, description: str, items: list[tuple[str, str, list[str]]]
    ) -> dict[str, str] | None:
        return None


class ClaudeReasoner:
    """Claude Sonnet 5 기반 추출·근거 생성. 실패 시 None 으로 폴백."""

    name = "claude"

    def __init__(self, model: str | None = None) -> None:
        self._model = model or "claude-sonnet-5"

    def extract_requirements(self, description: str) -> list[str] | None:  # pragma: no cover - 네트워크
        vocab = ", ".join(CAPABILITY_VOCAB)
        system = (
            "너는 하네스 아키텍트의 요구사항 추출기다. 프로젝트 설명에서 필요한 능력을 "
            f"아래 통제 어휘에서만 고른다. JSON 배열로만 답하라.\n어휘: {vocab}"
        )
        try:
            result = llm.complete_json(system, description, model=self._model, max_tokens=256)
        except Exception:  # noqa: BLE001
            return None
        caps = result if isinstance(result, list) else result.get("capabilities", [])
        return [c for c in caps if c in CAPABILITY_VOCAB]

    def rank_reasons(
        self, description: str, items: list[tuple[str, str, list[str]]]
    ) -> dict[str, str] | None:  # pragma: no cover - 네트워크
        system = (
            "너는 하네스 아키텍트의 랭킹 근거 생성기다. 각 컴포넌트가 이 프로젝트에 왜 "
            "적합한지 한 줄 근거를 한국어로 쓴다. JSON {id: reason} 형태로만 답하라."
        )
        payload = {
            "project": description,
            "components": [{"id": i, "summary": s, "provides": p} for i, s, p in items],
        }
        try:
            result = llm.complete_json(system, json.dumps(payload, ensure_ascii=False), model=self._model)
        except Exception:  # noqa: BLE001
            return None
        return {k: str(v) for k, v in result.items()} if isinstance(result, dict) else None


def get_reasoner(settings: Settings | None = None) -> Reasoner:
    settings = settings or load_settings()
    if settings.use_claude and llm.claude_available():
        return ClaudeReasoner(model=settings.claude_model)
    return NullReasoner()
