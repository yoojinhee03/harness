# Phase 3 — 프론트 화면 E(카탈로그) + F(대시보드)

> 설계: 화면 기획 E·F. 핵심 스파인 A~D 는 완료. 보조 화면 E(탐색·신규 저작 유도)와
> F(하네스 목록·재열기 허브)를 붙여 여정을 완성한다.

## 목표

- **E 카탈로그**: 컴포넌트 탐색·검색·facet/capability 필터·상세(provides/requires·cost·auth·
  config 스키마). 콜드스타트·gap 대응 진입점. B/C 의 gap 안내에서 진입 가능.
- **F 대시보드**: 하네스 목록(로컬 저장)·상태·재열기·"새 하네스 만들기". 진입 허브.

## 작업

1. **API 활용** — 이미 있는 `GET /catalog`, `GET /catalog/{id}` 사용. 필요 시 facet 필터는
   프론트에서 `capability_tags` 로 처리(백엔드 확장 불필요).
2. **E 화면** — 검색창 + 타입/capability 필터 칩 + 컴포넌트 카드 그리드 + 상세 드로어.
3. **F 화면** — 생성한 하네스를 `localStorage` 에 저장(id·이름·컴포넌트·생성시각), 카드 목록,
   클릭 시 D 로 재열기, "새로 만들기" → A.
4. **네비게이션** — 상단에 스파인(A~D) 외 보조 탭(E/F) 추가. 라우팅은 경량 상태 기반.
5. **되돌림 연결** — C 의 gap "구성요소 추천" → B, B 의 콜드스타트 → E 진입 경로 연결.

## 완료 기준

- [x] E: 카탈로그 목록·검색·타입/capability 필터·상세 드로어(config_schema 포함).
- [x] F: 하네스 저장/목록/재열기 동작(localStorage) — 생성 성공 시 자동 저장.
- [x] 보조 탭(생성/카탈로그/대시보드) 네비게이션 + 콜드스타트(E→새 생성) 경로.
- [x] `pnpm build`(tsc + vite) 통과, `/catalog`·`/catalog/{id}` 라이브 관통.

**구현 노트:** `lib/store.ts`(localStorage) · `screens/ScreenE.tsx`(검색·필터·상세) ·
`screens/ScreenF.tsx`(대시보드). App 에 view 네비 추가, ScreenD 가 생성 성공 시 `onSaved` 로
대시보드에 저장, F 의 "열기"가 선택을 복원해 D 로 재진입.

## 검증

`corepack pnpm build` 성공 + 백엔드 띄우고 dev 서버에서 E 가 실제 카탈로그를 렌더하는지 관통.
