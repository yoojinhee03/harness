"""카탈로그 LLM 보강 — 앱 등록 키(provider+key)로 DB 카탈로그의 caps 를 채운다.

`AppSettingsStore` 에서 provider·LLM 키를 복호(앱과 같은 HARNESS_SECRET_KEY 필요)해 분류기를 만들고,
`CapabilityEnricher` 로 `catalog_components` 의 caps 를 태깅한다. 기본은 빈-캡 컴포넌트만(증분·저비용),
`--retag` 면 이미 태그가 있어도 재분류(초기 휴리스틱 오탐 정리).

dry-run 은 대상 개수만 보여주고 LLM 을 호출하지 않는다(비용 없음). `--apply` 가 실제 분류+DB 반영.
서빙(recommend)은 다음 재인덱싱 때 반영된다(LiveRecommender 가 generation 변화 감지).

사용(앱 env 에서 — 키 복호를 위해 HARNESS_SECRET_KEY/DATABASE_URL 이 앱과 동일해야 함):
    python apps/api/scripts/enrich_catalog.py                 # dry-run(대상 개수)
    python apps/api/scripts/enrich_catalog.py --apply         # 빈-캡만 보강
    python apps/api/scripts/enrich_catalog.py --retag --max 3000 --apply   # 전체 재분류
"""

from __future__ import annotations

import argparse

from harness_api.db import catalog_components, make_engine, resolve_database_url
from harness_api.llm_settings import AppSettingsStore
from harness_api.store import now_iso, resolve_store_dir
from harness_catalog import CapabilityEnricher, make_classifier
from harness_resolver import Component
from sqlalchemy import select, update


def _load(engine) -> list[tuple[str, Component]]:  # noqa: ANN001
    rows = []
    with engine.connect() as conn:
        for r in conn.execute(
            select(catalog_components.c.origin, catalog_components.c.data)
        ).mappings():
            try:
                rows.append((r["origin"], Component.model_validate_json(r["data"])))
            except Exception:  # noqa: BLE001 — 손상 행은 스킵
                continue
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="앱 등록 키로 DB 카탈로그 caps 를 LLM 보강한다.")
    ap.add_argument("--apply", action="store_true", help="실제 분류+DB 반영(미지정 시 dry-run)")
    ap.add_argument("--retag", action="store_true", help="이미 태그 있어도 재분류(오탐 정리)")
    ap.add_argument("--max", type=int, default=200, help="보강 상한(대상 컴포넌트 수, 기본 200)")
    ap.add_argument("--batch", type=int, default=40, help="배치 크기(기본 40)")
    args = ap.parse_args(argv)

    engine = make_engine(resolve_database_url(resolve_store_dir()))
    app = AppSettingsStore(engine).resolve()
    provider, key = app["provider"], app["llm_key"]
    classifier = make_classifier(provider, key)
    if classifier is None:
        print(f"✗ LLM 키 없음/복호 실패(provider={provider}). 앱에서 키 등록 + HARNESS_SECRET_KEY 확인.")
        return 2

    rows = _load(engine)
    comps = [c for _, c in rows]
    origin_by_id = {c.id: o for o, c in rows}
    before = {c.id: list(c.capability_tags) for c in comps}
    targets = comps if args.retag else [c for c in comps if not c.capability_tags]
    print(f"provider={provider} · 컴포넌트 {len(comps)} · 대상 {len(targets)}(retag={args.retag}) · 상한 {args.max}")

    if not args.apply:
        print("(dry-run — LLM 호출 없음. 반영하려면 --apply)")
        return 0

    CapabilityEnricher(
        classifier=classifier, batch_size=args.batch, max_enrich=args.max, retag=args.retag
    ).enrich(comps)

    changed = [c for c in comps if c.capability_tags != before[c.id]]
    ts = now_iso()
    with engine.begin() as conn:
        for c in changed:
            conn.execute(
                update(catalog_components)
                .where(
                    catalog_components.c.origin == origin_by_id[c.id],
                    catalog_components.c.id == c.id,
                )
                .values(data=c.model_dump_json(), updated_at=ts)
            )
    print(f"✓ {len(changed)}개 태깅 반영됨 → DB (recommend 는 다음 재인덱싱에 반영)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
