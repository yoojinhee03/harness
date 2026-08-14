#!/usr/bin/env bash
# CI 프리플라이트: 푸시 전에 CI 가 잡아내는 오류를 로컬에서 먼저 검증한다.
# 하나라도 실패하면 non-zero 로 종료 → pre-push 훅이 푸시를 막는다.
#
# 사용:
#   scripts/preflight.sh          # 전체(ruff + mypy + 액션버전 + pytest)
#   PREFLIGHT_FAST=1 scripts/preflight.sh   # 빠른 검사만(ruff + 액션버전)
#   git push --no-verify          # 긴급 시 훅 우회
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel)"
APP="$ROOT/harness-architect"
FAST="${PREFLIGHT_FAST:-0}"
fail=0

step() { printf '\n\033[1;34m▶ %s\033[0m\n' "$1"; }
ok()   { printf '\033[0;32m  ✓ %s\033[0m\n' "$1"; }
bad()  { printf '\033[0;31m  ✗ %s\033[0m\n' "$1"; fail=1; }

run() { # run "<라벨>" <명령...>
  local label="$1"; shift
  if "$@"; then ok "$label"; else bad "$label"; fi
}

if command -v uv >/dev/null 2>&1; then
  step "Ruff 린트"
  ( cd "$APP" && uv run ruff check . ) && ok "ruff" || bad "ruff 린트 실패"

  if [ "$FAST" != "1" ]; then
    step "Mypy 타입체크"
    ( cd "$APP" && uv run mypy \
        packages/resolver/src packages/catalog/src packages/runtime/src \
        apps/api/src apps/cli/src apps/mcp/src ) && ok "mypy" || bad "mypy 타입 오류"

    step "Alembic 마이그레이션 드리프트"
    ( cd "$APP" && rm -f .preflight-alembic.db \
        && DATABASE_URL="sqlite:///.preflight-alembic.db" uv run alembic upgrade head \
        && DATABASE_URL="sqlite:///.preflight-alembic.db" uv run alembic check; \
        rc=$?; rm -f .preflight-alembic.db; exit $rc ) \
      && ok "alembic" || bad "마이그레이션 누락(모델↔리비전 드리프트) — alembic revision --autogenerate 필요"
  fi
else
  bad "uv 미설치 — ruff/mypy 검증 불가 (https://docs.astral.sh/uv/ 설치 필요)"
fi

step "워크플로 액션 버전 검증"
python3 "$ROOT/scripts/check_workflow_actions.py" && ok "actions" || bad "워크플로 액션 버전 검증 실패"

if [ "$FAST" != "1" ] && command -v uv >/dev/null 2>&1; then
  step "Pytest"
  ( cd "$APP" && uv run pytest -q ) && ok "pytest" || bad "pytest 실패"
fi

echo
if [ "$fail" -ne 0 ]; then
  printf '\033[0;31m프리플라이트 실패 — 위 오류를 고친 뒤 다시 푸시하세요. (긴급 시: git push --no-verify)\033[0m\n'
  exit 1
fi
printf '\033[0;32m프리플라이트 통과 ✅\033[0m\n'
