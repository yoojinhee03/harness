"""제로샷 caps 태깅 보정 — 스냅샷에서 커버리지·정밀도를 측정해 임계값을 정한다(하드닝 TASK 3).

휴리스틱이 비운 컴포넌트에 zeroshot_classifier 를 임계값별로 돌려 (1) 채워지는 비율(커버리지)과
(2) 샘플 육안 정밀도를 낸다. "거짓 gap 을 줄이려다 거짓 충족을 만들면 더 나쁘다" — 정밀도가 낮으면
임계값을 올리거나 활성화를 보류한다.

사용:
    python packages/catalog/scripts/eval_zeroshot.py --from-snapshot live.json
    python packages/catalog/scripts/eval_zeroshot.py --from-snapshot live.json --thresholds 0.3,0.35,0.4 --samples 20
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

from harness_catalog.caps_zeroshot import zeroshot_classifier  # noqa: E402
from harness_catalog.vocabulary import extract_capabilities_heuristic  # noqa: E402
from harness_resolver import Component  # noqa: E402


def _text(c: Component) -> str:
    return " ".join([c.name, c.summary, c.description, *c.keywords]).strip()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="제로샷 caps 임계값 보정(TASK 3)")
    p.add_argument("--from-snapshot", required=True, help="measure_caps --save-snapshot 산출 JSON")
    p.add_argument("--thresholds", default="0.25,0.30,0.35,0.40")
    p.add_argument("--samples", type=int, default=15)
    args = p.parse_args(argv)

    doc = json.loads(Path(args.from_snapshot).read_text(encoding="utf-8"))
    comps = [Component.model_validate(d) for ds in doc.values() for d in ds]
    empty = [c for c in comps if not extract_capabilities_heuristic(_text(c))]
    total = len(comps)
    print(f"전체 {total} · 휴리스틱 빈 caps {len(empty)} ({len(empty) / total:.1%})")

    thresholds = [float(t) for t in args.thresholds.split(",")]
    for th in thresholds:
        clf = zeroshot_classifier(threshold=th, top_n=2)
        result = clf([(c.id, _text(c)) for c in empty]) or {}
        filled = len(result)
        print(f"  threshold={th:.2f} → 채움 {filled}/{len(empty)} ({filled / max(1, len(empty)):.1%})")

    # 정밀도 육안 — 중간 임계값에서 샘플 덤프(설명 → 배정된 caps)
    mid = thresholds[len(thresholds) // 2]
    clf = zeroshot_classifier(threshold=mid, top_n=2)
    result = clf([(c.id, _text(c)) for c in empty]) or {}
    by_id = {c.id: c for c in empty}
    print(f"\n샘플(threshold={mid:.2f}, 최대 {args.samples}) — 육안 정밀도:")
    for cid in list(result)[: args.samples]:
        desc = (by_id[cid].summary or by_id[cid].description)[:70]
        print(f"  {cid}: {result[cid]}  ← {desc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
