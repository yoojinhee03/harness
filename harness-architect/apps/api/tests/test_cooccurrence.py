"""컴포넌트 공출현 집계 테스트 — 하드닝 TASK 5e."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from harness_api.cooccurrence import CooccurrenceStore, _pairs
from harness_api.db import component_cooccurrence as cc_table
from harness_api.db import make_engine

_AGG = Path(__file__).resolve().parents[1] / "scripts" / "aggregate_cooccurrence.py"


def _engine(tmp_path: Any) -> Any:
    return make_engine(f"sqlite:///{tmp_path}/t.db")


def test_pairs_normalized_unique() -> None:
    # 정렬·중복제거 후 a<b 쌍
    assert _pairs(["b", "a", "a", "c"]) == [("a", "b"), ("a", "c"), ("b", "c")]
    assert _pairs(["only"]) == []  # 1개 이하면 쌍 없음


def test_record_and_top(tmp_path: Any) -> None:
    st = CooccurrenceStore(_engine(tmp_path))
    assert st.record(["github-mcp", "pr-review-skill"]) == 1  # 쌍 1개
    top = st.top()
    assert top and top[0]["pair"] == ["github-mcp", "pr-review-skill"] and top[0]["count"] == 1


def test_atomic_increment_across_instances(tmp_path: Any) -> None:
    eng = _engine(tmp_path)
    for _ in range(3):
        CooccurrenceStore(eng).record(["a", "b", "c"])  # 매번 쌍 3개(ab, ac, bc)
    top = {tuple(r["pair"]): r["count"] for r in CooccurrenceStore(eng).top()}
    assert top[("a", "b")] == 3 and top[("a", "c")] == 3 and top[("b", "c")] == 3


def test_nonblocking_on_db_failure(tmp_path: Any) -> None:
    eng = _engine(tmp_path)
    st = CooccurrenceStore(eng)
    cc_table.drop(eng)  # 테이블 제거 → 실패해도 예외 없이 삼킨다(비차단)
    assert st.record(["a", "b"]) == 0
    assert st.top() == []


def test_aggregate_parse_cooccur_lines() -> None:
    mod_spec = importlib.util.spec_from_file_location("agg_cooccur", _AGG)
    assert mod_spec and mod_spec.loader
    mod = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(mod)
    lines = [
        '2026-08-19 12:00 INFO COOCCUR_SIGNAL {"components": ["a", "b"], "source": "verify"}',
        "무관한 라인",
        'COOCCUR_SIGNAL {"components": ["x"]}',  # 1개 → 무시
    ]
    assert mod.parse_cooccur_lines(lines) == [["a", "b"]]
