"""harness CLI — 설계: 진행 플랜 Phase 5. 웹 없이 터미널에서 완결.

    harness resolve <harness.yaml>                    검증(진단)
    harness eject   <harness.yaml> --to claude-code   네이티브 포맷으로 방출
        [--out DIR] [--dry-run] [--catalog DIR]

카탈로그는 기본으로 옆 폴더(../harness-catalog/components)를 자동 탐색한다. 다른 위치면
--catalog 또는 CATALOG_DIR 로 지정한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from harness_catalog import (
    build_registry,
    facet_for_capability,
    load_recipe,
    load_recipes,
    suggested_component_type,
)
from harness_resolver import (
    HarnessConfig,
    InMemoryRegistry,
    Policy,
    Registry,
    ResolveResult,
    policy_from_document,
    resolve,
)
from harness_runtime import (
    DEFAULT_SEVERITY,
    EvalCase,
    adopt_dir,
    apply_suggestions,
    available_targets,
    doctor,
    drop_component,
    emit,
    load_eval_file,
    load_eval_scenario,
    preview,
    read_native_tree,
    run_ablation,
    run_eval,
    verify,
    violations,
)


def _load_config(path: str) -> HarnessConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return HarnessConfig.model_validate(data)


def _cases_from_args(args: argparse.Namespace) -> list[EvalCase]:
    """`--cases <파일>` 또는 `--scenario <이름>`. 로딩은 코어(harness_runtime)가 한다(CLI/API 공용)."""
    if getattr(args, "scenario", None):
        return load_eval_scenario(args.scenario)
    if not getattr(args, "cases", None):
        raise SystemExit("--cases <파일> 또는 --scenario <이름> 중 하나가 필요합니다.")
    return load_eval_file(args.cases)


def _registry(catalog: str | None) -> Registry:
    try:
        return build_registry(catalog)
    except FileNotFoundError as exc:
        print(f"경고: 카탈로그를 찾지 못함 — 빈 레지스트리로 진행 ({exc})", file=sys.stderr)
        return InMemoryRegistry([])


def _load_governance(path: str | None) -> Policy | None:
    """`--policy <파일>` → Policy. 거버넌스 섹션이 없으면 None(정책 미지정).

    같은 `.harness/policy.yaml` 의 `severity:` 는 verify 심각도 오버라이드로 이미 쓰이고 있다
    (`_load_policy`). 한 파일에 섹션을 나눠 담으므로 severity 만 있는 기존 파일은 None 이 된다.
    """
    if not path:
        return None
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return policy_from_document(doc)


def _print_diagnostics(result: ResolveResult) -> None:
    d = result.diagnostics
    for item in d.errors:
        # 정책 위반은 규칙 이름을 함께 낸다 — "무엇을 고쳐야 하나"가 설정 오류와 다르기 때문이다.
        if item.code == "policy_violation":
            print(f"  ⛔ [policy] {item.detail.get('rule', '?')}: {item.message}", file=sys.stderr)
        else:
            print(f"  ✗ [error] {item.code}: {item.message}", file=sys.stderr)
    for item in d.gaps:
        print(f"  • [gap] {item.capability} (요구: {item.component_id})", file=sys.stderr)
    for item in d.warnings:
        print(f"  ! [warn] {item.code}: {item.message}", file=sys.stderr)


def cmd_init(args: argparse.Namespace) -> int:
    """검증된 레시피로 harness.yaml 을 만든다 — 콜드스타트("무엇부터 골라야 하나")를 없앤다."""
    if args.list or not args.recipe:
        for r in load_recipes():
            print(f"  {r.meta.name:14s} {r.meta.title} — {r.meta.description}")
            for w in r.meta.use_when:
                print(f"      · {w}")
        if not args.recipe:
            print("\n사용: harness init --recipe <이름> [-o harness.yaml]")
        return 0

    try:
        recipe = load_recipe(args.recipe)
    except KeyError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    doc = recipe.config.model_dump(exclude_none=True, exclude_defaults=True, by_alias=True)
    text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    out = Path(args.output) if args.output else None
    if out is None:
        print(text.rstrip())
        return 0
    if out.exists() and not args.force:
        print(f"✗ {out} 가 이미 있습니다(--force 로 덮어쓰기)", file=sys.stderr)
        return 1
    out.write_text(text, encoding="utf-8")
    print(f"✓ {out} 생성 — {recipe.meta.title}. 시작점이니 팀에 맞게 고쳐 쓰세요.")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    policy = _load_governance(getattr(args, "policy", None))
    result = resolve(_load_config(args.config), _registry(args.catalog), policy)
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
    # 정책 위반 하네스는 방출도 막는다 — resolve 에서만 막으면 eject 로 우회된다.
    policy = _load_governance(getattr(args, "policy", None))
    result = resolve(_load_config(args.config), _registry(args.catalog), policy)
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
    cases = _cases_from_args(args)
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


def cmd_ablate(args: argparse.Namespace) -> int:
    reg = _registry(args.catalog)
    config = _load_config(args.config)
    full = resolve(config, reg)
    ablated = resolve(drop_component(config, args.drop), reg)
    if full.resolved is None or ablated.resolved is None:
        print("✗ resolve 실패 — ablation 중단", file=sys.stderr)
        return 1
    result = run_ablation(full.resolved, ablated.resolved, _cases_from_args(args), args.drop)
    print(f"full mean={result.full.mean_score} · ablated(-{args.drop}) mean={result.ablated.mean_score}")
    d = result.delta_mean
    if d is None:
        print("delta: — (키 없어 dry_run 스킵 — ANTHROPIC_API_KEY 설정 시 실측)")
    else:
        verdict = "기여함(+)" if d > 0 else ("역효과(-)" if d < 0 else "무기여")
        print(f"✓ '{args.drop}' 기여 델타 {d:+g} — {verdict}")
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


# ── verify — 기존 레포(.claude/.cursor)를 adopt→resolve 로 정적 검증(CI 게이트) ──
def _load_policy(repo: Path) -> dict[str, str]:
    """`.harness/policy.yaml` 의 severity 오버라이드 — {category: violation|warning|ignore}."""
    p = repo / ".harness" / "policy.yaml"
    if not p.is_file():
        return {}
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}
    sev = doc.get("severity", {}) if isinstance(doc, dict) else {}
    return {str(k): str(v) for k, v in sev.items()} if isinstance(sev, dict) else {}


def cmd_preview(args: argparse.Namespace) -> int:
    """실행 전 조립 분해를 보여준다(모델 호출 없음). 기본 text, CI 용 --format json."""
    report = preview(
        _load_config(args.config),
        _registry(args.catalog),
        eject_target=args.target,
        policy=_load_governance(getattr(args, "policy", None)),
    )
    if args.format == "json":
        print(report.model_dump_json(indent=2, exclude_none=True))
        return 0 if report.ok else 1

    print(f"{'✓' if report.ok else '✗'} {report.harness_id} · {report.model.get('name', '?')}")
    for label, b in (("컨텍스트 토큰", report.context_budget), ("추가 도구", report.tool_budget)):
        if b is None:
            continue
        print(f"  {label}: {b.used} / {b.limit}{' ⚠ 초과' if b.over else ''} (추정)")
    for c in report.components:
        dep = " [deprecated]" if c.status == "deprecated" else ""
        print(f"    · {c.id:24s} {c.context_tokens:>6}토큰 ({c.share:.0%}) 도구+{c.added_tools}{dep}")
    if report.prompt_sections:
        print(f"  시스템 프롬프트 {report.prompt_chars}자 · 조각 {len(report.prompt_sections)}개")
        for sec in report.prompt_sections:
            print(f"    {sec.layer}. {sec.source} — {sec.tokens}토큰")
    for m in report.mcp_servers:
        where = "API 전송" if m.sent_to_api else "eject(로컬)"
        print(f"  MCP {m.id} [{m.transport}] → {where}")
    for event, steps in report.hooks.items():
        chain = " → ".join(f"{s.id}{'(blocking)' if s.blocking else ''}" for s in steps)
        print(f"  훅 {event}: {chain}")
    for a in report.auth:
        print(f"  인증 {a.component_id}: {'충족' if a.satisfied else '미충족'} ({a.granted_scope or '축소값 없음'})")
    for d in report.diagnostics:
        print(f"  [{d.severity}] {d.code}: {d.message}")
    for n in report.notes:
        print(f"  ※ {n}")
    if report.eject_files is not None:
        names = ", ".join(sorted(report.eject_files))
        print(f"  eject({report.eject_target}) 파일 {len(report.eject_files)}개: {names}")
    return 0 if report.ok else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    """저장된 하네스 ↔ 현재 카탈로그의 드리프트를 진단한다. --fix 는 안전한 것만 적용한다."""
    config = _load_config(args.config)
    report = doctor(config, _registry(args.catalog))

    if args.format == "json":
        print(report.model_dump_json(indent=2, exclude_none=True))
    else:
        icon = {"missing": "✗", "deprecated": "⚠", "upgrade_available": "↑", "unpinned": "📌", "ok": "✓"}
        for f in report.findings:
            if f.issue == "ok" and not args.all:
                continue
            arrow = f"  → {f.suggested_ref}" if f.suggested_ref else ""
            print(f"  {icon.get(f.issue, '·')} {f.component_id}: {f.detail or '최신'}{arrow}")
        counts = ", ".join(f"{k} {v}" for k, v in sorted(report.summary().items())) or "없음"
        print(f"{'✓ 이상 없음' if report.ok else '진단'} — {counts}")
        for n in report.notes:
            print(f"  ※ {n}")

    if args.fix:
        fixed = apply_suggestions(config, report)
        if fixed == config:
            print("적용할 안전한 제안이 없습니다.", file=sys.stderr)
        else:
            doc = fixed.model_dump(exclude_none=True, exclude_defaults=True, by_alias=True)
            Path(args.config).write_text(
                yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            print(f"✓ {args.config} 갱신(같은 id 의 버전 교체만 — 타 컴포넌트 대체는 수동)")
        return 0

    # blocking(사라짐·deprecated)만 non-zero — 업그레이드 권고로 CI 를 깨지 않는다.
    return 1 if report.blocking else 0


def cmd_verify(args: argparse.Namespace) -> int:
    """레포를 adopt→resolve 로 검증 — ①능력 미충족 ②이식 손실 ③리졸버 에러. CI 게이트(종료코드).

    판정은 `harness_runtime.verify`(코어, CLI/API 공용 — 드리프트 방지). CLI 는 심각도/정책/종료코드/
    출력·옵트인 신호만 담당. caps 판정은 TASK 3 완료 전 잠정(거짓 gap 가능)이라 기본 warning.
    """
    repo = Path(args.repo)
    if not repo.is_dir():
        print(f"✗ 레포 디렉터리 없음: {repo}", file=sys.stderr)
        return 2
    registry = _registry(args.catalog)
    require = [c.strip() for c in (args.require or "").split(",") if c.strip()]
    try:
        report = verify(read_native_tree(repo), registry, require=require, target=args.target)
    except ValueError as exc:  # 미지원 타깃 등
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — 실행 오류는 종료코드 2(위반 1 과 구분)
        print(f"✗ 실행 오류: {exc}", file=sys.stderr)
        return 2

    severity = {**DEFAULT_SEVERITY, **_load_policy(repo)}
    viols = violations(report.findings, severity)
    exit_code = 1 if viols else 0

    if args.record:  # 5e: 옵트인 데이터 수집(로컬 로그 신호 — aggregate_*.py 가 durable 집계)
        _emit_signals(report.findings, report.component_ids)

    out: dict[str, Any] = {
        "repo": str(repo),
        "target": args.target,
        "ok": exit_code == 0,
        "violations": viols,
        "findings": {c: v for c, v in report.findings.items() if v and severity.get(c) != "ignore"},
        "adopt": {
            "unknown_mcp": report.unknown_mcp,
            "unknown_skills": report.unknown_skills,
            "hooks": report.hooks,
        },
        "note": "capability 판정은 TASK 3(caps 커버리지) 완료 전 잠정 — 거짓 gap 가능(기본 warning)",
    }
    if args.format == "json":
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        _print_verify_text(out, severity.get)
    return exit_code


def _print_verify_text(report: dict[str, Any], sev: Any) -> None:
    mark = "✓ 통과" if report["ok"] else "✗ 위반"
    print(f"{mark} — {report['repo']}" + (f" (target={report['target']})" if report["target"] else ""))
    labels = {
        "resolve_error": "리졸버 에러(훅 계약 등)",
        "required_missing": "요구 능력 미충족(--require)",
        "capability_gap": "능력 gap(잠정)",
        "portability_loss": "이식 손실",
        "resolve_warning": "경고",
    }
    for cat, items in report["findings"].items():
        badge = "✗" if sev(cat) == "violation" else "!"
        print(f"  {badge} [{sev(cat)}] {labels.get(cat, cat)} ({len(items)})", file=sys.stderr)
        for it in items:
            desc = it.get("message") or it.get("detail") or it.get("capability") or str(it)
            extra = f" [{it['fidelity']}]" if it.get("fidelity") else ""
            print(f"      - {desc}{extra}", file=sys.stderr)


def _emit_signals(findings: dict[str, list[dict[str, Any]]], component_ids: list[str]) -> None:
    """5e 옵트인 신호(stderr, 마커 라인) — GAP_SIGNAL(source=verify) + COOCCUR_SIGNAL(공출현).

    기존 aggregate_gaps.py(GAP_SIGNAL)·aggregate_cooccurrence.py(COOCCUR_SIGNAL)가 durable 집계한다.
    로컬 전용(전송 아님). env/시크릿은 담지 않는다(5b — 능력·컴포넌트 id 만).
    """
    seen: set[str] = set()
    for cat in ("capability_gap", "required_missing"):
        for item in findings.get(cat, []):
            cap = item.get("capability")
            if not cap or cap in seen:
                continue
            seen.add(cap)
            payload = {
                "capability": cap,
                "suggested_type": suggested_component_type(cap),
                "facet": facet_for_capability(cap) or "",
                "source": "verify",
            }
            print(f"GAP_SIGNAL {json.dumps(payload, ensure_ascii=False, sort_keys=True)}", file=sys.stderr)
    ids = sorted(set(component_ids))
    if len(ids) >= 2:  # 공출현은 2개 이상 함께 등장할 때만 의미가 있다
        payload = {"components": ids, "source": "verify"}
        print(f"COOCCUR_SIGNAL {json.dumps(payload, ensure_ascii=False, sort_keys=True)}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="harness.yaml 을 resolve/eject 한다.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="검증된 레시피로 harness.yaml 을 만든다.")
    p_init.add_argument("--recipe", default=None, help="레시피 이름(생략 시 목록 출력)")
    p_init.add_argument("--list", action="store_true", help="레시피 목록만 출력")
    p_init.add_argument("-o", "--output", default=None, help="쓸 파일 경로(생략 시 stdout)")
    p_init.add_argument("--force", action="store_true", help="기존 파일 덮어쓰기")
    p_init.set_defaults(func=cmd_init)

    p_resolve = sub.add_parser("resolve", help="harness.yaml 을 검증(진단)한다.")
    p_resolve.add_argument("config", help="harness.yaml 경로")
    p_resolve.add_argument(
        "--policy", default=None, help="조직 정책 파일(.harness/policy.yaml 형식) — 위반 시 차단"
    )
    p_resolve.add_argument("--catalog", default=None, help="카탈로그 components 디렉터리(기본: 자동 탐색)")
    p_resolve.set_defaults(func=cmd_resolve)

    p_eject = sub.add_parser("eject", help="ResolvedHarness 를 런타임 네이티브 포맷으로 방출한다.")
    p_eject.add_argument("config", help="harness.yaml 경로")
    p_eject.add_argument("--to", required=True, choices=available_targets(), help="타깃 런타임")
    p_eject.add_argument("--out", default=".", help="출력 디렉터리(기본: 현재 폴더)")
    p_eject.add_argument("--dry-run", action="store_true", help="디스크에 쓰지 않고 생성될 내용만 출력")
    p_eject.add_argument(
        "--policy", default=None, help="조직 정책 파일(.harness/policy.yaml 형식) — 위반 시 차단"
    )
    p_eject.add_argument("--catalog", default=None, help="카탈로그 components 디렉터리(기본: 자동 탐색)")
    p_eject.set_defaults(func=cmd_eject)

    p_eval = sub.add_parser("eval", help="하네스를 eval 케이스로 실행·채점한다(경험적 검증).")
    p_eval.add_argument("config", help="harness.yaml 경로")
    p_eval.add_argument("--cases", default=None, help="eval 케이스 YAML 경로(cases: [...])")
    p_eval.add_argument(
        "--scenario", default=None, help="시드 시나리오 이름(pr-review|issue-triage|doc-draft)"
    )
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

    p_ablate = sub.add_parser("ablate", help="컴포넌트 하나를 빼고 eval 델타를 재 기여도를 측정한다.")
    p_ablate.add_argument("config", help="harness.yaml 경로")
    p_ablate.add_argument("--cases", default=None, help="eval 케이스 YAML 경로")
    p_ablate.add_argument("--scenario", default=None, help="시드 시나리오 이름")
    p_ablate.add_argument("--drop", required=True, help="빼서 기여도를 잴 컴포넌트 id")
    p_ablate.add_argument("--catalog", default=None, help="카탈로그 components 디렉터리(기본: 자동 탐색)")
    p_ablate.set_defaults(func=cmd_ablate)

    p_preview = sub.add_parser(
        "preview", help="실행 전 조립 분해를 본다(프롬프트 조각·MCP·훅·예산). 모델 호출 없음."
    )
    p_preview.add_argument("config", help="harness.yaml 경로")
    p_preview.add_argument("--target", default=None, choices=available_targets(), help="함께 볼 eject 타깃")
    p_preview.add_argument("--format", choices=["json", "text"], default="text", help="출력(기본 text)")
    p_preview.add_argument(
        "--policy", default=None, help="조직 정책 파일(.harness/policy.yaml 형식) — 위반 시 차단"
    )
    p_preview.add_argument("--catalog", default=None, help="카탈로그 components 디렉터리(기본: 자동 탐색)")
    p_preview.set_defaults(func=cmd_preview)

    p_doctor = sub.add_parser(
        "doctor", help="저장된 하네스가 카탈로그 갱신에 뒤처졌는지 진단한다(드리프트·deprecated·업그레이드)."
    )
    p_doctor.add_argument("config", help="harness.yaml 경로")
    p_doctor.add_argument("--fix", action="store_true", help="안전한 제안(같은 id 의 버전 교체)만 파일에 적용")
    p_doctor.add_argument("--all", action="store_true", help="이상 없는 컴포넌트도 출력")
    p_doctor.add_argument("--format", choices=["json", "text"], default="text", help="출력(기본 text)")
    p_doctor.add_argument("--catalog", default=None, help="카탈로그 components 디렉터리(기본: 자동 탐색)")
    p_doctor.set_defaults(func=cmd_doctor)

    p_verify = sub.add_parser(
        "verify", help="기존 레포(.claude/.cursor)를 adopt→resolve 로 정적 검증(CI 게이트)."
    )
    p_verify.add_argument("repo", help="검증할 레포 디렉터리(.claude/·.cursor/ 포함)")
    p_verify.add_argument("--require", default="", help="쉼표구분 요구 능력(예: vcs.code-review,comms.messaging)")
    p_verify.add_argument("--target", default=None, choices=available_targets(), help="이식 손실을 잴 타깃")
    p_verify.add_argument("--format", choices=["json", "text"], default="json", help="출력(기본 json — CI)")
    p_verify.add_argument(
        "--record",
        action="store_true",
        help="옵트인 데이터 수집 — gap/공출현을 로그 신호로 방출(로컬, 2>signals.log 로 수집)",
    )
    p_verify.add_argument("--catalog", default=None, help="카탈로그 components 디렉터리(기본: 자동 탐색)")
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
