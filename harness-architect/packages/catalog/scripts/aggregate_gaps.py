"""Gap 신호 집계 — "자주 요청되나 카탈로그에 없는 능력"을 실사용 로그에서 뽑는다(작업 3).

recommender 는 요구 능력을 카탈로그가 못 채울 때마다 한 줄씩 `GAP_SIGNAL {json}` 로그를 남긴다
(`harness_catalog.recommender._log_gaps`). 이 스크립트는 그 로그를 집계해 **다음에 무엇을 시딩할지**
의 우선순위 목록을 만든다 — 카탈로그 성장을 추측이 아니라 수요 데이터로 굴린다(콜드스타트 큐).

입력: 로그 파일 경로들(인자) 또는 stdin. 라인 어디에 있든 `GAP_SIGNAL ` 마커 뒤의 JSON 을 파싱한다
(로그 프리픽스·타임스탬프 무관). 출력: 빈도 내림차순 표(count·capability·suggested_type·facet)와,
`--json` 시 기계가 읽을 배열.

사용:
    python packages/catalog/scripts/aggregate_gaps.py app.log another.log
    journalctl -u harness-api | python packages/catalog/scripts/aggregate_gaps.py
    python packages/catalog/scripts/aggregate_gaps.py --top 20 --json app.log
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from typing import Any

DEFAULT_MARKER = "GAP_SIGNAL"


def parse_gap_lines(lines: Iterable[str], marker: str = DEFAULT_MARKER) -> list[dict[str, Any]]:
    """`… {marker} {json} …` 형태 라인에서 gap 레코드를 추출한다(마커 뒤 첫 '{' 부터 파싱)."""
    records: list[dict[str, Any]] = []
    needle = marker + " "
    for line in lines:
        idx = line.find(needle)
        if idx == -1:
            continue
        brace = line.find("{", idx)
        if brace == -1:
            continue
        try:
            obj = json.loads(line[brace:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("capability"):
            records.append(obj)
    return records


def aggregate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """capability 별 빈도 집계 → 내림차순(동률은 capability 사전순). suggested_type/facet 은 최빈값."""
    counts: Counter[str] = Counter(r["capability"] for r in records)
    type_by_cap: dict[str, Counter[str]] = {}
    facet_by_cap: dict[str, Counter[str]] = {}
    for r in records:
        cap = r["capability"]
        type_by_cap.setdefault(cap, Counter())[str(r.get("suggested_type") or "?")] += 1
        facet_by_cap.setdefault(cap, Counter())[str(r.get("facet") or "?")] += 1
    out: list[dict[str, Any]] = []
    for cap, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        out.append(
            {
                "capability": cap,
                "count": count,
                "suggested_type": type_by_cap[cap].most_common(1)[0][0],
                "facet": facet_by_cap[cap].most_common(1)[0][0],
            }
        )
    return out


def _read_inputs(paths: list[str]) -> Iterable[str]:
    if not paths:
        yield from sys.stdin
        return
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as fh:
            yield from fh


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="gap 신호 로그를 집계해 시딩 우선순위를 만든다.")
    ap.add_argument("paths", nargs="*", help="로그 파일 경로(없으면 stdin)")
    ap.add_argument("--marker", default=DEFAULT_MARKER, help=f"gap 로그 마커(기본: {DEFAULT_MARKER})")
    ap.add_argument("--top", type=int, default=0, help="상위 N개만(0=전부)")
    ap.add_argument("--json", action="store_true", help="JSON 배열로 출력")
    args = ap.parse_args(argv)

    ranked = aggregate(parse_gap_lines(_read_inputs(args.paths), args.marker))
    if args.top > 0:
        ranked = ranked[: args.top]

    if args.json:
        json.dump(ranked, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    if not ranked:
        print("gap 신호 없음 (로그에 GAP_SIGNAL 라인이 없거나 마커 불일치).")
        return 0
    total = sum(r["count"] for r in ranked)
    print(f"# 자주 요청되나 카탈로그에 없는 능력 — 시딩 우선순위 (총 {total}건, {len(ranked)}종)")
    print(f"{'count':>6}  {'capability':<28} {'→ type':<9} facet")
    print(f"{'-' * 6}  {'-' * 28} {'-' * 9} {'-' * 8}")
    for r in ranked:
        print(f"{r['count']:>6}  {r['capability']:<28} {r['suggested_type']:<9} {r['facet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
