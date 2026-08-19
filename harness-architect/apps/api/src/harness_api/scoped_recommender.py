"""스코프 인지 추천 — 전역 카탈로그 결과에 그 유저의 저작(ready) 컴포넌트를 합친다(Phase 14 피드백 루프).

저작 컴포넌트가 재사용되려면 검색에 나와야 한다. 전역 추천기는 유저 무관 싱글턴이라(2054+ 카탈로그를
1회 색인) 유저 컴포넌트를 안 담는다. 여기서 유저의 (소수) ready 컴포넌트만 **같은 임베더**로 즉석
점수화(`rank_components`)해 전역 결과와 병합하고, gap 은 전역∪유저 커버리지로 재계산한다 — 유저가 만든
능력은 더 이상 gap 이 아니다(gap → 저작 → 재사용 → gap 닫힘).

전역 인덱스는 안 건드린다(재임베딩 없음). 유저 집합은 작아 즉석 임베딩이 값싸다.
"""

from __future__ import annotations

from harness_catalog import Recommendation, Recommender, RecommendResult
from harness_resolver import Component


class ScopedRecommender:
    """전역 Recommender + 이 요청 유저의 저작 컴포넌트를 병합해 recommend 한다."""

    def __init__(self, base: Recommender, user_components: list[Component]) -> None:
        self._base = base
        self._user = user_components

    def recommend(self, description: str, top_k: int = 6) -> RecommendResult:
        g = self._base.recommend(description, top_k=top_k)
        if not self._user:
            return g
        extra = self._base.rank_components(self._user, g.requirements, description, top_k=top_k)
        merged: dict[str, Recommendation] = {r.id: r for r in g.recommendations}
        for r in extra:  # 유저 저작이 id 충돌 시 우선(자기 것 재사용)
            merged[r.id] = r
        recs = sorted(merged.values(), key=lambda r: -r.score)[:top_k]
        user_caps = {c for comp in self._user for c in [*comp.provides, *comp.capability_tags]}
        gaps = [gp for gp in g.gaps if gp.capability not in user_caps]  # 유저가 채운 능력은 gap 아님
        groups: dict[str, list[str]] = {}
        for r in recs:
            groups.setdefault(r.type, []).append(r.id)
        return g.model_copy(update={"recommendations": recs, "gaps": gaps, "groups": groups})
