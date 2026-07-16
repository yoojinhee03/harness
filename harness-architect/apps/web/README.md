# harness-web

프론트엔드 — React + TypeScript + Vite + Tailwind + TanStack Query. 하네스 생성 여정
**A(설명) → B(추천·선택) → C(검증) → D(harness.yaml)** 를 구현한다. 되돌림 루프(C→B)가
일급 동작이고, 진단 색 체계(충족=초록·경고/gap=앰버·오류=빨강)를 전 화면에 일관 적용한다.

```bash
corepack pnpm install     # 또는 pnpm install
corepack pnpm dev         # http://localhost:5173  (백엔드 :8000 로 /api 프록시)
corepack pnpm build       # 타입체크 + 프로덕션 빌드
```

백엔드(`uv run uvicorn harness_api.main:app --reload`)가 :8000 에 떠 있어야 추천/검증/생성이
동작한다. `vite.config.ts` 의 프록시가 `/api/*` → `:8000` 으로 전달한다.

상단 네비로 **생성(A~D) · 카탈로그(E) · 대시보드(F)** 전환. E 는 컴포넌트 탐색·검색·필터·
상세, F 는 생성한 하네스 목록·재열기(localStorage). 화면 대응: `src/screens/ScreenA~F.tsx`,
API 계약: `src/api/client.ts`, 진단 색: `tailwind.config.js`.
