# 백엔드(FastAPI) 이미지 — uv 워크스페이스를 그대로 빌드한다.
# 카탈로그 *데이터*(harness-catalog/components)는 이미지에 넣지 않고 런타임에
# CATALOG_DIR 로 읽기전용 마운트한다(루트 docker-compose.yml 참고). 코드↔자산 분리 유지.
FROM python:3.14-slim AS base

# uv 바이너리 — astral 공식 이미지에서 복사(로컬과 동일한 0.11 라인).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

WORKDIR /app

# 도커 레이어 캐시와 궁합: 바이트코드 컴파일 + 복사 링크 + 파이썬 자동 다운로드 끔.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1

# ── 1) 의존성 레이어: 워크스페이스 매니페스트만 먼저 복사해 *외부* 의존성만 설치 ──
#    소스가 바뀌어도 이 레이어는 캐시되어 재설치를 피한다.
COPY pyproject.toml uv.lock ./
COPY packages/resolver/pyproject.toml packages/resolver/pyproject.toml
COPY packages/catalog/pyproject.toml packages/catalog/pyproject.toml
COPY packages/runtime/pyproject.toml packages/runtime/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --no-dev --no-install-workspace

# ── 2) 소스 레이어: 실제 코드 복사 후 워크스페이스 패키지까지 설치 ──
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --no-dev

# venv 를 PATH 앞에 둬서 uvicorn 을 바로 실행.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "harness_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
