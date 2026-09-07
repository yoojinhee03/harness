"""피드백 신호 — 실사용 keep/drop 을 랭킹 신호로 (진행 플랜 Phase 9).

`ranking.py` 는 `usage_count`·`retention_score` 를 이미 가중하지만 **신호를 채우는 파이프가
비어 있었다** — 시드에서 전부 0 이라 두 항이 상수처럼 죽어 있다(랭킹 골든셋이 이 축을 못 재는
이유도 같다: `test_known_blind_spots_are_still_blind`). 여기가 그 파이프의 순수 집계부다.

**보수적으로 센다.** 소량 데이터에서 retention 이 과적합하면 랭킹이 우연에 흔들린다. 관측이
`MIN_OBSERVATIONS` 미만인 컴포넌트는 **중립 처리**한다 — usage·retention 둘 다 0, 즉 신호가
붙기 전과 정확히 같은 점수다. "데이터가 적을 땐 아무 말도 하지 않는다"가 기본값이다.

**순수하다.** DB·네트워크를 모른다. 집계 레코드를 받아 Component 를 새로 만들어 돌려준다.
영속·수집은 `harness_api.feedback`(스토어)과 호출부의 몫이다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from harness_resolver import Component
from pydantic import BaseModel, Field

# 이 횟수 미만으로 관측된 컴포넌트는 중립(신호 없음). 실데이터가 쌓이면 재보정 대상이다.
MIN_OBSERVATIONS = 5


class FeedbackRecord(BaseModel):
    """컴포넌트 하나에 대한 누적 관측 — 스토어가 이 모양으로 준다."""

    component_id: str
    selected_count: int = 0  # 최종 구성에 포함됨(eject·저장 등 확정 시점)
    dropped_count: int = 0  # 추천/후보에 올랐으나 최종 구성에서 빠짐

    @property
    def observations(self) -> int:
        return self.selected_count + self.dropped_count


class UsageSignal(BaseModel):
    """랭킹에 주입할 신호. `confident=False` 면 두 수치는 0(중립)이다."""

    usage_count: int = 0
    retention_score: float = 0.0
    confident: bool = False


def usage_signal(record: FeedbackRecord, *, min_observations: int = MIN_OBSERVATIONS) -> UsageSignal:
    """관측 → 신호. 임계 미만이면 중립(랭킹 불변).

    retention 은 keep 비율이다. 분모가 관측 총합이라, 많이 추천됐는데 늘 빠지는 컴포넌트는
    자연히 낮아진다(노출량이 아니라 *채택률* 을 본다).
    """
    if record.observations < min_observations:
        return UsageSignal()
    return UsageSignal(
        usage_count=record.selected_count,
        retention_score=round(record.selected_count / record.observations, 4),
        confident=True,
    )


def usage_signals(
    records: Iterable[FeedbackRecord], *, min_observations: int = MIN_OBSERVATIONS
) -> dict[str, UsageSignal]:
    """id → 신호. 중립인 것도 담는다(호출부가 '관측은 있었으나 부족'을 구분할 수 있게)."""
    return {r.component_id: usage_signal(r, min_observations=min_observations) for r in records}


def apply_signals(
    components: Iterable[Component], signals: Mapping[str, UsageSignal]
) -> list[Component]:
    """컴포넌트에 신호를 입힌 **새 리스트**를 만든다(입력을 변형하지 않는다).

    신호가 없거나 중립이면 원본을 그대로 둔다 — 카탈로그가 선언한 값을 덮어쓰지 않는다.
    """
    out: list[Component] = []
    for c in components:
        sig = signals.get(c.id)
        if sig is None or not sig.confident:
            out.append(c)
            continue
        out.append(c.model_copy(update={"usage_count": sig.usage_count, "retention_score": sig.retention_score}))
    return out


class FeedbackEvent(BaseModel):
    """한 번의 확정 관측 — 무엇을 골랐고 무엇을 버렸나.

    `dropped` 는 "후보에 올랐는데 안 쓴 것"이다. 이걸 안 받으면 retention 은 늘 1.0 이 되어
    아무 변별력이 없다 — 채택률의 분모가 노출이기 때문이다.
    """

    selected: list[str] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    source: str = ""  # eject | harness_save | studio | recommend

    def normalized(self) -> tuple[list[str], list[str]]:
        """중복 제거 + 양쪽에 걸친 id 는 selected 우선(모순 입력 방어)."""
        sel = sorted({i for i in self.selected if i})
        drop = sorted({i for i in self.dropped if i} - set(sel))
        return sel, drop
