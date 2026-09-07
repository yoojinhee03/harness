"""랭킹 eval — 추천 품질을 골든셋으로 잰다. 백로그 #2(공출현 신호 → 랭킹)의 선행 게이트.

**왜 별도인가** — `harness_runtime.eval`(Phase 11)은 *프롬프트 출력* 을 잰다("하네스를 붙이면
출력이 나아지는가"). 여기는 그 앞단인 *추천* 을 잰다("설명에 맞는 컴포넌트를 골라 위로 올리는가").
`ranking.py` 를 바꾸는 작업은 후자로만 회귀를 볼 수 있다. 두 eval 은 대상이 달라 겹치지 않는다.

**결정성** — `LocalEmbedder` + `NullReasoner`(휴리스틱 추출) 로 고정한다. 키가 있든 없든 같은
수를 내야 회귀 판정이 성립한다. 키 경로(Voyage/Claude)의 품질 측정은 이 계약이 아니다.

**시드 카탈로그에서 무엇이 관측되는가(실측)** — 큐레이션 시드 13개에서는 relevance floor 때문에
능력 매칭된 것만 올라오므로 *포함 여부*는 랭킹이 아니라 그라운딩 계약을 잰다. 순서를 실제로
움직이는 축은 **비용(`_W_TOKENS`)과 임베딩(`_W_EMBED`)** 둘뿐이다:
  - `_W_EXPLORE` 는 시드 전체가 `usage_count == 0` 이라 모든 후보에 같은 상수 → 순서 불변.
  - `_W_CAPABILITY` 는 후보들의 매칭 개수가 같으면(df=1 태그가 대부분) 역시 상수 → 순서 불변.
따라서 **이 골든셋은 그 두 축의 퇴행을 잡지 못한다.** 거기까지 덮으려면 매칭 개수·사용량이
갈리는 대규모 수확 카탈로그가 필요하다(`CATALOG_DIR` 로 교체해 같은 골든셋을 돌린다).
`_W_USAGE`·`_W_RETENTION`·`_W_EXPLORE` 는 피드백 루프(Phase 9)가 신호를 채우면 살아난다 —
`rank(usage=...)` 로 실측이 들어오는 순간 이 세 축이 관측 가능해진다.

**판정을 둘로 나눈다** — eval 설계의 고전적 함정은 개선까지 실패로 만드는 것이다.
  - **하드(pass/fail)**: `expect_ids` 포함 · `expect_absent` 배제 · `expect_gaps` 정합.
    파이프라인 계약이라 개선해도 안 흔들린다.
  - **소프트(수치)**: `recall@k` · `mean_rr` · `prefer_order` 만족 수. 전부 **하한(floor)** 으로만
    걸어 개선은 통과시키고 퇴행만 잡는다. 특히 `prefer_order` 에는 *지금 못 맞히는* 쌍도 적어둔다
    (알려진 약점) — 케이스 pass/fail 은 안 건드리고 총합만 관리하므로, #2 가 올려야 할 목표치가 된다.

사용:
    from harness_catalog.rank_eval import load_cases, evaluate, build_eval_recommender
    report = evaluate(build_eval_recommender(build_registry()), load_cases(path))
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from harness_resolver import Registry
from pydantic import BaseModel, Field

from .embeddings import LocalEmbedder
from .reasoning import NullReasoner
from .recommender import Recommender
from .store import VectorStore

# 골든셋 파일의 자기식별 태그 — 프롬프트 eval(harness-catalog/evals/pr-review.yaml)과 섞이지 않게.
KIND = "ranking-golden"


class RankingCase(BaseModel):
    """골든 케이스 한 건 — 설명 하나에 대한 기대 추천."""

    name: str
    description: str
    top_k: int = 6
    expect_ids: list[str] = Field(default_factory=list)
    """top_k 안에 반드시 있어야 하는 컴포넌트 id."""
    expect_absent: list[str] = Field(default_factory=list)
    """top_k 안에 있으면 안 되는 id — 잡음 카드 회귀 방지."""
    expect_gaps: list[str] = Field(default_factory=list)
    """gap 으로 보고돼야 하는 능력. 통제어휘 정합이라 결정적이다(발명 금지 계약)."""
    exact_gaps: bool = True
    """True 면 gap 집합이 `expect_gaps` 와 정확히 일치해야 한다(거짓 gap 도 회귀)."""
    prefer_order: list[list[str]] = Field(default_factory=list)
    """[상위 id, 하위 id] 쌍 — 케이스 pass/fail 에는 넣지 않고 만족 수만 센다(알려진 약점 기록)."""


class GoldenSet(BaseModel):
    kind: str = KIND
    name: str = "unnamed"
    cases: list[RankingCase]


class CaseResult(BaseModel):
    name: str
    returned: list[str]
    """top_k 로 자른 추천 id(순서 보존)."""
    ranks: dict[str, int] = Field(default_factory=dict)
    """기대 id → 전체 랭킹에서의 1-기반 순위. 0 은 '아예 안 나옴'."""
    recall: float
    mean_rr: float
    """기대 id 들의 평균 역순위.

    ⚠️ **맹점** — 기대 id 가 상위를 연속으로 차지하면 자기들끼리의 순서 변화에 무감각하다
    (1·2위를 맞바꿔도 (1+0.5)/2 로 동일). 즉 이 수는 '기대 id 가 아래로 밀리거나 사라졌는가'만
    잡고 '기대 id 들 사이의 순서'는 못 잡는다. 후자는 `prefer_order` 가 담당한다."""
    missing: list[str] = Field(default_factory=list)
    leaked: list[str] = Field(default_factory=list)
    """`expect_absent` 인데 top_k 에 들어온 id."""
    gap_diff: list[str] = Field(default_factory=list)
    """gap 불일치 — 누락은 `-cap`, 잉여는 `+cap`."""
    order_ok: int = 0
    order_total: int = 0
    scored: bool = True
    """기대 id 가 있어 순위 수치가 의미를 갖는가. 전부-gap 케이스는 False —
    잴 게 없어서 나온 recall/rr 1.0 이 집계 평균을 부풀리면 하한선의 민감도가 죽는다."""
    passed: bool = True

    @property
    def order_violations(self) -> int:
        return self.order_total - self.order_ok


class EvalReport(BaseModel):
    name: str
    cases: list[CaseResult]

    @property
    def scored_cases(self) -> list[CaseResult]:
        """순위 수치가 의미 있는 케이스만 — 전부-gap 케이스는 빠진다."""
        return [c for c in self.cases if c.scored]

    @property
    def pass_rate(self) -> float:
        # 통과율은 전부-gap 케이스도 포함한다(하드 판정은 거기서도 의미가 있다).
        return _mean([1.0 if c.passed else 0.0 for c in self.cases])

    @property
    def mean_recall(self) -> float:
        return _mean([c.recall for c in self.scored_cases])

    @property
    def mean_rr(self) -> float:
        return _mean([c.mean_rr for c in self.scored_cases])

    @property
    def order_ok(self) -> int:
        return sum(c.order_ok for c in self.cases)

    @property
    def order_total(self) -> int:
        return sum(c.order_total for c in self.cases)

    @property
    def failed(self) -> list[CaseResult]:
        return [c for c in self.cases if not c.passed]


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def build_eval_recommender(registry: Registry) -> Recommender:
    """결정적 구성의 Recommender — 로컬 임베더 + 휴리스틱 추출 + 인메모리 스토어.

    영속 스토어(pgvector)를 쓰지 않는다: eval 은 외부 상태에 기대면 안 된다.
    """
    return Recommender(
        registry,
        embedder=LocalEmbedder(),
        reasoner=NullReasoner(),
        store=VectorStore(),
    )


def default_golden_path() -> Path:
    """골든셋 기본 위치 — 카탈로그 데이터 옆(`harness-catalog/evals/ranking-golden.yaml`).

    `RANK_EVAL_GOLDEN` 로 덮어쓸 수 있다. 탐색 규칙은 loader.resolve_catalog_dir 와 같은 결
    (cwd·이 파일 위치에서 위로) 이되 대상이 evals 폴더다.
    """
    env = os.environ.get("RANK_EVAL_GOLDEN")
    if env:
        return Path(env).expanduser().resolve()
    for start in (Path.cwd(), Path(__file__).resolve()):
        for ancestor in [start, *start.parents]:
            for candidate in (
                ancestor / "harness-catalog" / "evals" / "ranking-golden.yaml",
                ancestor.parent / "harness-catalog" / "evals" / "ranking-golden.yaml",
            ):
                if candidate.is_file():
                    return candidate.resolve()
    raise FileNotFoundError(
        "랭킹 골든셋을 찾을 수 없습니다 — RANK_EVAL_GOLDEN 을 설정하거나 "
        "harness-catalog/evals/ranking-golden.yaml 을 두세요."
    )


def load_cases(path: str | Path | None = None) -> GoldenSet:
    """골든셋 YAML 로드. `kind` 가 다르면 거부한다(프롬프트 eval 파일 오투입 방지)."""
    p = Path(path) if path else default_golden_path()
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    kind = doc.get("kind")
    if kind != KIND:
        raise ValueError(f"{p}: kind={kind!r} — 랭킹 골든셋이 아닙니다(기대: {KIND!r}).")
    return GoldenSet.model_validate(doc)


def evaluate_case(rec: Recommender, case: RankingCase) -> CaseResult:
    """케이스 하나 채점. 순위는 top_k 가 아니라 **전체 랭킹**에서 읽는다.

    top_k 안에서만 순위를 보면 6위→7위로 밀린 퇴행을 '그냥 사라짐'으로만 관측하게 된다.
    전체를 받아두면 몇 계단 밀렸는지가 mean_rr 에 연속적으로 잡힌다.
    """
    catalog_size = len(rec.registry.all())
    result = rec.recommend(case.description, top_k=max(catalog_size, case.top_k))
    full = [r.id for r in result.recommendations]
    returned = full[: case.top_k]
    at_k = set(returned)

    ranks = {cid: (full.index(cid) + 1 if cid in full else 0) for cid in case.expect_ids}
    hits = [cid for cid in case.expect_ids if cid in at_k]
    recall = round(len(hits) / len(case.expect_ids), 4) if case.expect_ids else 1.0
    # 기대 id 별 역순위의 평균 — 순위가 밀리면 연속적으로 떨어진다(못 나오면 0).
    mean_rr = _mean([1.0 / r if r else 0.0 for r in ranks.values()]) if ranks else 1.0

    got_gaps = {g.capability for g in result.gaps}
    want_gaps = set(case.expect_gaps)
    missing_gaps = sorted(want_gaps - got_gaps)
    extra_gaps = sorted(got_gaps - want_gaps) if case.exact_gaps else []
    gap_diff = [f"-{c}" for c in missing_gaps] + [f"+{c}" for c in extra_gaps]

    order_total = len(case.prefer_order)
    order_ok = sum(1 for hi, lo in case.prefer_order if _outranks(full, hi, lo))

    leaked = [cid for cid in case.expect_absent if cid in at_k]
    missing = [cid for cid in case.expect_ids if cid not in at_k]

    return CaseResult(
        name=case.name,
        returned=returned,
        ranks=ranks,
        recall=recall,
        mean_rr=mean_rr,
        missing=missing,
        leaked=leaked,
        gap_diff=gap_diff,
        order_ok=order_ok,
        order_total=order_total,
        scored=bool(case.expect_ids),
        # prefer_order 는 판정에 넣지 않는다 — 알려진 약점 기록용.
        passed=not (missing or leaked or gap_diff),
    )


def _outranks(full: list[str], hi: str, lo: str) -> bool:
    """`hi` 가 `lo` 보다 위인가. 둘 다 나와야 참으로 친다(안 나온 건 만족이 아니다)."""
    if hi not in full or lo not in full:
        return False
    return full.index(hi) < full.index(lo)


def evaluate(rec: Recommender, golden: GoldenSet) -> EvalReport:
    return EvalReport(
        name=golden.name,
        cases=[evaluate_case(rec, c) for c in golden.cases],
    )


def format_report(report: EvalReport, *, verbose: bool = False) -> str:
    """사람이 읽는 요약 — 스크립트/CI 로그용."""
    n_scored = len(report.scored_cases)
    lines = [
        f"랭킹 eval: {report.name} — 케이스 {len(report.cases)} (순위채점 {n_scored})",
        f"  통과율   {report.pass_rate:.1%}",
        f"  recall@k {report.mean_recall:.4f}",
        f"  mean_rr  {report.mean_rr:.4f}",
        f"  선호순서 {report.order_ok}/{report.order_total} (케이스 판정 제외)",
    ]
    for c in report.cases:
        mark = "✓" if c.passed else "✗"
        nums = (
            f"recall={c.recall:.2f} rr={c.mean_rr:.3f}"
            if c.scored
            else "recall=  —  rr=  —  "  # 전부-gap 케이스: 순위로 잴 게 없다
        )
        lines.append(f"  {mark} {c.name:22s} {nums} order={c.order_ok}/{c.order_total}")
        if c.missing:
            lines.append(f"      누락 id: {', '.join(c.missing)}")
        if c.leaked:
            lines.append(f"      잡음 id: {', '.join(c.leaked)}")
        if c.gap_diff:
            lines.append(f"      gap 불일치: {', '.join(c.gap_diff)}")
        if verbose:
            lines.append(f"      반환: {', '.join(c.returned) or '(없음)'}")
            if c.ranks:
                lines.append("      순위: " + ", ".join(f"{k}={v or '—'}" for k, v in c.ranks.items()))
    return "\n".join(lines)
