"""피드백 신호 테스트 (Phase 9) — 실사용 keep/drop 이 랭킹에 닿는가, 그리고 **조용히 닿지 않는가**.

두 방향을 다 고정한다:
  · 신호가 없으면 랭킹이 피드백 이전과 **완전히 같아야** 한다(옵트인 꺼짐이 기본이므로).
  · 신호가 충분히 쌓이면 실제로 순위를 움직여야 한다(안 움직이면 파이프가 헛돈 것).
"""

from __future__ import annotations

import pytest
from harness_catalog import (
    FeedbackEvent,
    FeedbackRecord,
    apply_signals,
    rank,
    usage_signal,
    usage_signals,
)
from harness_catalog.feedback import MIN_OBSERVATIONS
from harness_resolver import Component


def comp(cid: str, **kw) -> Component:
    base = dict(id=cid, type="skill", name=cid, version="1.0.0", provides=["review.code"], body="x")
    return Component(**{**base, **kw})


# ── 순수 집계 ──


def test_below_threshold_is_neutral():
    """관측이 적으면 아무 말도 하지 않는다 — 소량 데이터가 랭킹을 흔들면 안 된다."""
    r = FeedbackRecord(component_id="a", selected_count=MIN_OBSERVATIONS - 1, dropped_count=0)
    sig = usage_signal(r)
    assert sig.confident is False
    assert sig.usage_count == 0 and sig.retention_score == 0.0


def test_at_threshold_becomes_confident():
    r = FeedbackRecord(component_id="a", selected_count=MIN_OBSERVATIONS, dropped_count=0)
    sig = usage_signal(r)
    assert sig.confident is True
    assert sig.usage_count == MIN_OBSERVATIONS and sig.retention_score == 1.0


def test_retention_is_adoption_rate_not_exposure():
    """많이 추천됐는데 늘 빠지면 retention 이 낮아야 한다(분모가 관측 총합)."""
    often_dropped = usage_signal(FeedbackRecord(component_id="a", selected_count=2, dropped_count=18))
    rarely_dropped = usage_signal(FeedbackRecord(component_id="b", selected_count=9, dropped_count=1))
    assert often_dropped.retention_score == 0.1
    assert rarely_dropped.retention_score == 0.9
    # 노출은 often 쪽이 훨씬 많지만 채택률로는 진다.
    assert often_dropped.retention_score < rarely_dropped.retention_score


def test_threshold_is_tunable():
    r = FeedbackRecord(component_id="a", selected_count=2, dropped_count=0)
    assert usage_signal(r).confident is False
    assert usage_signal(r, min_observations=2).confident is True


def test_usage_signals_keeps_neutral_entries():
    """중립도 맵에 담는다 — 호출부가 '관측 없음'과 '관측 부족'을 구분할 수 있어야 한다."""
    sigs = usage_signals([FeedbackRecord(component_id="a", selected_count=1)])
    assert "a" in sigs and sigs["a"].confident is False


# ── Component 주입 ──


def test_apply_signals_does_not_mutate_input():
    original = comp("a")
    out = apply_signals([original], usage_signals([FeedbackRecord(component_id="a", selected_count=10)]))
    assert original.usage_count == 0  # 원본 불변
    assert out[0].usage_count == 10


def test_apply_signals_leaves_declared_values_when_neutral():
    """중립이면 카탈로그 선언값을 덮어쓰지 않는다."""
    declared = comp("a", usage_count=7, retention_score=0.5)
    out = apply_signals([declared], usage_signals([FeedbackRecord(component_id="a", selected_count=1)]))
    assert out[0].usage_count == 7 and out[0].retention_score == 0.5


# ── 랭킹 반영 ──


def _scores(usage=None) -> dict[str, float]:
    candidates = [(comp("popular"), 0.5), (comp("unpopular"), 0.5)]
    return {r.component.id: r.score for r in rank(candidates, ["review.code"], usage=usage)}


def test_no_signal_means_ranking_unchanged():
    """옵트인 꺼짐이 기본이므로, 신호 없이는 점수가 예전과 한 치도 달라지면 안 된다."""
    assert _scores(None) == _scores({}) == _scores(usage_signals([]))
    # 동점(둘 다 usage 0 → explore 부스트 동일)
    s = _scores(None)
    assert s["popular"] == s["unpopular"]


def test_confident_signal_moves_the_ranking():
    """신호가 쌓이면 실제로 순위가 갈려야 한다 — 안 갈리면 파이프가 헛돈 것이다."""
    sigs = usage_signals(
        [
            FeedbackRecord(component_id="popular", selected_count=18, dropped_count=2),
            FeedbackRecord(component_id="unpopular", selected_count=2, dropped_count=18),
        ]
    )
    s = _scores(sigs)
    assert s["popular"] > s["unpopular"]


def test_neutral_signal_does_not_move_the_ranking():
    """임계 미만 관측으로는 순위가 안 움직인다(과적합 방지의 실동작 확인)."""
    sigs = usage_signals(
        [
            FeedbackRecord(component_id="popular", selected_count=3, dropped_count=0),
            FeedbackRecord(component_id="unpopular", selected_count=0, dropped_count=3),
        ]
    )
    assert _scores(sigs) == _scores(None)


def test_signal_overrides_declared_value():
    """실측이 카탈로그 선언값을 이긴다 — 선언은 콜드스타트 추정일 뿐이다."""
    candidates = [(comp("a", usage_count=100, retention_score=1.0), 0.5)]
    declared_only = rank(candidates, ["review.code"])[0].score
    measured = rank(
        candidates,
        ["review.code"],
        usage=usage_signals([FeedbackRecord(component_id="a", selected_count=1, dropped_count=19)]),
    )[0].score
    assert measured < declared_only


# ── 이벤트 정규화 ──


def test_event_normalization_dedups_and_prefers_selected():
    """같은 id 가 양쪽에 오면 selected 우선 — 모순 입력이 카운트를 두 번 올리면 안 된다."""
    sel, drop = FeedbackEvent(selected=["a", "a", "b"], dropped=["b", "c", ""]).normalized()
    assert sel == ["a", "b"]
    assert drop == ["c"]


@pytest.mark.parametrize("event", [FeedbackEvent(), FeedbackEvent(selected=[""], dropped=[""])])
def test_empty_event_yields_nothing(event):
    assert event.normalized() == ([], [])
