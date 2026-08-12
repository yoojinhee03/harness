"""가드레일 실물 구현 (선택적) — 카탈로그의 lifecycle 훅을 진짜로 동작하게 한다.

`pii-redact-hook`(after_response·can_modify_response)의 실제 핸들러를 오픈소스
**Microsoft Presidio** 로 구현한다 — 탐지·마스킹이 실제로 이뤄진다(이전엔 빈 껍데기).
훅 엔진에 등록하면 응답 페이로드의 PII 를 마스킹한다.

Presidio 는 선택적 extra(무거움 — spacy 모델 필요) → 지연 import + 설치 안내.
설치: `pip install presidio-analyzer presidio-anonymizer && python -m spacy download en_core_web_sm`
미설치 시 핸들러 팩토리가 RuntimeError → 훅 미등록(엔진은 no-op 통과, 폴백 불변).
"""

from __future__ import annotations

from typing import Any

from .sandbox import HookHandler

_INSTALL_HINT = (
    "PII 가드레일은 presidio 가 필요합니다: "
    "pip install presidio-analyzer presidio-anonymizer && python -m spacy download en_core_web_sm"
)
_cache: dict[str, Any] = {}


def _engines() -> tuple[Any, Any]:
    """(AnalyzerEngine, AnonymizerEngine) 을 1회 구성해 캐시. 경량 spacy 모델(sm) 사용."""
    if "analyzer" not in _cache:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            from presidio_anonymizer import AnonymizerEngine
        except ModuleNotFoundError as exc:  # pragma: no cover - 선택적 의존성
            raise RuntimeError(_INSTALL_HINT) from exc
        cfg = {"nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]}
        nlp = NlpEngineProvider(nlp_configuration=cfg).create_engine()
        _cache["analyzer"] = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
        _cache["anonymizer"] = AnonymizerEngine()
    return _cache["analyzer"], _cache["anonymizer"]


def presidio_redact(text: str, language: str = "en") -> str:
    """텍스트의 PII(이름·이메일·카드번호 등)를 `<TYPE>` 자리표시로 마스킹한다."""
    if not text:
        return text
    analyzer, anonymizer = _engines()
    results = analyzer.analyze(text=text, language=language)
    redacted: str = anonymizer.anonymize(text=text, analyzer_results=results).text
    return redacted


def pii_redact_handler() -> HookHandler:
    """훅 엔진에 등록할 PII 마스킹 핸들러. 문자열/문자열 dict 값의 PII 를 마스킹.

    (호출 시 presidio 미설치면 RuntimeError — 등록 전에 확인하려면 먼저 호출)
    """
    _engines()  # 미설치면 여기서 RuntimeError(등록 자체를 막음)

    def handler(payload: Any) -> Any:
        if isinstance(payload, str):
            return presidio_redact(payload)
        if isinstance(payload, dict):
            return {k: (presidio_redact(v) if isinstance(v, str) else v) for k, v in payload.items()}
        return payload

    return handler
