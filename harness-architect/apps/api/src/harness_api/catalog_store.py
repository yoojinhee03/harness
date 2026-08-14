"""DB 백엔드 카탈로그 — 느린 harvest 를 DB 에 적재하고, 서빙은 DB 만 읽는다.

라이브 소스(공식 MCP 레지스트리·플러그인 마켓플레이스)는 **harvest 시점에만** 네트워크로 가져온다.
결과 `Component` 를 `catalog_components` 에 origin 별로 원자적 교체 저장(`replace`)한다. 서빙
레지스트리는 `DbCatalogSource` 로 DB 를 읽어 즉시 응답한다 — 요청/워밍 경로에서 네트워크·프로세스
캐시 의존을 없앤다(레플리카 공유·재시작 생존). harvest 와 서빙이 DB 로 분리된다.

`sync_catalog` 는 API 의 백그라운드 주기 태스크(또는 CLI)가 호출한다.
"""

from __future__ import annotations

import logging
from datetime import datetime

from harness_catalog import Fetcher, Settings, build_live_sources, load_settings
from harness_resolver import Component
from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Engine

from .db import catalog_components, catalog_sync_state
from .store import now_iso

log = logging.getLogger("harness_api.catalog_store")


class CatalogStore:
    """`catalog_components` 테이블 접근. origin 단위로 원자적 교체(삭제 후 삽입)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def replace(self, origin: str, components: list[Component]) -> int:
        """origin 의 모든 행을 새 집합으로 교체(한 트랜잭션). 반환: 삽입 개수. 삭제분도 자연 반영."""
        ts = now_iso()
        rows = [
            {
                "origin": origin,
                "id": c.id,
                "type": c.type,
                "name": c.name,
                "version": c.version,
                "data": c.model_dump_json(),
                "updated_at": ts,
            }
            for c in components
        ]
        with self._engine.begin() as conn:
            conn.execute(delete(catalog_components).where(catalog_components.c.origin == origin))
            if rows:
                conn.execute(insert(catalog_components), rows)
        return len(rows)

    def all(self) -> list[Component]:
        with self._engine.connect() as conn:
            result = conn.execute(select(catalog_components.c.data))
            return [Component.model_validate_json(row[0]) for row in result]

    def get(self, component_id: str, version: str | None = None) -> Component | None:
        with self._engine.connect() as conn:
            stmt = select(catalog_components.c.data).where(catalog_components.c.id == component_id)
            row = conn.execute(stmt).first()
        if row is None:
            return None
        comp = Component.model_validate_json(row[0])
        if version is not None and comp.version != version:
            return None
        return comp

    def origins_for(self, ids: list[str]) -> dict[str, str]:
        """주어진 id 들의 origin(registry|marketplace) 매핑. 프로비넌스(신뢰 등급) 판정용.

        페이지 단위(수십 개)로만 조회해 전체 스캔을 피한다. 로컬 시드는 DB 에 없어 여기 안 나온다.
        """
        if not ids:
            return {}
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(catalog_components.c.id, catalog_components.c.origin).where(
                    catalog_components.c.id.in_(ids)
                )
            ).all()
        return {r[0]: r[1] for r in rows}

    def count(self) -> int:
        with self._engine.connect() as conn:
            n = conn.execute(select(func.count()).select_from(catalog_components)).scalar()
        return int(n or 0)

    def revision(self) -> str:
        """값싼 변경 시그니처 — (행 수, 최신 updated_at). sync 가 내용을 바꾸면 값이 바뀐다."""
        with self._engine.connect() as conn:
            row = conn.execute(
                select(func.count(), func.max(catalog_components.c.updated_at)).select_from(
                    catalog_components
                )
            ).first()
        return f"{row[0]}:{row[1]}" if row else "0:"

    def last_synced(self) -> str | None:
        """가장 최근 적재 시각(ISO). 없으면 None. 다음 sync 시점 판단·다중 레플리카 완화용."""
        with self._engine.connect() as conn:
            return conn.execute(select(func.max(catalog_components.c.updated_at))).scalar()

    # ── 증분 upsert / delete (하이브리드 sync) ──
    def upsert(self, origin: str, components: list[Component]) -> int:
        """origin 의 해당 id 행만 갈아끼운다(전체 교체 아님). 반환: upsert 개수."""
        if not components:
            return 0
        ts = now_iso()
        ids = [c.id for c in components]
        rows = [
            {
                "origin": origin,
                "id": c.id,
                "type": c.type,
                "name": c.name,
                "version": c.version,
                "data": c.model_dump_json(),
                "updated_at": ts,
            }
            for c in components
        ]
        with self._engine.begin() as conn:
            conn.execute(
                delete(catalog_components).where(
                    catalog_components.c.origin == origin, catalog_components.c.id.in_(ids)
                )
            )
            conn.execute(insert(catalog_components), rows)
        return len(rows)

    def delete(self, origin: str, ids: list[str]) -> int:
        """origin 의 주어진 id 행 삭제(상류에서 제거·폐기된 것). 반환: 삭제 개수."""
        ids = list(ids)
        if not ids:
            return 0
        with self._engine.begin() as conn:
            r = conn.execute(
                delete(catalog_components).where(
                    catalog_components.c.origin == origin, catalog_components.c.id.in_(ids)
                )
            )
        return r.rowcount or 0

    # ── sync 상태(워터마크·시각) ──
    def get_state(self, origin: str) -> tuple[str | None, str | None]:
        """(watermark, last_full_at). 없으면 (None, None)."""
        with self._engine.connect() as conn:
            row = conn.execute(
                select(catalog_sync_state.c.watermark, catalog_sync_state.c.last_full_at).where(
                    catalog_sync_state.c.origin == origin
                )
            ).first()
        return (row[0], row[1]) if row else (None, None)

    def set_state(
        self, origin: str, *, watermark: str | None, last_full_at: str | None, last_sync_at: str
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(catalog_sync_state).where(catalog_sync_state.c.origin == origin))
            conn.execute(
                insert(catalog_sync_state).values(
                    origin=origin,
                    watermark=watermark,
                    last_full_at=last_full_at,
                    last_sync_at=last_sync_at,
                )
            )

    def due_for_sync(self, interval_seconds: float) -> bool:
        """마지막 sync(모든 origin 중 최신) 이후 interval 이 지났으면 True. 상태 없으면 True(첫 sync)."""
        with self._engine.connect() as conn:
            last = conn.execute(select(func.max(catalog_sync_state.c.last_sync_at))).scalar()
        return seconds_since(last) >= interval_seconds


class DbCatalogSource:
    """서빙용 소스 — DB(CatalogStore)를 읽는다. 네트워크 없음. revision 이 바뀔 때만 재조회(캐시).

    `Registry`(FederatedRegistry)에 `LiveSource` 로 꽂힌다. 매 요청마다 값싼 revision 질의 1회 +
    변경 시에만 전체 재로드 → 서빙은 사실상 즉시. sync 가 DB 를 갱신하면 다음 접근에 자동 반영.
    """

    origin = "db"

    def __init__(self, store: CatalogStore) -> None:
        self._store = store
        self._cache: list[Component] = []
        self._rev: str | None = None

    def components(self) -> list[Component]:
        rev = self._store.revision()
        if rev != self._rev:
            self._cache = self._store.all()
            self._rev = rev
        return self._cache


def sync_catalog(
    engine: Engine, settings: Settings | None = None, fetcher: Fetcher | None = None
) -> dict[str, dict[str, object]]:
    """하이브리드 harvest → DB. 반환: {origin: {mode, upsert, delete}}.

    origin 별로:
    - **증분(delta)**: 소스가 지원하고(supports_delta) 워터마크가 있으며 full 주기가 안 됐으면
      `updated_since=<watermark>` 로 바뀐 것만 upsert(+상류에서 삭제된 건 delete). 값싸고 빠름.
    - **전체(full)**: 최초·워터마크 없음·full 주기 도래 시 전체 재수집 후 origin 통째 교체(드리프트 정리).
    마켓플레이스는 증분 API 가 없어 항상 full. 한 소스 실패는 격리(기존 DB 유지, 스킵).
    """
    cfg = settings or load_settings()
    store = CatalogStore(engine)
    result: dict[str, dict[str, object]] = {}
    for source in build_live_sources(cfg, fetcher):
        origin = getattr(source, "origin", "live")
        watermark, last_full = store.get_state(origin)
        full_due = last_full is None or seconds_since(last_full) >= cfg.catalog_full_interval
        use_delta = bool(getattr(source, "supports_delta", False)) and bool(watermark) and not full_due
        try:
            if use_delta:
                upserts, deletes, wm = source.fetch_delta(watermark)  # type: ignore[attr-defined]
                u = store.upsert(origin, upserts)
                d = store.delete(origin, deletes)
                store.set_state(origin, watermark=wm or watermark, last_full_at=last_full, last_sync_at=now_iso())
                result[origin] = {"mode": "delta", "upsert": u, "delete": d}
                log.info("카탈로그 sync(delta) origin=%s +%d/-%d", origin, u, d)
            else:
                components = source.components()  # 전체 재수집(+enrich)
                n = store.replace(origin, components)
                wm = getattr(source, "last_watermark", None)
                now = now_iso()
                store.set_state(origin, watermark=wm, last_full_at=now, last_sync_at=now)
                result[origin] = {"mode": "full", "upsert": n, "delete": 0}
                log.info("카탈로그 sync(full) origin=%s → %d개", origin, n)
        except Exception as exc:  # noqa: BLE001 — 한 소스 실패가 전체를 막지 않게
            log.warning("harvest 실패(origin=%s) — 기존 DB 유지, 스킵: %s", origin, exc)
            continue
    return result


def seconds_since(iso: str | None) -> float:
    """ISO 시각 이후 경과 초. None/파싱실패는 무한대(즉시 sync 대상)."""
    if not iso:
        return float("inf")
    try:
        return (datetime.now(datetime.fromisoformat(iso).tzinfo) - datetime.fromisoformat(iso)).total_seconds()
    except ValueError:
        return float("inf")
