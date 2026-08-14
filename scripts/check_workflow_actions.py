#!/usr/bin/env python3
"""GitHub Actions 워크플로의 `uses:` 액션 버전이 실제로 존재하는지 검증한다.

`aquasecurity/trivy-action@0.28.0` 처럼 태그가 없어서 CI 가
"Unable to resolve action ... unable to find version" 로 죽는 걸 푸시 전에 잡는다.

- 태그/브랜치 ref: `git ls-remote` 로 원격에 존재하는지 확인(공개 레포는 인증 불필요).
- 40자리 커밋 SHA 로 핀한 경우: 의도적 핀으로 보고 건너뜀.
- 로컬 액션(`./...`)·docker 액션(`docker://...`): 건너뜀.
- 네트워크 오류(원격 접속 자체 실패)면 실패로 보지 않고 경고만 하고 통과(오프라인 오탐 방지).

종료코드: 존재하지 않는 ref 가 하나라도 있으면 1, 아니면 0.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / ".github" / "workflows"
USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?([^'\"\s#]+)")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def find_action_refs() -> list[tuple[str, str, str, pathlib.Path, int]]:
    """(owner/repo, ref, raw, file, lineno) 목록을 워크플로에서 추출."""
    refs: list[tuple[str, str, str, pathlib.Path, int]] = []
    if not WORKFLOW_DIR.is_dir():
        return refs
    for wf in sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")]):
        for i, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = USES_RE.match(line)
            if not m:
                continue
            raw = m.group(1)
            if raw.startswith((".", "docker://")) or "@" not in raw:
                continue
            path, ref = raw.rsplit("@", 1)
            parts = path.split("/")
            if len(parts) < 2:
                continue
            refs.append((f"{parts[0]}/{parts[1]}", ref, raw, wf, i))
    return refs


def ref_exists(repo: str, ref: str) -> bool | None:
    """True=존재, False=원격엔 접속됐지만 ref 없음, None=접속 자체 실패(판정 보류)."""
    url = f"https://github.com/{repo}"
    queries = [f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}", f"refs/heads/{ref}"]
    try:
        out = subprocess.run(
            ["git", "ls-remote", "--quiet", url, *queries],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None  # 접속/인증 실패 → 판정 보류
    return bool(out.stdout.strip())


def main() -> int:
    refs = find_action_refs()
    if not refs:
        print("검증할 워크플로 액션이 없습니다.")
        return 0

    seen: dict[tuple[str, str], bool | None] = {}
    bad = False
    for repo, ref, raw, wf, lineno in refs:
        key = (repo, ref)
        if key not in seen:
            seen[key] = None if SHA_RE.match(ref) else ref_exists(repo, ref)
        status = seen[key]
        loc = f"{wf.relative_to(ROOT)}:{lineno}"
        if SHA_RE.match(ref):
            print(f"  · {raw}  (SHA 핀 — 건너뜀)  {loc}")
        elif status is True:
            print(f"  ✓ {raw}  {loc}")
        elif status is None:
            print(f"  ? {raw}  (원격 확인 불가 — 통과 처리)  {loc}")
        else:
            print(f"  ✗ {raw}  → '{ref}' 태그/브랜치를 {repo} 에서 찾을 수 없음  {loc}")
            bad = True

    if bad:
        print("\n존재하지 않는 액션 버전이 있습니다. (예: 태그에 v 접두사 누락)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
