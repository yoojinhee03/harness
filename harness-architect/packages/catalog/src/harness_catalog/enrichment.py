"""Capability LLM 보강 — 수확된 컴포넌트의 빈/약한 caps 를 통제 어휘로 채운다.

라이브 레지스트리/마켓플레이스에서 온 컴포넌트는 name+description 만 있어 휴리스틱 caps 가 자주
비거나 오탐한다(예: name-service → vcs 오탐). caps 가 비면 추천 랭킹·검색에 안 잡히므로,
키가 있을 때 Claude 로 배치 분류해 `capability_tags`/`provides` 를 보강한다.

설계 원칙(레포 이토스 정합):
- 옵트인(자동): ANTHROPIC_API_KEY 있고 use_claude 일 때만. 없으면 **무보강**(휴리스틱 유지, 오프라인 완주).
- Reasoner Protocol 은 건드리지 않는다 — 얇은 `CapabilityClassifier` 콜러블로 주입(테스트는 fake).
- 형태만 강제(범용): 반환 caps 는 `domain.capability` 형태만 통과(멤버십 강제 아님) — vocab 에 없던
  신규 도메인(미디어·금융 등)도 태깅돼 검색·재사용된다. 도메인 척추는 분류 프롬프트로 가이드.
- 비용 상한: 기본은 caps 빈 컴포넌트만(증분), `retag=True` 면 전체 재분류. `max_enrich` 상한·`batch_size` 배치.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from harness_resolver import Component

from . import llm
from .settings import Settings, load_settings
from .vocabulary import CAPABILITY_VOCAB, DOMAIN_VOCAB, is_valid_capability

log = logging.getLogger("harness_catalog.enrichment")

# list[(id, text)] → {id: [capability]} | None. None 이면 보강 실패(호출부가 원본 유지).
CapabilityClassifier = Callable[[list[tuple[str, str]]], dict[str, list[str]] | None]

_MAX_TEXT = 300  # 컴포넌트당 프롬프트에 넣는 설명 길이 상한(토큰 절약)


def _component_text(c: Component) -> str:
    kw = (" " + " ".join(c.keywords)) if c.keywords else ""
    return f"{c.name}. {c.description}{kw}"[:_MAX_TEXT]


def _tagger(model: str, provider: str, api_key: str | None) -> CapabilityClassifier:
    """provider/키로 배치 분류기 클로저 — (id, text) 목록 → {id: [domain.capability]}. 실패 시 None.

    도메인 무관·범용: 통제 도메인(척추)에 맞추되 capability 레벨은 신규 허용(형태만 계약). 그래야 vocab 에
    미리 없던 도메인(미디어·금융·헬스 등)의 MCP 도 정확히 태깅돼 검색·재사용된다. 억지 태깅은 금지.
    """

    def _classify(items: list[tuple[str, str]]) -> dict[str, list[str]] | None:  # pragma: no cover - 네트워크
        domains = ", ".join(f"{d}({desc})" for d, desc in DOMAIN_VOCAB.items())
        examples = ", ".join(sorted(CAPABILITY_VOCAB))
        system = (
            "너는 하네스 카탈로그의 능력 태거다. 각 컴포넌트(MCP 서버·스킬 등)가 **실제로 제공하는** 능력을 "
            "`domain.capability` 2단계 소문자·하이픈 형태로 태깅한다.\n"
            f"- domain 은 되도록 아래 통제 도메인에서: {domains}\n"
            "- 없으면 새 domain 도 가능하나 형태는 지킨다. capability 는 자유롭게 명명.\n"
            f"- 참고용 기존 능력 예시(여기서만 고르라는 뜻 아님): {examples}\n"
            "설명이 모호해 능력을 특정 못 하면 그 컴포넌트는 **비운다**(억지 태깅 금지 — 틀린 태그보다 빈 게 낫다). "
            'JSON 오브젝트 {"<id>": ["domain.capability", ...]} 형태로만 답하라.'
        )
        payload = {"components": [{"id": i, "text": t} for i, t in items]}
        try:
            result = llm.complete_json(
                system, json.dumps(payload, ensure_ascii=False), model=model, max_tokens=2048,
                provider=provider, api_key=api_key,
            )
        except Exception:  # noqa: BLE001 — 어떤 실패든 무보강 폴백
            return None
        if not isinstance(result, dict):
            return None
        return {
            str(k): [c for c in v if isinstance(c, str) and is_valid_capability(c)]
            for k, v in result.items()
            if isinstance(v, list)
        }

    return _classify


def claude_classifier(model: str) -> CapabilityClassifier:
    """하위호환 — anthropic env 키 기반 배치 분류기."""
    return _tagger(model, provider="anthropic", api_key=None)


def make_classifier(
    provider: str, api_key: str | None, model: str | None = None
) -> CapabilityClassifier | None:
    """앱 등록 키(provider+key)로 분류기를 만든다. 호출 불가(키 없음)면 None(무보강)."""
    if not (provider and llm.available(provider, api_key)):
        return None
    return _tagger(model or llm.default_model(provider), provider=provider, api_key=api_key)


def get_classifier(settings: Settings | None = None) -> CapabilityClassifier | None:
    """env 기반 폴백 — anthropic env 키가 있으면 분류기, 없으면 None. 앱 키 경로는 make_classifier 로 주입."""
    cfg = settings or load_settings()
    if cfg.use_claude and llm.claude_available():
        return claude_classifier(cfg.claude_model)
    return None


class CapabilityEnricher:
    """수확 컴포넌트의 caps 를 배치 LLM 분류로 보강한다. 분류기 없으면 무보강(원본 그대로).

    기본은 caps 빈 컴포넌트만(증분·저비용). `retag=True` 면 이미 태그가 있어도 재분류한다 — 오프라인
    휴리스틱이 남긴 저신뢰 태그를 LLM 으로 갈아끼울 때(전체 재태깅 패스). 반환 caps 는 형태(domain.capability)만
    강제하고 vocab 멤버십은 강제하지 않는다 — 신규 도메인(미디어 등)도 태깅되게 하려는 것(범용).
    """

    def __init__(
        self,
        classifier: CapabilityClassifier | None = None,
        settings: Settings | None = None,
        batch_size: int = 40,
        max_enrich: int = 150,
        retag: bool = False,
    ) -> None:
        # classifier 를 명시하지 않으면 설정에서 해석(키 없으면 None).
        self._classifier = classifier if classifier is not None else get_classifier(settings)
        self._batch = max(1, batch_size)
        self._max = max_enrich
        self._retag = retag

    @property
    def active(self) -> bool:
        return self._classifier is not None and self._max > 0

    def enrich(self, components: list[Component]) -> list[Component]:
        """대상 컴포넌트의 caps 를 제자리 보강하고 같은 리스트를 반환한다(가변 모델)."""
        if not self.active:
            return components
        targets = components if self._retag else [c for c in components if not c.capability_tags]
        capped = targets[: self._max]
        if not capped:
            return components
        by_id = {c.id: c for c in components}
        enriched = 0
        for i in range(0, len(capped), self._batch):
            batch = capped[i : i + self._batch]
            result = self._classifier([(c.id, _component_text(c)) for c in batch])  # type: ignore[misc]
            if not result:
                continue
            for cid, caps in result.items():
                comp = by_id.get(cid)
                valid = [c for c in caps if is_valid_capability(c)]
                if comp is not None and valid:
                    comp.capability_tags = valid
                    comp.provides = valid
                    enriched += 1
        if len(targets) > self._max:
            log.warning("capability 보강 상한 절단 — 대상 %d 중 %d개만(max_enrich)", len(targets), self._max)
        log.info("capability LLM 보강: %d개 태깅(대상 %d, retag=%s)", enriched, len(capped), self._retag)
        return components
