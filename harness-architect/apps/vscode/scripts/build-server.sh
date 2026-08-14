#!/usr/bin/env bash
# harness MCP 서버를 자립 실행파일(파이썬 인터프리터+의존성 포함)로 굽는다.
# 파이썬이 없는 사용자에게도 확장을 뿌릴 수 있게 한다. 현재 OS/아키텍처를 타깃으로 빌드한다
# (멀티플랫폼은 각 OS 러너에서 이 스크립트를 돌려 vsce package --target 으로 패키징).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VSCODE_DIR="$(dirname "$HERE")"                 # apps/vscode
ARCHITECT="$(cd "$VSCODE_DIR/../.." && pwd)"    # harness-architect
VENV="$ARCHITECT/.venv"
PY="$VENV/bin/python"
CATALOG_SNAPSHOT="$ARCHITECT/packages/catalog/src/harness_catalog/catalog-data/components"
OUT="$VSCODE_DIR/server"

if [ ! -x "$PY" ]; then
  echo "✗ venv 파이썬이 없습니다: $PY — 먼저 'cd $ARCHITECT && uv sync' 하세요." >&2
  exit 1
fi

echo "→ PyInstaller 준비"
if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PY" pyinstaller
  else
    "$PY" -m ensurepip --upgrade && "$PY" -m pip install --quiet pyinstaller
  fi
fi

BUILD_TMP="$(mktemp -d)"
trap 'rm -rf "$BUILD_TMP"' EXIT

echo "→ 서버 실행파일 빌드(onefile) — 현재 플랫폼"
# mcp 전체(--collect-all)를 긁으면 mcp.cli 가 optional typer 를 요구해 실패한다.
# 우리는 mcp.server 만 쓰므로 그 서브모듈만 수집하고 나머지는 임포트 그래프 분석에 맡긴다.
"$PY" -m PyInstaller \
  --onefile \
  --name harness-mcp \
  --collect-submodules mcp.server \
  --collect-submodules harness_mcp \
  --collect-submodules harness_catalog \
  --collect-submodules harness_resolver \
  --collect-submodules harness_runtime \
  --exclude-module typer \
  --exclude-module anthropic \
  --exclude-module voyageai \
  --distpath "$OUT/bin" \
  --workpath "$BUILD_TMP/build" \
  --specpath "$BUILD_TMP" \
  --noconfirm --clean --log-level WARN \
  "$HERE/server_entry.py"

echo "→ 카탈로그 스냅샷 동봉(외부 폴더로 — 확장이 CATALOG_DIR 로 가리킴)"
rm -rf "$OUT/catalog"
mkdir -p "$OUT/catalog"
cp "$CATALOG_SNAPSHOT"/*.yaml "$OUT/catalog/"

N_CAT="$(ls "$OUT/catalog"/*.yaml | wc -l | tr -d ' ')"
echo "✓ 완료 — $OUT/bin/harness-mcp · 카탈로그 ${N_CAT}개"
ls -lh "$OUT/bin/harness-mcp"
