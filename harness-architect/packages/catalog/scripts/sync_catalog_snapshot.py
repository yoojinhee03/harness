"""배포용 카탈로그 스냅샷 동기화 — harness-catalog/components → 패키지 내부 catalog-data.

소스 오브 트루스는 레포의 `harness-catalog/components` 다. uvx/PyPI 로 설치했을 때 loader 가
설치본 안에서 카탈로그를 자동 탐색할 수 있도록, 이 스크립트가 패키지 내부
`src/harness_catalog/catalog-data/components/` 에 빌드용 사본을 만든다. 둘의 drift 는
`tests/test_catalog_snapshot.py` 가 잡는다. 카탈로그를 바꾸면 이 스크립트를 다시 실행한다.

    python packages/catalog/scripts/sync_catalog_snapshot.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]  # packages/catalog
SRC = PKG.parents[2] / "harness-catalog" / "components"  # <repo>/harness-catalog/components
DST = PKG / "src" / "harness_catalog" / "catalog-data" / "components"


def main() -> int:
    if not SRC.is_dir():
        print(f"✗ 소스 카탈로그를 찾을 수 없음: {SRC}")
        return 1
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True, exist_ok=True)
    count = 0
    for f in sorted(SRC.glob("*.yaml")):
        shutil.copy2(f, DST / f.name)
        count += 1
    print(f"✓ {count}개 스냅샷 → {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
