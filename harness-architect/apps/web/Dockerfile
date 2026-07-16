# 프론트(React+Vite) — 정적 번들로 빌드한 뒤 nginx 로 서빙한다.
# 개발의 vite proxy(/api → :8000, 접두사 제거)와 동일한 계약을 nginx 로 재현하므로
# 브라우저는 웹 오리진 한 곳(:5173)만 보면 된다.

# ── 1) 빌드 스테이지 ──
FROM node:20-slim AS build
WORKDIR /app
RUN corepack enable

# 매니페스트 먼저 복사 → 의존성 레이어 캐시.
COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# ── 2) 런타임 스테이지 (nginx 정적 서빙 + /api 프록시) ──
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
