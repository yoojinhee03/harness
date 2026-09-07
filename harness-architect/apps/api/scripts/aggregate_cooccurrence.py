"""공출현 로그 집계 — verify --record 의 COOCCUR_SIGNAL 을 durable 테이블로 적재(하드닝 TASK 5e).

verify `--record` 는 검증한 하네스마다 `COOCCUR_SIGNAL {"components":[...]}` 한 줄을 stderr 로 낸다.
이 스크립트가 그 로그를 읽어 `component_cooccurrence` 테이블에 쌍 빈도를 누적한다(협업 필터링 신호).

사용(앱 env — DATABASE_URL 이 앱과 동일 DB 여야 한다):
    harness verify repo --record 2>signals.log
    python apps/api/scripts/aggregate_cooccurrence.py signals.log        # 적재
    python apps/api/scripts/aggregate_cooccurrence.py --top 20 signals.log
    cat signals.log | python apps/api/scripts/aggregate_cooccurrence.py  # stdin
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

from harness_api.cooccurrence import CooccurrenceStore
from harness_api.db import make_engine, resolve_database_url
from harness_api.store import resolve_store_dir

MARKER = "COOCCUR_SIGNAL"


def parse_cooccur_lines(lines: Iterable[str], marker: str = MARKER) -> list[list[str]]:
    """`… COOCCUR_SIGNAL {json} …` 라인에서 components 목록(2개 이상)을 추출한다(마커 뒤 첫 '{')."""
    out: list[list[str]] = []
    needle = marker + " "
    for line in lines:
        i = line.find(needle)
        if i < 0:
            continue
        brace = line.find("{", i)
        if brace < 0:
            continue
        try:
            obj = json.loads(line[brace:])
        except ValueError:
            continue
        comps = obj.get("components") if isinstance(obj, dict) else None
        if isinstance(comps, list) and len(comps) >= 2:
            out.append([str(c) for c in comps])
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="COOCCUR_SIGNAL → component_cooccurrence 적재(TASK 5e)")
    p.add_argument("logs", nargs="*", help="로그 파일 경로(미지정 시 stdin)")
    p.add_argument("--top", type=int, default=0, help="적재 후 상위 N 쌍 출력")
    args = p.parse_args(argv)

    lines: list[str] = []
    if args.logs:
        for path in args.logs:
            lines += Path(path).read_text(encoding="utf-8").splitlines()
    else:
        lines = sys.stdin.read().splitlines()

    sets = parse_cooccur_lines(lines)
    store = CooccurrenceStore(make_engine(resolve_database_url(resolve_store_dir())))
    pairs = sum(store.record(s) for s in sets)
    print(f"✓ 하네스 {len(sets)}개 · 쌍 {pairs}개 적재", file=sys.stderr)
    for r in store.top(args.top) if args.top else []:
        print(f"{r['count']:5d}  {r['pair'][0]} + {r['pair'][1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
