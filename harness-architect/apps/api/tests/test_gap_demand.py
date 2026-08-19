"""Gap 수요 집계 + 저작 제안 주석(Phase 14 후속)."""

from __future__ import annotations

from harness_api.gap_demand import GapDemand
from harness_api.orchestrator import _tool_search
from harness_catalog import CapabilityGap


def test_gap_demand_counts_and_ranks():
    gd = GapDemand()
    gd.record([{"capability": "media.video", "suggested_type": "mcp"}])
    gd.record([{"capability": "media.video", "suggested_type": "mcp"},
               {"capability": "comms.email", "suggested_type": "mcp"}])
    top = gd.top(5)
    assert top[0]["capability"] == "media.video" and top[0]["count"] == 2
    assert gd.hot_capabilities(5) == {"media.video", "comms.email"}


def test_gap_demand_accepts_objects():
    gd = GapDemand()
    gd.record([CapabilityGap(capability="data.relational", reason="x", suggested_type="mcp")])
    assert gd.top(1)[0]["capability"] == "data.relational"


class _FakeRec:
    """gap 하나를 내는 fake 추천기 — _tool_search 주석 경로 검증(네트워크 없음)."""

    def recommend(self, query: str, top_k: int = 5):  # noqa: ANN201
        class R:
            recommendations: list = []
            gaps = [CapabilityGap(capability="media.video", reason="없음", suggested_type="mcp")]
            requirements = ["media.video"]

        return R()


def test_tool_search_marks_hot_gaps():
    text, _events = _tool_search(_FakeRec(), "영상 편집", hot_capabilities={"media.video"})
    assert "★자주 요청됨" in text
    # hot 아니면 별표 없음
    text2, _ = _tool_search(_FakeRec(), "영상 편집", hot_capabilities=set())
    assert "★자주 요청됨" not in text2
