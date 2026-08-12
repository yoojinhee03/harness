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
from harness_runtime import EvalCase, adopt_dir, available_targets, emit, run_eval


def _load_config(path: str) -> HarnessConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return HarnessConfig.model_validate(data)


def _load_cases(path: str) -> list[EvalCase]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [EvalCase.model_validate(c) for c in (raw.get("cases") or [])]


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


def cmd_eval(args: argparse.Namespace) -> int:
    result = resolve(_load_config(args.config), _registry(args.catalog))
    if not result.ok or result.resolved is None:
        _print_diagnostics(result)
        print("✗ resolve 실패 — eval 중단", file=sys.stderr)
        return 1
    cases = _load_cases(args.cases)
    if not cases:
        print(f"경고: {args.cases} 에 케이스가 없음", file=sys.stderr)
        return 1
    report = run_eval(result.resolved, cases)  # client 미주입 → env 키로 live, 없으면 dry_run 스킵
    for c in report.cases:
        if not c.scored:
            print(f"  • {c.name} — 스킵({'dry_run' if c.dry_run else '출력없음'}): {c.note}")
        else:
            n_ok = sum(ch.passed for ch in c.checks)
            mark = "✓" if c.passed else "✗"
            print(f"  {mark} {c.name} — score={c.score} ({n_ok}/{len(c.checks)} 체크 통과)")
    if report.mean_score is None:
        print("mean: — (채점된 케이스 없음 — 키 없이 dry_run. ANTHROPIC_API_KEY 설정 시 live 채점)")
    else:
        print(f"✓ mean score {report.mean_score} · 채점 {report.scored_count}/{len(report.cases)} 케이스")
    return 0


def cmd_adopt(args: argparse.Namespace) -> int:
    result = adopt_dir(args.source, _registry(args.catalog), harness_id=args.id)
    doc = result.config.model_dump(exclude_none=True, exclude_defaults=True, by_alias=True)
    print(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False).rstrip())
    for note in result.notes:
        print(f"# {note}", file=sys.stderr)
    return 0


def cmd_harvest(args: argparse.Namespace) -> int:
    from harness_catalog import ServerDescriptor, component_to_yaml, harvest, uncovered

    raw = yaml.safe_load(Path(args.descriptors).read_text(encoding="utf-8")) or {}
    items = raw.get("servers") if isinstance(raw, dict) else raw
    descriptors = [ServerDescriptor.model_validate(d) for d in (items or [])]
    components = harvest(descriptors)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for c in components:
            (out / f"{c.id}.yaml").write_text(component_to_yaml(c), encoding="utf-8")
            print(f"  wrote {out}/{c.id}.yaml (caps={c.capability_tags})")
    else:
        for c in components:
            print(f"===== {c.id}.yaml (caps={c.capability_tags}) =====")
            print(component_to_yaml(c).rstrip())
    unc = uncovered(components)
    if unc:
        print(f"# capability 미추론(어휘 확장 후보): {unc}", file=sys.stderr)
    print(f"✓ {len(components)}개 수확", file=sys.stderr)
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

    p_eval = sub.add_parser("eval", help="하네스를 eval 케이스로 실행·채점한다(경험적 검증).")
    p_eval.add_argument("config", help="harness.yaml 경로")
    p_eval.add_argument("--cases", required=True, help="eval 케이스 YAML 경로(cases: [...])")
    p_eval.add_argument("--catalog", default=None, help="카탈로그 components 디렉터리(기본: 자동 탐색)")
    p_eval.set_defaults(func=cmd_eval)

    p_adopt = sub.add_parser("adopt", help="기존 네이티브 설정(.claude/.cursor)을 harness.yaml IR 로 역흡수한다.")
    p_adopt.add_argument("source", help="네이티브 설정이 있는 디렉터리")
    p_adopt.add_argument("--id", default="adopted", help="생성할 harness metadata.id")
    p_adopt.add_argument("--catalog", default=None, help="카탈로그 components 디렉터리(기본: 자동 탐색)")
    p_adopt.set_defaults(func=cmd_adopt)

    p_harvest = sub.add_parser("harvest", help="MCP 레지스트리 서버 디스크립터 → 카탈로그 컴포넌트로 수확한다.")
    p_harvest.add_argument("descriptors", help="서버 디스크립터 JSON/YAML(servers: [...] 또는 최상위 리스트)")
    p_harvest.add_argument("--out", default=None, help="컴포넌트 YAML 을 쓸 디렉터리(미지정 시 표준출력)")
    p_harvest.set_defaults(func=cmd_harvest)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
