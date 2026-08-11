"""배포 스냅샷 drift 검사 — 패키지 내부 사본이 소스(harness-catalog/components)와 일치해야 한다.

불일치 시 실패한다. `python packages/catalog/scripts/sync_catalog_snapshot.py` 로 다시 맞춘다.
"""

from __future__ import annotations

from pathlib import Path

PKG = Path(__file__).resolve().parents[1]  # packages/catalog
SRC = PKG.parents[2] / "harness-catalog" / "components"
SNAP = PKG / "src" / "harness_catalog" / "catalog-data" / "components"


def test_snapshot_matches_source() -> None:
    src = {p.name: p.read_text(encoding="utf-8") for p in SRC.glob("*.yaml")}
    snap = {p.name: p.read_text(encoding="utf-8") for p in SNAP.glob("*.yaml")}
    assert src, f"소스 카탈로그가 비어있음: {SRC}"
    assert snap == src, (
        "배포 스냅샷이 소스와 다릅니다 — "
        "`python packages/catalog/scripts/sync_catalog_snapshot.py` 를 실행하세요."
    )
