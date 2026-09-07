"""랭킹 eval — 골든셋 회귀 펜스 + 채점기 자체 테스트.

두 층이다:
  1. `test_golden_*` — 실제 골든셋을 시드 카탈로그에 돌려 **하한선**을 건다. `ranking.py` 나
     추출·그라운딩이 나빠지면 여기서 깨진다. 좋아지면 통과하고, 그때 하한선을 올린다.
  2. 나머지 — 채점기가 실제로 실패를 잡는지 본다. eval 이 아무것도 못 잡으면 펜스가 아니다.
"""

from __future__ import annotations

import pytest
import yaml
from harness_catalog import build_registry
from harness_catalog.rank_eval import (
    KIND,
    GoldenSet,
    RankingCase,
    build_eval_recommender,
    evaluate,
    evaluate_case,
    format_report,
    load_cases,
)

# ── 기준선(2026-09-07, 시드 카탈로그 13개 · LocalEmbedder · 휴리스틱 추출) ──
# 개선하면 이 값을 올려라. 내리는 커밋은 근거를 남겨라.
BASELINE_MEAN_RR = 0.66  # 실측 0.6629
BASELINE_RECALL = 1.0
BASELINE_ORDER_OK = 5  # 7쌍 중 5 — 나머지 2는 골든셋에 주석으로 적어둔 알려진 약점


@pytest.fixture(scope="module")
def report():
    registry = build_registry()
    return evaluate(build_eval_recommender(registry), load_cases())


# ── 1. 골든셋 회귀 펜스 ──


def test_golden_all_hard_checks_pass(report):
    """하드 판정 — 기대 id 포함 · 잡음 배제 · gap 정합. 파이프라인 계약이라 깨지면 회귀다."""
    assert report.failed == [], "\n" + format_report(report, verbose=True)


def test_golden_recall_floor(report):
    assert report.mean_recall >= BASELINE_RECALL, format_report(report)


def test_golden_mean_rr_floor(report):
    """기대 컴포넌트의 평균 역순위 — 순위가 밀리면 연속적으로 떨어진다(사라져야만 잡히는 게 아니라)."""
    assert report.mean_rr >= BASELINE_MEAN_RR, format_report(report, verbose=True)


def test_golden_preference_floor(report):
    """선호 순서 만족 수. 케이스 판정에는 안 들어가지만 총합이 줄면 퇴행이다."""
    assert report.order_ok >= BASELINE_ORDER_OK, format_report(report, verbose=True)


def test_golden_scored_subset_excludes_all_gap_cases(report):
    """전부-gap 케이스는 순위 집계에서 빠져야 한다 — 공허한 1.0 이 평균을 부풀리면 펜스가 둔해진다."""
    scored = {c.name for c in report.scored_cases}
    assert "media-all-gap" not in scored
    assert "data-all-gap" not in scored
    assert scored, "순위 채점 케이스가 하나도 없다"


# ── 2. 채점기 자체 ──


@pytest.fixture(scope="module")
def rec():
    return build_eval_recommender(build_registry())


def test_missing_expected_id_fails(rec):
    """카탈로그에 없는 id 를 기대하면 반드시 실패해야 한다(채점기가 무르면 펜스가 아니다)."""
    result = evaluate_case(rec, RankingCase(name="x", description="깃허브 이슈를 분류한다.", expect_ids=["nope-mcp"]))
    assert not result.passed
    assert result.missing == ["nope-mcp"]
    assert result.recall == 0.0
    assert result.ranks["nope-mcp"] == 0


def test_leaked_absent_id_fails(rec):
    result = evaluate_case(
        rec,
        RankingCase(
            name="x",
            description="깃허브 이슈를 읽고 우선순위 라벨로 분류한다.",
            expect_absent=["github-mcp"],  # 실제로는 나온다 → 잡혀야 한다
        ),
    )
    assert not result.passed
    assert result.leaked == ["github-mcp"]


def test_gap_mismatch_reported_both_directions(rec):
    """누락 gap 은 `-`, 잉여 gap 은 `+`. 거짓 gap 도 회귀다(둘 다 잡아야 한다)."""
    result = evaluate_case(
        rec,
        RankingCase(
            name="x",
            description="유튜브 쇼츠 영상을 자막 붙여 인코딩한다.",
            expect_gaps=["media.video", "nothing.here"],
        ),
    )
    assert not result.passed
    assert "-nothing.here" in result.gap_diff  # 기대했는데 안 남
    assert "+media.edit" in result.gap_diff  # 안 적었는데 남


