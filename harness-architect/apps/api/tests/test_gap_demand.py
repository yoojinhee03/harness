"""GapDemand(DB 영속) 테스트 — 하드닝 TASK 2.

검증: 재시작 후 카운트 유지 · 원자적 증분(다중 인스턴스) · DB 장애 비차단 ·
미해결 우선 정렬 + mark_resolved · hot-gap caps_source 게이팅 · false_gaps 재평가.
"""

from __future__ import annotations

from typing import Any

from harness_api.db import gap_demand as gd_table
from harness_api.db import make_engine
from harness_api.gap_demand import GapDemand
from harness_api.orchestrator import _tool_search
from harness_catalog import CapabilityGap


def _engine(tmp_path: Any) -> Any:
    return make_engine(f"sqlite:///{tmp_path}/t.db")  # make_engine 이 테이블 create_all


def _gap(cap: str, st: str = "mcp") -> dict[str, str]:
    return {"capability": cap, "suggested_type": st}


def test_persist_across_restart(tmp_path: Any) -> None:
    eng = _engine(tmp_path)
    gd = GapDemand(eng)
    gd.record([_gap("vcs.code-hosting")], source="recommend", catalog_revision="r1", candidate_count=5)
    gd.record([_gap("vcs.code-hosting")], source="studio", catalog_revision="r2", candidate_count=7)
    # 재시작 모사 — 새 인스턴스가 같은 DB 에서 누적 카운트를 본다
    top = GapDemand(eng).top()
    assert top and top[0]["capability"] == "vcs.code-hosting"
    assert top[0]["count"] == 2


def test_multi_writer_atomic_increment(tmp_path: Any) -> None:
    eng = _engine(tmp_path)
    a, b = GapDemand(eng), GapDemand(eng)  # 별개 인스턴스 = 레플리카 모사
    for _ in range(3):
        a.record([_gap("comms.email")])
        b.record([_gap("comms.email")])
    assert GapDemand(eng).top()[0]["count"] == 6  # ON CONFLICT DO UPDATE 원자적 누적


def test_nonblocking_on_db_failure(tmp_path: Any) -> None:
    eng = _engine(tmp_path)
    gd = GapDemand(eng)
    gd_table.drop(eng)  # 테이블 제거 → 이후 쓰기/읽기 실패해야 하지만 예외를 삼킨다(비차단)
    gd.record([_gap("x.y")])  # 예외가 나면 테스트 실패
    assert gd.top() == []  # 조회 실패도 [] 로(응답을 깨지 않음)


def test_mark_resolved_and_unresolved_first(tmp_path: Any) -> None:
    eng = _engine(tmp_path)
    gd = GapDemand(eng)
    gd.record([_gap("a.one")])
    gd.record([_gap("a.one")])  # count 2
    gd.record([_gap("b.two")])  # count 1
    assert gd.mark_resolved(["a.one"]) == 1
    top = gd.top()
    caps = [r["capability"] for r in top]
    assert caps.index("b.two") < caps.index("a.one")  # 미해결 우선(카운트가 낮아도)
    assert next(r for r in top if r["capability"] == "a.one")["resolved"] is True


def test_hot_gating_by_caps_source(tmp_path: Any) -> None:
    eng = _engine(tmp_path)
    gd = GapDemand(eng)
    gd.record([_gap("h.heur")], caps_source="heuristic")
    gd.record([_gap("z.zero")], caps_source="zeroshot")
    # 기본(require_trusted): heuristic(=TASK 3 전 거짓 gap) 은 노출 안 함, zeroshot 만
    assert gd.hot_capabilities() == {"z.zero"}
    assert gd.hot_capabilities(require_trusted=False) == {"h.heur", "z.zero"}


def test_false_gaps_reeval(tmp_path: Any) -> None:
    eng = _engine(tmp_path)
    gd = GapDemand(eng)
    gd.record([_gap("prov.ided")])
    gd.record([_gap("not.prov")])
    fg = gd.false_gaps(["prov.ided"])
    assert [g["capability"] for g in fg] == ["prov.ided"]
    assert fg[0]["already_resolved"] is False


# ── 원본 커버리지 복원(DB 전환 전 test_gap_demand 에 있던 것) ──


def test_gap_demand_accepts_objects(tmp_path: Any) -> None:
    """dict 뿐 아니라 CapabilityGap 객체도 기록할 수 있어야 한다(_parse getattr 경로)."""
    gd = GapDemand(_engine(tmp_path))
    gd.record([CapabilityGap(capability="data.relational", reason="x", suggested_type="mcp")])
    assert gd.top(1)[0]["capability"] == "data.relational"


class _FakeRec:
    """gap 하나를 내는 fake 추천기 — _tool_search 주석 경로 검증(네트워크 없음)."""

    def recommend(self, query: str, top_k: int = 5) -> Any:
        class R:
            recommendations: list[Any] = []
            gaps = [CapabilityGap(capability="media.video", reason="없음", suggested_type="mcp")]
            requirements = ["media.video"]

        return R()


def test_tool_search_marks_hot_gaps() -> None:
    """_tool_search 는 hot_capabilities 로 넘어온 gap 에 별표를 단다(GapDemand 무관, set 직접 주입)."""
    text, _events = _tool_search(_FakeRec(), "영상 편집", hot_capabilities={"media.video"})
    assert "★자주 요청됨" in text
    text2, _ = _tool_search(_FakeRec(), "영상 편집", hot_capabilities=set())
    assert "★자주 요청됨" not in text2
