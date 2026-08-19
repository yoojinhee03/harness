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
from .vocabulary import CAPABILITY_VOCAB, DOMAIN_VOCAB, is_valid_capability


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
    """LLM 기반 추출·근거 생성(provider anthropic|openai). 실패 시 None 으로 폴백.

    이름은 하위호환(원래 Claude 전용). provider/api_key 주입으로 앱 등록 키(OpenAI 등)도 쓴다.
    """

    name = "claude"

    def __init__(
        self, model: str | None = None, *, provider: str = "anthropic", api_key: str | None = None
    ) -> None:
        self._provider = provider
        self._api_key = api_key
        self._model = model or llm.default_model(provider)

    def extract_requirements(self, description: str) -> list[str] | None:  # pragma: no cover - 네트워크
        """카탈로그 무관 요구사항 추출(작업 2). 카탈로그보다 넓어야 gap 이 난다.

        도메인(척추)은 통제 목록에 맞추되, capability 레벨은 신규 허용 — 미시딩 도메인(예: media.*)도
        낼 수 있어야 recommender 가 그걸 gap 으로 표면화한다. 기존 capability 어휘는 '선호 예시'로만 준다
        (거기서만 고르라고 강제하지 않는다). 형태(`domain.capability`)만 계약이다.
        """
        domains = ", ".join(f"{d}({desc})" for d, desc in DOMAIN_VOCAB.items())
        examples = ", ".join(sorted(CAPABILITY_VOCAB))
        system = (
            "너는 하네스 아키텍트의 요구사항 추출기다. 카탈로그에 무엇이 있는지는 신경 쓰지 말고, "
            "이 제품이 동작하려면 필요한 '능력'만 뽑아라. 각 능력은 반드시 `domain.capability` "
            "2단계 소문자·하이픈 형태여야 한다.\n"
            "- domain 은 되도록 아래 통제 도메인에서 고른다(없으면 새 domain 도 가능하나 형태는 지킨다).\n"
            f"  통제 도메인: {domains}\n"
            "- capability 는 자유롭게 이름 붙여도 된다(카탈로그에 없는 능력이어도 정직하게 낸다).\n"
            f"- 참고용 기존 능력 예시(여기서만 고르라는 뜻 아님): {examples}\n"
            "JSON 배열로만 답하라. 컴포넌트 이름이나 설명이 아니라 능력만."
        )
        try:
            result = llm.complete_json(
                system, description, model=self._model, max_tokens=256,
                provider=self._provider, api_key=self._api_key,
            )
        except Exception:  # noqa: BLE001
            return None
        caps = result if isinstance(result, list) else result.get("capabilities", [])
        return [c for c in caps if isinstance(c, str) and is_valid_capability(c)]

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
            result = llm.complete_json(
                system, json.dumps(payload, ensure_ascii=False), model=self._model,
                provider=self._provider, api_key=self._api_key,
            )
        except Exception:  # noqa: BLE001
            return None
        return {k: str(v) for k, v in result.items()} if isinstance(result, dict) else None


def make_reasoner(provider: str, api_key: str | None, model: str | None = None) -> Reasoner:
    """앱 등록 키(provider+key)로 Reasoner 를 만든다. 키 없거나 호출 불가면 NullReasoner(휴리스틱 폴백)."""
    if provider and llm.available(provider, api_key):
        return ClaudeReasoner(model=model, provider=provider, api_key=api_key)
    return NullReasoner()


def get_reasoner(settings: Settings | None = None) -> Reasoner:
    """env 기반 폴백 경로 — anthropic env 키가 있으면 ClaudeReasoner, 없으면 Null.

    앱 등록 키 경로는 API 가 `make_reasoner(provider, key)` 로 직접 주입한다(이 함수는 env 전용).
    """
    settings = settings or load_settings()
    if settings.use_claude and llm.claude_available():
        return ClaudeReasoner(model=settings.claude_model)
    return NullReasoner()
