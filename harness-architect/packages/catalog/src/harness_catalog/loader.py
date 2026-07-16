"""카탈로그 로더 — YAML 자산을 읽어 Component 로 파싱하고 레지스트리를 만든다.

카탈로그 데이터는 `harness-architect` 와 같은 레포에 나란히 있는 `harness-catalog/components`
폴더다(별도 레포·submodule 아님). 탐색 순서: `CATALOG_DIR` 환경변수 → 옆 폴더
`../harness-catalog/components` → (있으면) `catalog-data/components`.

CLI:
    python -m harness_catalog.loader --validate [DIR]   # 스키마 검증
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from harness_resolver import Component, InMemoryRegistry


def resolve_catalog_dir(explicit: str | None = None) -> Path:
    """카탈로그 컴포넌트 디렉터리를 찾는다."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("CATALOG_DIR")
    if env:
        return Path(env).expanduser().resolve()

    # cwd 와 이 파일 위치 양쪽에서 위로 올라가며 사이드바이사이드 폴더를 찾는다.
    roots = [Path.cwd(), Path(__file__).resolve()]
    for start in roots:
        for ancestor in [start, *start.parents]:
            for candidate in (
                ancestor / "harness-catalog" / "components",
                ancestor / "catalog-data" / "components",
                ancestor.parent / "harness-catalog" / "components",
            ):
                if candidate.is_dir():
                    return candidate.resolve()
    raise FileNotFoundError(
        "카탈로그 디렉터리를 찾을 수 없습니다. CATALOG_DIR 를 설정하거나 "
        "harness-catalog/components 를 옆에 두세요."
    )


def load_components(catalog_dir: str | Path | None = None) -> list[Component]:
    """디렉터리의 *.yaml 을 모두 로드해 Component 리스트로 반환."""
    directory = catalog_dir if isinstance(catalog_dir, Path) else resolve_catalog_dir(catalog_dir)
    components: list[Component] = []
    for path in sorted(Path(directory).glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            continue
        components.append(Component.model_validate(raw))
    return components


def build_registry(catalog_dir: str | Path | None = None) -> InMemoryRegistry:
    return InMemoryRegistry(load_components(catalog_dir))


def _validate(directory: str | None) -> int:
    """각 YAML 이 Component 스키마를 통과하는지 검사. 실패 시 비정상 종료."""
    try:
        target = resolve_catalog_dir(directory)
    except FileNotFoundError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    errors = 0
    paths = sorted(Path(target).glob("*.yaml"))
    for path in paths:
        try:
            Component.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            print(f"✓ {path.name}")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"✗ {path.name}: {exc}", file=sys.stderr)
    print(f"\n{len(paths)}개 중 {len(paths) - errors}개 통과 ({target})")
    return 1 if errors else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--validate":
        raise SystemExit(_validate(args[1] if len(args) > 1 else None))
    reg = build_registry(args[0] if args else None)
    print(f"{len(reg.all())}개 컴포넌트 로드됨: {[c.id for c in reg.all()]}")
