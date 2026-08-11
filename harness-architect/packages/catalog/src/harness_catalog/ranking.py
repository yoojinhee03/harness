"""랭킹 — 검색으로 회수한 후보를 프로젝트 대비 순위매기고 근거를 붙인다.

설계: 기획 §3.1(4단계 랭킹·근거), 피드백 루프 §4(집계 신호 가중), 카탈로그 스키마 §4
(퍼지 회수 → 구조화 후처리). 기본은 휴리스틱; ANTHROPIC_API_KEY 있으면 Claude 가 근거를
프로즈로 다듬는다(랭킹 축은 유지).

랭킹 축: 임베딩 유사도 + 요구 능력 매칭 + 관련성 대비 비용 + 사용/유지 신호 + 탐색 부스트.
"""

from __future__ import annotations

import math

from harness_resolver import Component
from pydantic import BaseModel

# 가중치 — 요구 능력 매칭이 지배적, 비용은 감점, 피드백 신호는 소폭.
_W_EMBED = 1.0
_W_CAPABILITY = 2.5
_W_TOKENS = 0.15  # per 1k 컨텍스트 토큰 감점
_W_TOOLS = 0.02  # per 도구 감점
# ⚠️ usage_count·retention_score 는 피드백 루프(docs/plan/09)가 채우기 전까지 시드에서 전부 0 이라
#    아래 두 항은 현재 점수에 사실상 0 을 더한다(inert). 피드백 루프가 활성화되면 그때 신호가 산다.
#    지금은 랭킹을 실질적으로 embed(_W_EMBED)+capability(_W_CAPABILITY)-cost 가 지배한다.
_W_USAGE = 0.10
_W_RETENTION = 0.30
_W_EXPLORE = 0.05  # 신규·저사용 탐색 부스트 (리치-겟-리처 완화)


class RankedComponent(BaseModel):
    component: Component
    score: float
    embed_score: float
    matched_capabilities: list[str]
    reason: str


def rank(
    candidates: list[tuple[Component, float]],
    requirements: list[str],
) -> list[RankedComponent]:
    """(컴포넌트, 임베딩점수) 후보를 랭킹한다. 내림차순 정렬 결과."""
    req = set(requirements)
    ranked: list[RankedComponent] = []
    for component, embed_score in candidates:
        matched = sorted(set(component.capability_tags) & req)
        cost = component.cost

        score = _W_EMBED * embed_score
        score += _W_CAPABILITY * len(matched)
        score -= _W_TOKENS * (cost.context_tokens / 1000.0)
        score -= _W_TOOLS * cost.added_tools
        score += _W_USAGE * math.log1p(component.usage_count)
        score += _W_RETENTION * component.retention_score
        if component.usage_count == 0:
            score += _W_EXPLORE

        ranked.append(
            RankedComponent(
                component=component,
                score=round(score, 4),
                embed_score=round(embed_score, 4),
                matched_capabilities=matched,
                reason=_heuristic_reason(component, matched),
            )
        )
    ranked.sort(key=lambda r: -r.score)
    return ranked


def _heuristic_reason(component: Component, matched: list[str]) -> str:
    bits: list[str] = []
    if matched:
        bits.append(f"요구 능력 {'·'.join(matched)} 매칭")
    elif component.provides:
        bits.append(f"{'·'.join(component.provides[:2])} 제공")
    ctx = component.cost.context_tokens
    if ctx:
        bits.append(f"컨텍스트 {ctx}토큰")
    if component.cost.added_tools:
        bits.append(f"도구 +{component.cost.added_tools}")
    if component.requires:
        bits.append(f"의존: {'·'.join(component.requires)}")
    return " · ".join(bits) if bits else component.summary
