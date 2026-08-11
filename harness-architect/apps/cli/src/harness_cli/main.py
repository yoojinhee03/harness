"""harness CLI — 설계: 진행 플랜 Phase 5. 웹 없이 터미널에서 완결.

    harness resolve <harness.yaml>                    검증(진단)
    harness eject   <harness.yaml> --to claude-code   네이티브 포맷으로 방출
        [--out DIR] [--dry-run] [--catalog DIR]

카탈로그는 기본으로 옆 폴더(../harness-catalog/components)를 자동 탐색한다. 다른 위치면
--catalog 또는 CATALOG_DIR 로 지정한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from harness_catalog import build_registry
from harness_resolver import HarnessConfig, InMemoryRegistry, Registry, ResolveResult, resolve
from harness_runtime import available_targets, emit


def _load_config(path: str) -> HarnessConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return HarnessConfig.model_validate(data)


def _registry(catalog: str | None) -> Registry:
    try:
        return build_registry(catalog)
    except FileNotFoundError as exc:
        print(f"경고: 카탈로그를 찾지 못함 — 빈 레지스트리로 진행 ({exc})", file=sys.stderr)
        return InMemoryRegistry([])


def _print_diagnostics(result: ResolveResult) -> None:
    d = result.diagnostics
    for item in d.errors:
        print(f"  ✗ [error] {item.code}: {item.message}", file=sys.stderr)
    for item in d.gaps:
        print(f"  • [gap] {item.capability} (요구: {item.component_id})", file=sys.stderr)
    for item in d.warnings:
        print(f"  ! [warn] {item.code}: {item.message}", file=sys.stderr)


def cmd_resolve(args: argparse.Namespace) -> int:
    result = resolve(_load_config(args.config), _registry(args.catalog))
    _print_diagnostics(result)
    if result.ok and result.resolved is not None:
        r = result.resolved
        print(
            f"✓ ok — 컴포넌트 {len(r.components)}개 · "
            f"컨텍스트 {r.cost.context_tokens}토큰 · 도구 {r.cost.added_tools}"
        )
        if r.prompt is not None:
            print(f"  프롬프트: {len(r.prompt.segments)}조각 · {r.prompt.hash}")
        return 0
    print("✗ resolve 실패(위 에러 참조)", file=sys.stderr)
    return 1


def cmd_eject(args: argparse.Namespace) -> int:
    result = resolve(_load_config(args.config), _registry(args.catalog))
    if not result.ok or result.resolved is None:
        _print_diagnostics(result)
        print("✗ resolve 실패 — eject 중단", file=sys.stderr)
        return 1

    tree = emit(result.resolved, args.to)

    if args.dry_run:
        print(f"[dry-run] {args.to} — 생성될 파일 {len(tree)}개:")
        for path in sorted(tree):
            print(f"\n===== {path} =====")
            print(tree[path].rstrip("\n"))
        return 0

    out = Path(args.out)
    for path in sorted(tree):
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(tree[path], encoding="utf-8")
        print(f"  wrote {target} ({len(tree[path])} bytes)")
    print(f"✓ {args.to} → {out}/ ({len(tree)}개 파일)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="harness.yaml 을 resolve/eject 한다.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_resolve = sub.add_parser("resolve", help="harness.yaml 을 검증(진단)한다.")
    p_resolve.add_argument("config", help="harness.yaml 경로")
    p_resolve.add_argument("--catalog", default=None, help="카탈로그 components 디렉터리(기본: 자동 탐색)")
    p_resolve.set_defaults(func=cmd_resolve)

    p_eject = sub.add_parser("eject", help="ResolvedHarness 를 런타임 네이티브 포맷으로 방출한다.")
    p_eject.add_argument("config", help="harness.yaml 경로")
    p_eject.add_argument("--to", required=True, choices=available_targets(), help="타깃 런타임")
    p_eject.add_argument("--out", default=".", help="출력 디렉터리(기본: 현재 폴더)")
    p_eject.add_argument("--dry-run", action="store_true", help="디스크에 쓰지 않고 생성될 내용만 출력")
    p_eject.add_argument("--catalog", default=None, help="카탈로그 components 디렉터리(기본: 자동 탐색)")
    p_eject.set_defaults(func=cmd_eject)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
