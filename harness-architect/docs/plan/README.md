# 진행 플랜 — 로드맵

설계·MVP 슬라이스는 완료됐다(리졸버 8단계·카탈로그/RAG 로컬 폴백·FastAPI·프론트 A~D).
이 문서는 남은 🚧 항목을 **README 로드맵 순서대로** 실행하기 위한 플랜이다. 각 Phase 는
독립 문서로 상세를 두고, 여기 체크박스로 상태를 추적한다.

## 완료 (기준선)

- [x] 카탈로그 시드 4컴포넌트 + 스키마
- [x] 리졸버 8단계 순수함수 파이프라인 + 테스트 14
- [x] 카탈로그/RAG 로컬 폴백 (추출→검색→랭킹)
- [x] FastAPI `/catalog · /recommend · /resolve · /generate`
- [x] 프론트 화면 A→B→C→D (빌드·프록시 관통)

## 남은 작업 (순서대로)

| # | Phase | 문서 | 상태 | 라이브 검증 |
|---|-------|------|------|------------|
| 1 | RAG 실연동 (Voyage 임베딩 + Claude 추출·랭킹) | [01-rag-integration.md](./01-rag-integration.md) | ✅ 완료 | 키 필요 |
| 2 | 런타임 실연동 (Anthropic 호출 + sandbox 격리) | [02-runtime-execution.md](./02-runtime-execution.md) | ✅ 완료 | 키 필요 |
| 3 | 프론트 화면 E(카탈로그) + F(대시보드) | [03-screens-e-f.md](./03-screens-e-f.md) | ✅ 완료 | 빌드/프록시 |
| 4 | 카탈로그 확장 (도메인 확대 + 둘째 시나리오) | [04-catalog-expansion.md](./04-catalog-expansion.md) | ✅ 완료 | 테스트 |

**전체 완료** — 4개 Phase 모두 구현·검증. 백엔드 pytest 47 통과 · ruff/mypy 클린 ·
프론트 `pnpm build` 통과. 실연동(Voyage/Claude/Anthropic) 실호출은 키 주입 시 자동 활성.

## 검증 원칙

- **키 없이도 도는 로컬 폴백은 절대 깨지 않는다** — 모든 Phase 에서 폴백 경로가 그대로
  통과해야 한다(회귀 테스트로 고정).
- Phase 1·2 의 실연동 코드는 키 없이 라이브 검증이 불가하므로, 클라이언트를 **주입 가능**하게
  만들고 fake/mock 로 코드 경로를 테스트한다(실제 네트워크 호출은 키 있을 때만).
- Phase 3·4 는 빌드·프록시·pytest 로 완전 검증한다.

## 진행 규칙

각 Phase 완료 시: 테스트/빌드 통과 확인 → 해당 문서의 완료 기준 체크 → 이 표의 상태를
✅ 로 갱신 → 다음 Phase.
