"""능력 태깅 커버리지 실측 — 하드닝 지시서 v3 TASK 1 (TASK 3 스코핑 근거).

**무엇을 재나**: 카탈로그 컴포넌트 중 통제어휘 caps 를 하나도 못 뽑은 비율(빈 caps 미스율)과,
*왜* 못 뽑았는지의 원인 신호. 미스율 숫자보다 **원인 분류가 우선 산출물**이다(TASK 3 의 해법
분기를 결정하므로): 동의어·표현 차이면 제로샷 임베딩이 듣고, 통제어휘 부재면 어휘부터 확장한다.

**PRIMARY 지표 = 오프라인 휴리스틱 미스율.** `extract_capabilities_heuristic`(LLM·네트워크 무관)을
컴포넌트 텍스트에 재실행해 origin 독립적으로 잰다. enricher(LLM, 상한 150)는 근본 원인이 아니라
폴백이므로 이 측정에서 제외한다 — caps 파이프라인 자체는 TASK 3 에서 다룬다.

**origin 분리 강제**: local(수큐레이션) / registry / marketplace 를 절대 합산하지 않는다. 로컬 13개는
**스크립트 동작 검증용이며 대표값이 아니다**(caps 가 태생적으로 채워져 있어 미스율 ~0).

원인 신호(포섭 가능성 프록시): 빈 caps 컴포넌트를 임베딩해 통제어휘 벡터와 코사인 최댓값을 잰다.
- high(≥floor): 어휘는 있는데 표현이 달라 휴리스틱이 놓침 → **제로샷이 회수 가능**(TASK 3 분기 A).
- low: 가까운 어휘 자체가 없음 → **어휘 부재**(TASK 3 분기 B, 어휘 확장 먼저).
LocalEmbedder 프록시는 문자/단어 해싱이라 의미 동의어를 약하게 잡는다 → **회수 가능성의 하한**이다.
키가 있으면 `--embedder openai` 로 더 조인 신호를 얻어라.

샘플링(커서 페이지네이션 한계): registry 는 `updated_since` 순 커서라 offset·랜덤 접근이 없다.
`--sample N`(기본 200)은 **앞 N개 = 최신순 편향 표본**이다(크롤 절약). 무편향이 필요하면 `--full`.
marketplace(단일 파일 ≤500)·local(13)은 전수 측정하므로 샘플링 대상이 아니다.

사용:
    # 로컬 전수(네트워크 불필요, 스크립트 검증)
    python packages/catalog/scripts/measure_caps.py --source local

    # 라이브 실측(네트워크 필요) — 앞 200개 표본, 원인 신호 포함
    python packages/catalog/scripts/measure_caps.py --source all --sample 200 --out docs/caps-coverage-baseline.md

    # fetch/측정 분리(재현성): 네트워크 있는 곳에서 스냅샷 저장 → 오프라인 반복 측정
    python packages/catalog/scripts/measure_caps.py --source registry --full --save-snapshot reg.json
    python packages/catalog/scripts/measure_caps.py --from-snapshot reg.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# 패키지 부트스트랩 — uv 없이 `python` 으로도 돌게 워크스페이스 src 를 경로에 얹는다.
_ROOT = Path(__file__).resolve().parents[3]  # …/harness-architect
for _pkg in ("catalog", "resolver", "runtime"):
    _src = _ROOT / "packages" / _pkg / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from harness_catalog import (  # noqa: E402
    CAPABILITY_VOCAB,
    LocalEmbedder,
    MarketplaceSource,
    MCPRegistrySource,
    build_registry,
    extract_capabilities_heuristic,
    resolve_catalog_dir,
)
from harness_resolver import Component  # noqa: E402

RELEVANCE_FLOOR = 0.20  # recommender.RELEVANCE_FLOOR 미러 — 프록시 회수 임계값


def _component_text(c: Component) -> str:
    """휴리스틱이 보는 것과 같은 원문(name+summary+description+keywords). caps 는 순환이라 제외."""
    return " ".join([c.name, c.summary, c.description, *c.keywords]).strip()


# ── 소스 로딩 (origin 별) ─────────────────────────────────────────────────────
def load_local() -> list[Component]:
    return list(build_registry(resolve_catalog_dir()).all())


def load_registry(sample: int | None, full: bool) -> list[Component]:
    if full:
        src = MCPRegistrySource()  # 기본 max_pages=50, page_limit=100 (전량)
    else:
        n = sample or 200
        pages = max(1, math.ceil(n / 100))
        src = MCPRegistrySource(page_limit=min(100, n), max_pages=pages)  # 앞 N개(최신순 편향)
    comps = list(src.components())
    return comps if full or sample is None else comps[:sample]


def load_marketplace() -> list[Component]:
    return list(MarketplaceSource().components())  # 단일 파일 전수


# ── 스냅샷 (fetch/측정 분리) ───────────────────────────────────────────────────
def save_snapshot(path: str, by_origin: dict[str, list[Component]]) -> None:
    doc = {o: [c.model_dump(mode="json") for c in cs] for o, cs in by_origin.items()}
    Path(path).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def load_snapshot(path: str) -> dict[str, list[Component]]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {o: [Component.model_validate(d) for d in ds] for o, ds in doc.items()}


# ── 원인 신호 (포섭 가능성 프록시) ─────────────────────────────────────────────
def _vocab_docs() -> dict[str, str]:
    """통제어휘 항목 → 임베딩용 텍스트(cap 명 + 키워드)."""
    return {
        cap: cap.replace(".", " ").replace("-", " ") + " " + " ".join(kw)
        for cap, (_facet, kw) in CAPABILITY_VOCAB.items()
    }


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def cause_signal(empty: list[Component], embedder: LocalEmbedder) -> list[dict[str, Any]]:
    """빈 caps 컴포넌트별: 통제어휘와의 최대 코사인 + argmax cap + 버킷. 회수 가능성 프록시."""
    vocab = _vocab_docs()
    vcaps = list(vocab)
    vvecs = embedder.embed([vocab[c] for c in vcaps])
    cvecs = embedder.embed([_component_text(c) for c in empty])
    out: list[dict[str, Any]] = []
    for comp, cv in zip(empty, cvecs, strict=True):
        best_cap, best = "", -1.0
        for cap, vv in zip(vcaps, vvecs, strict=True):
            s = _cosine(cv, vv)
            if s > best:
                best_cap, best = cap, s
        bucket = "high" if best >= RELEVANCE_FLOOR else ("mid" if best >= 0.10 else "low")
        out.append(
            {
                "id": comp.id,
                "name": comp.name,
                "desc": (comp.summary or comp.description)[:100],
                "top_vocab": best_cap,
                "max_cosine": round(best, 3),
                "bucket": bucket,
            }
        )
    return out


# ── origin 별 측정 ─────────────────────────────────────────────────────────────
def measure_origin(
    origin: str, comps: list[Component], embedder: LocalEmbedder, k: int
) -> dict[str, Any]:
    total = len(comps)
    # PRIMARY: 휴리스틱을 텍스트에 재실행(origin 독립). tagged: 로딩 시 이미 붙은 caps.
    heur_empty = [c for c in comps if not extract_capabilities_heuristic(_component_text(c))]
    tagged_empty = [c for c in comps if not c.capability_tags]
    signals = cause_signal(heur_empty, embedder) if heur_empty else []
    buckets = {"high": 0, "mid": 0, "low": 0}
    for s in signals:
        buckets[s["bucket"]] += 1
    return {
        "origin": origin,
        "total": total,
        "heuristic_empty": len(heur_empty),
        "heuristic_miss_rate": round(len(heur_empty) / total, 4) if total else 0.0,
        "tagged_empty": len(tagged_empty),
        "cause_buckets": buckets,  # 회수 가능성: high=제로샷 회수 가능, low=어휘 부재
        "samples": signals[:k],
    }


# ── 출력 ───────────────────────────────────────────────────────────────────────
def render_markdown(results: list[dict[str, Any]], meta: dict[str, str]) -> str:
    L: list[str] = ["# 능력 태깅 커버리지 baseline (TASK 1 실측)", ""]
    L.append(f"- 임베더(프록시): `{meta['embedder']}` · 회수 임계값 floor={RELEVANCE_FLOOR}")
    L.append(f"- 샘플 모드: {meta['sample_mode']}")
    L.append("")
    if any(r["origin"] == "local" for r in results):
        L.append(
            "> **로컬 origin 은 대표값이 아니다** — 수큐레이션 13개라 caps 가 태생적으로 채워져 "
            "미스율 ~0. 스크립트 동작 검증용이다. 대표 신호는 registry/marketplace 를 봐라."
        )
    L.append(
        "> **LocalEmbedder 프록시는 회수 가능성의 하한**이다(해싱 벡터라 의미 동의어를 약하게 잡음). "
        "`high` 로 나오면 확실히 제로샷 회수 가능, `low` 는 어휘부재일 수도·프록시 한계일 수도 있으니 "
        "`--embedder openai` 로 재확인해라."
    )
    L.append("")

    # (1) 원인 신호 — 우선 산출물 (TASK 3 분기 결정)
    L.append("## 1. 원인 신호 — 포섭 가능성 (우선 산출물)")
    L.append("")
    L.append("| origin | 빈 caps | high(제로샷↑) | mid | low(어휘부재?) | → TASK 3 분기 |")
    L.append("|---|---:|---:|---:|---:|---|")
    for r in results:
        b = r["cause_buckets"]
        e = r["heuristic_empty"]
        if e == 0:
            branch = "—(빈 caps 없음)"
        elif b["high"] >= b["low"]:
            branch = "**A: 제로샷 임베딩**(동의어 우세)"
        else:
            branch = "**B: 어휘 확장 먼저**(부재 우세)"
        L.append(f"| {r['origin']} | {e} | {b['high']} | {b['mid']} | {b['low']} | {branch} |")
    L.append("")

    # (2) 포섭 유형 샘플 — 규칙 기반 수동 분류용
    L.append("## 2. 빈 caps 샘플 (수동 원인 분류용)")
    L.append("")
    L.append(
        "판정 규칙: *기존 vocab 항목에 동의어 키워드만 추가하면 잡히나?* → **동의어** · "
        "*해당 도메인 vocab 자체가 없나?* → **어휘부재** · *설명이 1줄 미만?* → **짧음** · 비영어 → **언어**"
    )
    L.append("")
    for r in results:
        if not r["samples"]:
            continue
        L.append(f"### {r['origin']}")
        L.append("| id | 설명(발췌) | 최근접 vocab | cos | 버킷 |")
        L.append("|---|---|---|---:|---|")
        for s in r["samples"]:
            desc = s["desc"].replace("|", "\\|").replace("\n", " ")
            L.append(f"| `{s['id']}` | {desc} | `{s['top_vocab']}` | {s['max_cosine']} | {s['bucket']} |")
        L.append("")

    # (3) origin 별 미스율 (숫자)
    L.append("## 3. origin 별 미스율 (합산 금지)")
    L.append("")
    L.append("| origin | 전체 | 휴리스틱 빈 caps | 미스율 | (참고)로딩시 tagged 빈 caps |")
    L.append("|---|---:|---:|---:|---:|")
    for r in results:
        L.append(
            f"| {r['origin']} | {r['total']} | {r['heuristic_empty']} | "
            f"{r['heuristic_miss_rate']:.1%} | {r['tagged_empty']} |"
        )
    L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="능력 태깅 커버리지 실측 (TASK 1)")
    p.add_argument("--source", choices=["registry", "marketplace", "local", "all"], default="all")
    p.add_argument("--sample", type=int, default=200, help="registry 전용, 앞 N개(최신순 편향). 기본 200")
    p.add_argument("--full", action="store_true", help="registry 전량(무편향, 크롤 비쌈)")
    p.add_argument("--from-snapshot", help="스냅샷 JSON 에서 로드(네트워크 무관·재현성)")
    p.add_argument("--save-snapshot", help="라이브 fetch 결과를 JSON 으로 저장(측정 안 함도 가능)")
    p.add_argument("--embedder", choices=["local", "openai"], default="local", help="원인 신호 프록시 임베더")
    p.add_argument("--classify-sample", type=int, default=50, help="origin 별 샘플 출력 개수")
    p.add_argument("--format", choices=["md", "json"], default="md")
    p.add_argument("--out", help="출력 파일(기본 stdout)")
    args = p.parse_args(argv)

    # 소스 수집 (origin 분리 유지)
    by_origin: dict[str, list[Component]] = {}
    if args.from_snapshot:
        by_origin = load_snapshot(args.from_snapshot)
        sample_mode = f"snapshot={args.from_snapshot}"
    else:
        want = ["registry", "marketplace", "local"] if args.source == "all" else [args.source]
        sample_mode = "full(registry 전량)" if args.full else f"registry 앞 {args.sample}개(최신순 편향)"
        for o in want:
            try:
                if o == "local":
                    by_origin[o] = load_local()
                elif o == "registry":
                    by_origin[o] = load_registry(args.sample, args.full)
                elif o == "marketplace":
                    by_origin[o] = load_marketplace()
            except Exception as exc:  # noqa: BLE001 — 네트워크 없는 환경(B)에선 라이브 origin 스킵
                print(f"경고: origin={o} 로드 실패(네트워크/키 필요?) — 스킵: {exc}", file=sys.stderr)

    if args.save_snapshot:
        save_snapshot(args.save_snapshot, by_origin)
        print(f"✓ 스냅샷 저장: {args.save_snapshot} ({sum(len(v) for v in by_origin.values())}개)", file=sys.stderr)

    if not by_origin:
        print("측정할 origin 이 없다(전부 로드 실패). --source local 또는 --from-snapshot 을 써라.", file=sys.stderr)
        return 1

    embedder = LocalEmbedder()  # openai 프록시는 키 경로 필요 — 지금은 local 고정(하한 신호)
    if args.embedder == "openai":
        print("경고: --embedder openai 는 키 경로가 필요하다. LocalEmbedder 로 폴백.", file=sys.stderr)

    results = [measure_origin(o, cs, embedder, args.classify_sample) for o, cs in by_origin.items()]
    meta = {"embedder": embedder.name, "sample_mode": sample_mode}

    if args.format == "json":
        text = json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=2)
    else:
        text = render_markdown(results, meta)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"✓ 기록: {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
