"""Gap 재평가 — 과거 gap 기록 중 지금은 공급 가능한(=거짓) 것을 표시(TASK 2 인터페이스, TASK 3 후 실행).

빈 caps 컴포넌트가 능력 매칭에서 이탈해, 과거엔 실제로 제공 가능한 능력도 gap 으로 기록됐다(오탐).
TASK 3 로 caps 커버리지가 오른 뒤 이 스크립트로 과거 기록을 **현재 카탈로그 상태**에 재판정해 정화한다.

공급 가능 능력 집합 = 로컬 시드 + DB 하베스트의 모든 컴포넌트가 provides/capability_tags 로 내놓는 능력.
`false_gaps` 는 리포트만(변경 없음), `--apply` 는 해당 미해결 gap 에 resolved_at 을 채운다.

사용(앱 env 에서 — DATABASE_URL 이 앱과 동일해야 같은 DB 를 본다):
    python apps/api/scripts/reeval_gaps.py            # 리포트만(거짓/해결가능 gap 목록)
    python apps/api/scripts/reeval_gaps.py --apply    # resolved_at 채워 정화
"""

from __future__ import annotations

import argparse

from harness_api.db import make_engine, resolve_database_url
from harness_api.gap_demand import GapDemand
from harness_api.store import resolve_store_dir
from harness_catalog import build_registry, resolve_catalog_dir

from harness_api.catalog_store import CatalogStore  # isort: skip (로컬 패키지 순서)


def provided_capabilities(engine: object) -> set[str]:
    """로컬 시드 + DB 하베스트가 공급하는 능력 전체(provides ∪ capability_tags)."""
    provided: set[str] = set()
    try:
        for c in build_registry(resolve_catalog_dir()).all():
            provided |= set(c.provides or []) | set(c.capability_tags or [])
    except FileNotFoundError:
        pass  # 로컬 카탈로그 없으면 DB 만
    for c in CatalogStore(engine).all():  # type: ignore[arg-type]
        provided |= set(c.provides or []) | set(c.capability_tags or [])
    return provided


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="gap 수요 재평가/정화 (TASK 2 인터페이스)")
    p.add_argument("--apply", action="store_true", help="거짓 gap 에 resolved_at 을 채운다(정화)")
    args = p.parse_args(argv)

    engine = make_engine(resolve_database_url(resolve_store_dir()))
    provided = provided_capabilities(engine)
    gd = GapDemand(engine)

    stale = [g for g in gd.false_gaps(provided) if not g["already_resolved"]]
    print(f"공급 가능 능력 {len(provided)}개 · 재판정 대상(미해결이나 공급됨) {len(stale)}개")
    for g in stale:
        print(f"  • {g['capability']} (count={g['count']}, caps_source={g['caps_source']})")

    if args.apply:
        n = gd.mark_resolved(provided)
        print(f"✓ resolved 표시: {n}개")
    else:
        print("(리포트만 — 정화하려면 --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
