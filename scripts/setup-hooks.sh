#!/usr/bin/env bash
# git 훅 활성화(레포당 1회). 클론 후 한 번 실행하면 pre-push 프리플라이트가 걸린다.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
git -C "$ROOT" config core.hooksPath .githooks
chmod +x "$ROOT"/.githooks/* "$ROOT"/scripts/*.sh 2>/dev/null || true
echo "✓ core.hooksPath=.githooks 설정 완료 — 이제 git push 전에 프리플라이트가 실행됩니다."
