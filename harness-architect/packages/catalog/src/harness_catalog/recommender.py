"""RAG 추천 엔진 — 기획 §3.1. 제품의 심장.

흐름: 프로젝트 설명 → ① 요구 능력 추출 → ② 카탈로그 검색(임베딩 top-K) →
③ 랭킹·근거 → 추천 목록(타입별 그룹). 키가 없으면 전 구간 로컬 폴백으로 관통한다.
"""

from __future__ import annotations

from harness_resolver import Component, Registry
from pydantic import BaseModel

from .embeddings import Embedder, get_embedder
from .ranking import RankedComponent, rank
from .reasoning import Reasoner, get_reasoner
from .store import VectorStore
from .vocabulary import extract_capabilities_heuristic


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


class RecommendResult(BaseModel):
    description: str
    requirements: list[str]
    extraction_mode: str  # "claude" | "heuristic"
    ranking_mode: str  # "claude" | "heuristic"
    recommendations: list[Recommendation]
    groups: dict[str, list[str]]  # type → [component id] (화면 B 그룹 탭)


class Recommender:
    def __init__(
        self,
        registry: Registry,
        embedder: Embedder | None = None,
        reasoner: Reasoner | None = None,
    ) -> None:
        self.registry = registry
        self.embedder = embedder or get_embedder()
        self.reasoner = reasoner or get_reasoner()
        self.store = VectorStore()
        self._by_id: dict[str, Component] = {}
        self._index()

    def _index(self) -> None:
        comps = self.registry.all()
        self._by_id = {c.id: c for c in comps}
        if not comps:
            return
        vectors = self.embedder.embed([c.embedding_document() for c in comps])
        for c, v in zip(comps, vectors, strict=True):
            self.store.add(c.id, v)

    # ── ① 요구 능력 추출 ──
    def extract_requirements(self, description: str) -> tuple[list[str], str]:
        caps = self.reasoner.extract_requirements(description)
        if caps is not None:
            return caps, self.reasoner.name
        return extract_capabilities_heuristic(description), "heuristic"

    # ── ②③ 검색 + 랭킹 ──
    def recommend(self, description: str, top_k: int = 6) -> RecommendResult:
        requirements, extraction_mode = self.extract_requirements(description)

        query = description + " " + " ".join(requirements)
        qvec = self.embedder.embed([query])[0]
        # 전체 후보에 대해 임베딩 점수를 받고(회수), 이후 구조화 신호로 랭킹(2단 구조).
        hits = self.store.search(qvec, top_k=len(self._by_id) or 1)
        candidates = [(self._by_id[cid], score) for cid, score in hits if cid in self._by_id]

        ranked = rank(candidates, requirements)
        top = ranked[:top_k]
        ranking_mode = self._enrich_reasons(top, description)

        recommendations = [self._to_recommendation(r) for r in top]
        groups: dict[str, list[str]] = {}
        for rec in recommendations:
            groups.setdefault(rec.type, []).append(rec.id)

        return RecommendResult(
            description=description,
            requirements=requirements,
            extraction_mode=extraction_mode,
            ranking_mode=ranking_mode,
            recommendations=recommendations,
            groups=groups,
        )

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
