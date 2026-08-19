"""RAG 추천 엔진 — 기획 §3.1. 제품의 심장.

흐름: 프로젝트 설명 → ① 요구 능력 추출 → ② 카탈로그 검색(임베딩 top-K) →
③ 랭킹·근거 → 추천 목록(타입별 그룹) + gap 신호. 키가 없으면 전 구간 로컬 폴백으로 관통한다.

그라운딩 계약(작업 1): 추천 후보는 **카탈로그 검색 결과에서만** 나온다. LLM 은 랭킹·근거로만 관여하며
새 컴포넌트를 정의할 수 없다(스키마상 `Recommendation` 은 카탈로그 id 참조만 표현 가능). 반환 직전 모든
id 를 레지스트리에 대조하고, 미존재 id 는 제거·경고한다. 검색이 어떤 요구 능력을 못 채우면 그 능력은
gap 신호로 나간다(발명 금지). 부분 커버리지("찾은 N개 + gap M개")는 실패가 아니라 정상 결과다.

gap 판정은 **통제 어휘 정합(strict)** 으로 한다 — 어떤 카탈로그 컴포넌트도 그 능력을 provides/tag 하지
않으면 gap. 임베딩 점수 임계값이 아니라 계약 필드로 판정하므로 임베더 스케일에 무관하고 결정적이다.
임베딩 점수는 '무관한 추천 카드'를 걷어내는 relevance floor 로만 쓴다(발명이 아니라 잡음 억제).
"""

from __future__ import annotations

import json
import logging
import math

from harness_resolver import Component, Registry
from pydantic import BaseModel

from .embeddings import Embedder, cosine, get_embedder
from .ranking import RankedComponent, rank
from .reasoning import Reasoner, get_reasoner
from .store import VectorStore, VectorStoreLike, content_hash
from .vocabulary import (
    extract_capabilities_heuristic,
    facet_for_capability,
    is_valid_capability,
    suggested_component_type,
)

log = logging.getLogger("harness_catalog.recommender")

# 요구 능력이 매칭되지 않은 후보는 이 임베딩 유사도 이상일 때만 추천 카드로 남긴다.
# LocalEmbedder 실측(시드 카탈로그): 연관 컴포넌트 ≥0.27, 무관 도메인 잡음 ≤0.15 → 0.20 이 경계.
# ⚠️ 절대 임계값이라 임베더 교체 시 재보정 대상. 단, gap 판정은 이 값과 무관(통제 어휘 정합)하므로
#    floor 오보정이 '발명'을 유발하진 않는다 — 잡음 카드가 조금 새거나 덜 새는 표시 이슈일 뿐.
RELEVANCE_FLOOR = 0.20


# 집계 스크립트(scripts/aggregate_gaps.py)가 파싱하는 안정적 마커. 형식: `GAP_SIGNAL {json}`.
GAP_SIGNAL_MARKER = "GAP_SIGNAL"


