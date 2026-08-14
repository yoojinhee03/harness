"""Capability LLM 보강 — 수확된 컴포넌트의 빈/약한 caps 를 통제 어휘로 채운다.

라이브 레지스트리/마켓플레이스에서 온 컴포넌트는 name+description 만 있어 휴리스틱 caps 가 자주
비거나 오탐한다(예: name-service → vcs 오탐). caps 가 비면 추천 랭킹·검색에 안 잡히므로,
키가 있을 때 Claude 로 배치 분류해 `capability_tags`/`provides` 를 보강한다.

설계 원칙(레포 이토스 정합):
- 옵트인(자동): ANTHROPIC_API_KEY 있고 use_claude 일 때만. 없으면 **무보강**(휴리스틱 유지, 오프라인 완주).
- Reasoner Protocol 은 건드리지 않는다 — 얇은 `CapabilityClassifier` 콜러블로 주입(테스트는 fake).
- 통제 어휘 강제: 반환 caps 는 `CAPABILITY_VOCAB` 로 필터(자유 텍스트 금지).
- 비용 상한: caps 가 빈 컴포넌트만, `max_enrich` 개까지, `batch_size` 씩 배치. 절단은 로그.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from harness_resolver import Component

from . import llm
from .settings import Settings, load_settings
from .vocabulary import CAPABILITY_VOCAB

log = logging.getLogger("harness_catalog.enrichment")

# list[(id, text)] → {id: [capability]} | None. None 이면 보강 실패(호출부가 원본 유지).
CapabilityClassifier = Callable[[list[tuple[str, str]]], dict[str, list[str]] | None]

_MAX_TEXT = 300  # 컴포넌트당 프롬프트에 넣는 설명 길이 상한(토큰 절약)


def _component_text(c: Component) -> str:
    return f"{c.name}. {c.description}"[:_MAX_TEXT]


def claude_classifier(model: str) -> CapabilityClassifier:
    """Claude 배치 분류기 — (id, text) 목록 → {id: [통제어휘 cap]}. 실패 시 None."""

    def _classify(items: list[tuple[str, str]]) -> dict[str, list[str]] | None:  # pragma: no cover - 네트워크
        vocab = ", ".join(CAPABILITY_VOCAB)
        system = (
            "너는 하네스 카탈로그의 능력 태거다. 각 컴포넌트(MCP 서버·스킬 등)가 제공하는 능력을 "
            "아래 통제 어휘에서만 고른다. 애매하면 비운다(억지 태깅 금지). "
            'JSON 오브젝트 {"<id>": ["cap", ...]} 형태로만 답하라.\n어휘: ' + vocab
        )
        payload = {"components": [{"id": i, "text": t} for i, t in items]}
        try:
            result = llm.complete_json(
                system, json.dumps(payload, ensure_ascii=False), model=model, max_tokens=2048
            )
        except Exception:  # noqa: BLE001 — 어떤 실패든 무보강 폴백
            return None
        if not isinstance(result, dict):
            return None
        return {
            str(k): [c for c in v if c in CAPABILITY_VOCAB]
            for k, v in result.items()
            if isinstance(v, list)
        }

    return _classify


def get_classifier(settings: Settings | None = None) -> CapabilityClassifier | None:
    """키가 있으면 Claude 분류기, 없으면 None(무보강)."""
    cfg = settings or load_settings()
    if cfg.use_claude and llm.claude_available():
        return claude_classifier(cfg.claude_model)
    return None


class CapabilityEnricher:
    """caps 가 빈 컴포넌트를 배치 LLM 분류로 보강한다. 분류기 없으면 무보강(원본 그대로)."""

    def __init__(
        self,
        classifier: CapabilityClassifier | None = None,
        settings: Settings | None = None,
        batch_size: int = 40,
        max_enrich: int = 150,
    ) -> None:
        # classifier 를 명시하지 않으면 설정에서 해석(키 없으면 None).
        self._classifier = classifier if classifier is not None else get_classifier(settings)
        self._batch = max(1, batch_size)
        self._max = max_enrich

    @property
    def active(self) -> bool:
        return self._classifier is not None and self._max > 0

    def enrich(self, components: list[Component]) -> list[Component]:
        """caps 빈 컴포넌트를 제자리 보강하고 같은 리스트를 반환한다(가변 모델)."""
        if not self.active:
            return components
        targets = [c for c in components if not c.capability_tags]
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
                valid = [c for c in caps if c in CAPABILITY_VOCAB]
                if comp is not None and valid:
                    comp.capability_tags = valid
                    comp.provides = valid
                    enriched += 1
        if len(targets) > self._max:
            log.warning("capability 보강 상한 절단 — 대상 %d 중 %d개만(max_enrich)", len(targets), self._max)
        log.info("capability LLM 보강: %d개 태깅(대상 %d)", enriched, len(capped))
        return components
