"""수확 카탈로그 재태깅 — 개선된 휴리스틱으로 DB `catalog_components` 의 caps 를 다시 계산한다.

라이브/마켓플레이스에서 수확된 MCP 들은 초기 휴리스틱의 부분문자열 오탐으로 caps 가 오염돼 있다
(예: 'ci' 가 'de**ci**sion' 안에서 → vcs.ci-cd). 라틴 단어경계 매칭 + 미디어 어휘가 들어간 지금의
`extract_capabilities_heuristic` 로 name+description+keywords 를 다시 태깅해 오탐을 걷어낸다
(틀린 태그 → 빈 태그로; 미디어 서버 → media.* 로). 소스는 네트워크가 아니라 이미 DB 에 저장된
설명 텍스트라 오프라인으로 돈다. 다음 라이브 harvest 가 돌면 어차피 같은 휴리스틱으로 재생성되므로
이 스크립트의 변경은 파생 컬럼 재계산일 뿐(원본 소실 아님).

LLM 키가 있으면 이후 sync 가 빈-캡 컴포넌트를 도메인 가이드로 추가 보강한다(enrichment).

사용:
    python packages/catalog/scripts/retag_catalog.py                 # dry-run(요약만)
    python packages/catalog/scripts/retag_catalog.py --apply         # DB 에 반영
    python packages/catalog/scripts/retag_catalog.py --db path.db --apply
기본 DB: $DATABASE_URL(sqlite) 또는 <repo>/.harness-store/harness.db
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

from harness_catalog.vocabulary import extract_capabilities_heuristic


def _default_db() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///") :]
    # <repo>/.harness-store/harness.db (이 파일: packages/catalog/scripts/)
    return str(Path(__file__).resolve().parents[4] / ".harness-store" / "harness.db")


def _recompute(name: str, description: str, keywords: list[str]) -> list[str]:
    return extract_capabilities_heuristic(" ".join([name or "", description or "", *(keywords or [])]))


def retag(db_path: str, apply: bool) -> int:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT origin, id, data FROM catalog_components").fetchall()
    changed = 0
    before_empty = after_empty = 0
    tag_delta: Counter[str] = Counter()
    updates: list[tuple[str, str, str]] = []  # (data, origin, id)

    for row in rows:
        try:
            doc = json.loads(row["data"])
        except json.JSONDecodeError:
            continue
        old = list(doc.get("capability_tags") or [])
        new = _recompute(doc.get("name", ""), doc.get("description", ""), doc.get("keywords") or [])
        before_empty += not old
        after_empty += not new
        for t in old:
            tag_delta[t] -= 1
        for t in new:
            tag_delta[t] += 1
        if new != old:
            changed += 1
            doc["capability_tags"] = new
            doc["provides"] = new
            updates.append((json.dumps(doc, ensure_ascii=False), row["origin"], row["id"]))

    print(f"대상 {len(rows)}행 · 태그 변경 {changed}행 · 빈-캡 {before_empty} → {after_empty}")
    gained = [(t, n) for t, n in tag_delta.most_common() if n > 0][:8]
    dropped = [(t, n) for t, n in sorted(tag_delta.items(), key=lambda kv: kv[1]) if n < 0][:8]
    if gained:
        print("  ↑ 늘어난 태그:", ", ".join(f"{t}(+{n})" for t, n in gained))
    if dropped:
        print("  ↓ 줄어든 태그:", ", ".join(f"{t}({n})" for t, n in dropped))

    if not apply:
        print("\n(dry-run — 반영하려면 --apply)")
        con.close()
        return 0
    with con:
        con.executemany(
            "UPDATE catalog_components SET data = ? WHERE origin = ? AND id = ?", updates
        )
    con.close()
    print(f"\n✓ {len(updates)}행 반영됨 → {db_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="수확 카탈로그를 개선된 휴리스틱으로 재태깅한다.")
    ap.add_argument("--db", default=_default_db(), help="sqlite DB 경로(기본: DATABASE_URL 또는 store)")
    ap.add_argument("--apply", action="store_true", help="DB 에 실제 반영(미지정 시 dry-run)")
    args = ap.parse_args(argv)
    if not Path(args.db).exists():
        print(f"✗ DB 없음: {args.db}")
        return 2
    return retag(args.db, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
