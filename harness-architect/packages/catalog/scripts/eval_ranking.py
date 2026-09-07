"""랭킹 eval 러너 — 골든셋으로 추천 품질을 측정한다(백로그 #2 의 선행 게이트).

`ranking.py` 를 건드리기 전후로 이걸 돌려 수치를 비교한다. 회귀 판정의 자동 펜스는
`tests/test_rank_eval.py` 가 하한선으로 걸고, 이 스크립트는 사람이 델타를 읽는 용도다.

사용:
    python packages/catalog/scripts/eval_ranking.py
    python packages/catalog/scripts/eval_ranking.py -v            # 반환 목록·순위까지
    python packages/catalog/scripts/eval_ranking.py --json        # 기계 판독(전후 diff 용)
    python packages/catalog/scripts/eval_ranking.py --cases path/to/golden.yaml
    CATALOG_DIR=... python packages/catalog/scripts/eval_ranking.py   # 대규모 카탈로그에 대고
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _pkg in ("catalog", "resolver"):
    _src = _ROOT / "packages" / _pkg / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from harness_catalog.loader import build_registry  # noqa: E402
from harness_catalog.rank_eval import (  # noqa: E402
    build_eval_recommender,
    evaluate,
    format_report,
    load_cases,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="랭킹 골든셋 eval — 추천 품질 측정")
    p.add_argument("--cases", default=None, help="골든셋 YAML (기본: harness-catalog/evals/ranking-golden.yaml)")
    p.add_argument("--catalog", default=None, help="카탈로그 컴포넌트 디렉터리 (기본: 자동 탐색)")
    p.add_argument("-v", "--verbose", action="store_true", help="케이스별 반환 목록·순위 출력")
    p.add_argument("--json", action="store_true", help="JSON 으로 출력(전후 비교·CI 수집)")
    args = p.parse_args(argv)

    golden = load_cases(args.cases)
    registry = build_registry(args.catalog)
    report = evaluate(build_eval_recommender(registry), golden)

    if args.json:
        payload = {
            "name": report.name,
            "catalog_size": len(registry.all()),
            "pass_rate": report.pass_rate,
            "mean_recall": report.mean_recall,
            "mean_rr": report.mean_rr,
            "order_ok": report.order_ok,
            "order_total": report.order_total,
            "cases": [c.model_dump() for c in report.cases],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"카탈로그 {len(registry.all())}개")
        print(format_report(report, verbose=args.verbose))

    # 하드 판정이 하나라도 깨지면 비정상 종료 — CI 에서 그대로 쓸 수 있게.
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