def test_exact_gaps_false_allows_extra_gaps(rec):
    """`exact_gaps: false` 면 잉여 gap 을 눈감는다 — 부분 명세 케이스용."""
    result = evaluate_case(
        rec,
        RankingCase(
            name="x",
            description="유튜브 쇼츠 영상을 자막 붙여 인코딩한다.",
            expect_gaps=["media.video"],
            exact_gaps=False,
        ),
    )
    assert result.passed, result.gap_diff


def test_rank_read_from_full_list_not_top_k(rec):
    """순위는 top_k 바깥에서도 읽혀야 한다 — 6위→7위 퇴행을 '사라짐'으로 뭉개지 않기 위해."""
    case = RankingCase(
        name="x",
        description=(
            "GitHub PR 을 코드 리뷰하고 결과를 슬랙으로 알려주는 봇. "
            "팀 코딩 컨벤션을 따르고 시크릿이 새지 않게 스캔한다."
        ),
        top_k=1,
        expect_ids=["pr-review-skill"],
    )
    result = evaluate_case(rec, case)
    assert result.returned == ["github-mcp"]  # top_k=1 로 잘림
    assert not result.passed  # top_k 안에 없으니 하드 판정은 실패
    assert result.ranks["pr-review-skill"] > 1  # 그래도 순위는 읽힌다


def test_prefer_order_needs_both_present(rec):
    """한쪽이 아예 안 나오면 선호 순서 만족으로 치지 않는다(공짜 점수 방지)."""
    result = evaluate_case(
        rec,
        RankingCase(
            name="x",
            description="깃허브 이슈를 읽고 우선순위 라벨로 분류한다.",
            prefer_order=[["issue-triage-skill", "nope-mcp"]],
        ),
    )
    assert result.order_total == 1
    assert result.order_ok == 0
    assert result.passed  # 선호 순서는 케이스 판정에 넣지 않는다


def test_load_cases_rejects_wrong_kind(tmp_path):
    """프롬프트 eval(pr-review.yaml)을 잘못 넣으면 거부해야 한다."""
    p = tmp_path / "wrong.yaml"
    p.write_text(
        yaml.safe_dump({"scenario": "pr-review", "cases": []}, allow_unicode=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=KIND):
        load_cases(p)


# ── 3. 펜스가 실제로 회귀를 잡는가(메타) ──
#
# "테스트가 있다" 와 "테스트가 회귀를 잡는다" 는 다르다. 랭킹 가중치를 흔들어 지표가
# 실제로 떨어지는지 못 박는다. 이게 없으면 골든셋이 조용히 무력해져도 아무도 모른다.


@pytest.mark.parametrize(
    ("attr", "bad_value"),
    [
        ("_W_TOKENS", 5.0),  # 비용 감점 폭주 → issue-triage·mixed 의 스킬/MCP 순서가 뒤집힌다
        ("_W_EMBED", 0.0),  # 임베딩 축 제거 → 컨벤션/알림·프롬프트 조각 순서가 뒤집힌다
    ],
)
def test_fence_catches_ranking_regression(monkeypatch, attr, bad_value):
    from harness_catalog import ranking

    monkeypatch.setattr(ranking, attr, bad_value)
    degraded = evaluate(build_eval_recommender(build_registry()), load_cases())
    assert degraded.order_ok < BASELINE_ORDER_OK, (
        f"{attr}={bad_value} 로 랭킹을 망가뜨렸는데 선호순서 지표가 안 떨어졌다 — "
        f"골든셋이 이 축을 못 덮는다.\n{format_report(degraded, verbose=True)}"
    )


@pytest.mark.parametrize("attr", ["_W_CAPABILITY", "_W_EXPLORE"])
def test_known_blind_spots_are_still_blind(monkeypatch, attr):
    """시드 카탈로그가 못 덮는 축을 명시적으로 고정한다(모듈 docstring 의 실측 근거).

    `_W_EXPLORE` 는 usage_count 가 전부 0 이라, `_W_CAPABILITY` 는 매칭 개수가 같아 상수항이다.
    **이 테스트가 깨지면 좋은 소식이다** — 카탈로그가 그 축을 가르기 시작했다는 뜻이므로,
    docstring 의 한계 서술과 하한선을 갱신하고 이 테스트를 지워라.
    """
    from harness_catalog import ranking

    monkeypatch.setattr(ranking, attr, 0.0)
    degraded = evaluate(build_eval_recommender(build_registry()), load_cases())
    assert degraded.order_ok == BASELINE_ORDER_OK
    assert degraded.failed == []


def test_evaluation_is_deterministic(rec):
    """같은 입력에 같은 수 — 회귀 판정의 전제."""
    golden = GoldenSet(cases=[RankingCase(name="x", description="노션 위키를 참고해 회의록 초안을 쓴다.")])
    first = evaluate(rec, golden)
    second = evaluate(rec, golden)
    assert first.model_dump() == second.model_dump()