def _log_gaps(gaps: list[CapabilityGap]) -> None:
    """각 gap 을 기계가 읽을 수 있는 한 줄로 남긴다(운영 로그 파이프라인이 durable 하게 보관)."""
    for g in gaps:
        payload = {"capability": g.capability, "suggested_type": g.suggested_type, "facet": g.facet}
        log.info("%s %s", GAP_SIGNAL_MARKER, json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _valid_caps(caps: list[str]) -> list[str]:
    """`domain.capability` 형태만 통과시키고 순서를 보존해 중복 제거(추출 결과 정규화)."""
    seen: set[str] = set()
    out: list[str] = []
    for cap in caps:
        if is_valid_capability(cap) and cap not in seen:
            seen.add(cap)
            out.append(cap)
    return out


class Recommendation(BaseModel):
    """화면 B 카드 한 장 분량 — 근거·능력·비용·충돌을 함께 노출."""

    id: str
    type: str
    name: str
    version: str
    summary: str
    score: float
    reason: str
    provides: list[str]
    requires: list[str]
    matched_capabilities: list[str]
    context_tokens: int
    added_tools: int
    exclusive_group: str | None
    conflicts_with: list[str]
    auth_required: bool


class CapabilityGap(BaseModel):
    """카탈로그가 못 채운 요구 능력 — 발명 대신 내보내는 정직한 결핍 신호(작업 1·3).

    필드명은 기존 어휘와 정렬한다: `capability` 는 resolver `Diagnostic.capability` 와, `reason` 은
    `Recommendation.reason` 과 같은 이름을 쓴다(프론트에서 gap 카드를 추천 카드 옆에 동등하게 렌더).
    resolver gap 과 달리 `component_id` 가 없다 — 이건 특정 컴포넌트의 미충족 requires 가 아니라
    **프로젝트가 필요로 하나 카탈로그에 없는 능력**이기 때문이다. 대신 `suggested_type` 으로
    "어떤 컴포넌트 타입이 이걸 채울 수 있나"를 준다(콜드스타트 시딩 큐의 입력).
    """

    capability: str
    reason: str
    suggested_type: str  # skill | mcp | context | hook — facet 기반 추정
    facet: str | None = None


class RecommendResult(BaseModel):
    description: str
    requirements: list[str]
    extraction_mode: str  # "claude" | "heuristic"
    ranking_mode: str  # "claude" | "heuristic"
    recommendations: list[Recommendation]
    gaps: list[CapabilityGap]  # 카탈로그가 못 채운 요구 능력(부분 커버리지의 절반)
    groups: dict[str, list[str]]  # type → [component id] (화면 B 그룹 탭)


class Recommender:
    def __init__(
        self,
        registry: Registry,
        embedder: Embedder | None = None,
        reasoner: Reasoner | None = None,
        store: VectorStoreLike | None = None,
    ) -> None:
        self.registry = registry
        self.embedder = embedder or get_embedder()
        self.reasoner = reasoner or get_reasoner()
        # store: 인메모리(기본) 또는 pgvector(영속). 둘 다 ensure/search 계약을 만족한다.
        self.store: VectorStoreLike = store if store is not None else VectorStore()
        self._by_id: dict[str, Component] = {}
        # 능력 → 그 능력을 provides/tag 하는 컴포넌트 id (strict 커버리지 판정용, gap 계산).
        self._provided_index: dict[str, list[str]] = {}
        self._index()

    def _index(self) -> None:
        comps = self.registry.all()
        self._by_id = {c.id: c for c in comps}
        self._provided_index = {}
        for c in comps:
            for cap in set(c.provides) | set(c.capability_tags):
                self._provided_index.setdefault(cap, []).append(c.id)
        if not comps:
            return
        # 스토어가 임베딩을 소유·회수한다. 영속 스토어(pgvector)는 (id, content_hash) 가 그대로면
        # 재임베딩을 건너뛴다 → 재시작마다 카탈로그 전량 재임베딩하던 비용/지연 제거.
        entries = [(c.id, content_hash(doc := c.embedding_document()), doc) for c in comps]
        self.store.ensure(entries, self.embedder.embed)

    # ── ① 요구 능력 추출 (카탈로그 무관 — 카탈로그보다 넓어야 gap 이 난다, 작업 2) ──
    def extract_requirements(self, description: str) -> tuple[list[str], str]:
        """설명 → 요구 능력. 카탈로그에 무엇이 있는지 모르는 채로 '이 제품에 필요한 역량'만 낸다.

        LLM(품질) 경로는 vocab 밖 신규 능력(예: media.transcode)도 낼 수 있어 미시딩 도메인이 gap 으로
        표면화된다. 어떤 경로든 결과는 `domain.capability` 형태만 통과시킨다(형태 검증, 멤버십 아님).
        """
        caps = self.reasoner.extract_requirements(description)
        if caps is not None:
            return _valid_caps(caps), self.reasoner.name
        return _valid_caps(extract_capabilities_heuristic(description)), "heuristic"

    # ── ②③ 검색 + 랭킹 + 그라운딩 + gap ──
    def recommend(self, description: str, top_k: int = 6) -> RecommendResult:
        requirements, extraction_mode = self.extract_requirements(description)

        query = description + " " + " ".join(requirements)
        qvec = self.embedder.embed([query])[0]
        # 전체 후보에 대해 임베딩 점수를 받고(회수), 이후 구조화 신호로 랭킹(2단 구조).
        hits = self.store.search(qvec, top_k=len(self._by_id) or 1)
        candidates = [(self._by_id[cid], score) for cid, score in hits if cid in self._by_id]

        ranked = rank(candidates, requirements, cap_weight=self._cap_weight(requirements))
        # 그라운딩: 무관한 잡음 카드를 걷어낸다(요구 능력 매칭 또는 임베딩 floor 이상만 남김).
        relevant = [r for r in ranked if self._is_relevant(r)]
        top = self._catalog_verified(relevant)[:top_k]
        ranking_mode = self._enrich_reasons(top, description)

        recommendations = [self._to_recommendation(r) for r in top]
        gaps = self._compute_gaps(requirements)
        _log_gaps(gaps)  # 콜드스타트 큐 입력 — 집계 스크립트가 "자주 요청되나 없는 능력"을 뽑는다(작업 3)
        groups: dict[str, list[str]] = {}
        for rec in recommendations:
            groups.setdefault(rec.type, []).append(rec.id)

        return RecommendResult(
            description=description,
            requirements=requirements,
            extraction_mode=extraction_mode,
            ranking_mode=ranking_mode,
            recommendations=recommendations,
            gaps=gaps,
            groups=groups,
        )

    def rank_components(
        self, components: list[Component], requirements: list[str], description: str, top_k: int = 6
    ) -> list[Recommendation]:
        """주어진 컴포넌트들을 요구·설명 대비 랭킹해 Recommendation 으로 반환(외부 병합용).

        전역 인덱스에 없는 소규모 집합(예: 유저 저작 컴포넌트)을 같은 임베더·그라운딩(relevance floor·
        cap_weight)으로 점수화한다. gap 계산·로깅은 하지 않는다(호출부가 병합·재계산). 스코프 인지 검색의
        피드백 루프에 쓴다 — 저작 컴포넌트가 재사용되게.
        """
        if not components:
            return []
        query = description + " " + " ".join(requirements)
        qvec = self.embedder.embed([query])[0]
        vecs = self.embedder.embed([c.embedding_document() for c in components])
        candidates = [(c, cosine(qvec, v)) for c, v in zip(components, vecs, strict=True)]
        ranked = rank(candidates, requirements, cap_weight=self._cap_weight(requirements))
        relevant = [r for r in ranked if self._is_relevant(r)]
        return [self._to_recommendation(r) for r in relevant[:top_k]]

    def _cap_weight(self, requirements: list[str]) -> dict[str, float]:
        """요구 능력별 IDF 식 신뢰 가중치(0~1). 전역에 과다 부여된 능력일수록 낮다(잡음 태그 억제).

        df=1(고유 능력) → 1.0. df 가 클수록(수확 오탐이 몰린 태그) 급감. 큐레이션 시드는 능력별 df=1 이라
        전부 1.0 → 랭킹 불변. 대규모 수확 카탈로그에서만 실효(예: vcs.code-review df=553 → ~0.14).
        """
        weight: dict[str, float] = {}
        for cap in requirements:
            df = len(self._provided_index.get(cap, ()))
            weight[cap] = 1.0 / (1.0 + math.log(df)) if df > 1 else 1.0
        return weight

    @staticmethod
    def _is_relevant(r: RankedComponent) -> bool:
        """추천 카드로 남길 만큼 관련 있는가 — 능력 매칭이 있거나 임베딩 유사도가 floor 이상."""
        return bool(r.matched_capabilities) or r.embed_score >= RELEVANCE_FLOOR

    def _catalog_verified(self, ranked: list[RankedComponent]) -> list[RankedComponent]:
        """반환 직전 그라운딩 게이트 — 카탈로그에 실재하는 id 만 통과(미존재는 제거·경고).

        현 파이프라인은 후보를 카탈로그에서만 뽑으므로 정상 경로에선 전부 통과한다. 이 게이트는
        레지스트리 재구성/라이브 refresh 로 인한 드리프트나 향후 회귀에 대한 방어선이다(발명 불가 보증).
        """
        out: list[RankedComponent] = []
        for r in ranked:
            if r.component.id in self._by_id:
                out.append(r)
            else:  # pragma: no cover - 방어적 게이트(정상 경로에선 도달 불가)
                log.warning("추천에서 카탈로그 미존재 id 제거: %s", r.component.id)
        return out

    def _compute_gaps(self, requirements: list[str]) -> list[CapabilityGap]:
        """요구 능력 중 카탈로그가 못 채운 것을 gap 으로. 판정은 통제-어휘 정합(strict)."""
        gaps: list[CapabilityGap] = []
        for cap in requirements:
            if cap in self._provided_index:
                continue  # 어떤 컴포넌트가 이 능력을 provides/tag → 커버됨(gap 아님)
            gaps.append(
                CapabilityGap(
                    capability=cap,
                    reason=f"'{cap}' 능력이 필요하지만 이를 제공하는 컴포넌트가 카탈로그에 없음",
                    suggested_type=suggested_component_type(cap),
                    facet=facet_for_capability(cap),
                )
            )
        return gaps

    def _enrich_reasons(self, ranked: list[RankedComponent], description: str) -> str:
        """랭킹 근거를 Reasoner 로 다듬는다. None 이면 휴리스틱 근거 유지."""
        if not ranked:
            return "heuristic"
        items = [(r.component.id, r.component.summary, r.component.provides) for r in ranked]
        reasons = self.reasoner.rank_reasons(description, items)
        if not reasons:
            return "heuristic"
        for r in ranked:
            if r.component.id in reasons:
                r.reason = reasons[r.component.id]
        return self.reasoner.name

    @staticmethod
    def _to_recommendation(r: RankedComponent) -> Recommendation:
        c = r.component
        return Recommendation(
            id=c.id,
            type=c.type,
            name=c.name,
            version=c.version,
            summary=c.summary,
            score=r.score,
            reason=r.reason,
            provides=c.provides,
            requires=c.requires,
            matched_capabilities=r.matched_capabilities,
            context_tokens=c.cost.context_tokens,
            added_tools=c.cost.added_tools,
            exclusive_group=c.constraints.exclusive_group,
            conflicts_with=c.conflicts_with,
            auth_required=bool(c.auth and c.auth.required),
        )


class LiveRecommender:
    """레지스트리 generation 이 바뀌면 Recommender 를 재구성(재인덱싱)한다.

    라이브 레지스트리(FederatedRegistry)는 TTL refresh 로 컴포넌트 집합이 변할 수 있는데,
    Recommender 는 생성 시 1회 임베딩 인덱싱한다 → 그대로 두면 recommend 가 startup 스냅샷에
    고정된다. 이 래퍼가 `registry.generation()` 변화를 감지해 재구성 → recommend 도 실시간 반영.
    `generation()` 이 없는 정적 레지스트리(라이브 off)면 1회 구성 후 고정(무비용).

    비고: 재구성은 전체 재임베딩이다. LocalEmbedder 는 값싸고, Voyage 는 비용이 있으나
    **내용이 바뀔 때만** 돈다(같은 집합이면 generation 불변 → 재사용).
    """

    def __init__(
        self,
        registry: Registry,
        embedder: Embedder | None = None,
        reasoner: Reasoner | None = None,
        store: VectorStoreLike | None = None,
    ) -> None:
        self._registry = registry
        self._embedder = embedder
        self._reasoner = reasoner
        self._store = store  # pgvector 등 영속 스토어(재구성 간 공유 → 영속·재임베딩 회피). None 이면 인메모리.
        self._rec: Recommender | None = None
        self._gen: int | None = None

    def _generation(self) -> int | None:
        gen = getattr(self._registry, "generation", None)
        return gen() if callable(gen) else None

    def get(self) -> Recommender:
        """현재 레지스트리 상태에 맞는 Recommender. generation 이 바뀌었으면 재구성."""
        gen = self._generation()
        if self._rec is None or gen != self._gen:
            self._rec = Recommender(
                self._registry, embedder=self._embedder, reasoner=self._reasoner, store=self._store
            )
            self._gen = gen
        return self._rec
