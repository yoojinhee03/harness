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

**v1 전체 완료** — 4개 Phase 모두 구현·검증. 백엔드 pytest 98 통과 · ruff/mypy(전체 소스) 클린 ·
프론트 `pnpm build` 통과. 실연동(Voyage/Claude/Anthropic) 실호출은 키 주입 시 자동 활성.

---

## v2 — 차별화 로드맵 (소스 오브 트루스 + 컴파일러)

> v1 은 "설명 → 추천 → 검증 → harness.yaml" 을 관통시켰다. 하지만 산출물이 *자기 포맷*
> (harness.yaml)에서 멈추면 "또 하나의 플러그인 포맷" 위험이 있다. v2 의 논지:
>
> **harness.yaml 을 실행 포맷이 아니라 소스 오브 트루스로 두고, 이미 가진 정규화 IR
> (`ResolvedHarness`)을 아무 에이전트 런타임으로나 컴파일한다.**
>
> 이건 기존 하네스 플러그인(Claude Code·Cursor·Cline·Continue)의 공통 한계 4개를 정면으로
> 뒤집는다 — 수동 조립(→ 그라운딩 추천), 런타임에서야 터짐(→ 실행 전 검증·프리뷰),
> 포맷 락인(→ 다중 런타임 컴파일·역임포트), 학습 없음(→ 피드백 루프). 앞 둘은 v1 에서 이미
> 확보했고, v2 는 **포맷 락인 탈피(이식성)** 와 **팀 거버넌스·학습**을 얹는다.

| # | Phase | 문서 | 우선순위 | 의존성 | 상태 |
|---|-------|------|---------|--------|------|
| 5 | 다중 런타임 컴파일 (`eject`, Claude Code 먼저) + CLI | [05-multi-runtime-compile.md](./05-multi-runtime-compile.md) | **P0 (플래그십)** | 없음 — `ResolvedHarness` IR 완료 | ✅ 완료 (Claude Code) |
| 6 | 실행 전 프리뷰 / 시뮬레이터 | [06-preview-simulator.md](./06-preview-simulator.md) | P0 | `build_request`(완료), 05 와 방출 뷰 공유 | 📋 계획 |
| 7 | 역방향 임포트 (`adopt`) + gap 분석 | [07-reverse-adopt.md](./07-reverse-adopt.md) | P1 | 05 (포맷 매핑의 역) | 📋 계획 |
| 8 | 정책 as code (조직 가드레일) | [08-policy-as-code.md](./08-policy-as-code.md) | P1 (상업 차별화) | resolver(완료) — 독립 | 📋 계획 |
| 9 | 피드백 루프 활성화 & 카탈로그 생애주기 | [09-feedback-and-catalog-lifecycle.md](./09-feedback-and-catalog-lifecycle.md) | P2 | 05 (실사용 신호) | 📋 계획 |
| 10 | 프롬프트 관리 (합성·변수·버전·린트) | [10-prompt-management.md](./10-prompt-management.md) | **P0 (05·06 토대)** | IR/resolver/cost(완료) — 05·06 강화 | ✅ 완료 (코어) |
| 11 | 경험적 검증 (프롬프트 eval → 품질 측정) | [11-empirical-validation.md](./11-empirical-validation.md) | P1 (신뢰도) | 10(완료) · 09 와 연동 | 📋 계획 |
| 12 | 프로덕션 하드닝 (MVP→실서비스: 보안·데이터·스케일·배포) | [12-production-hardening.md](./12-production-hardening.md) | **P0 (실서비스 잠금)** | 멀티테넌시(완료) 위 | 📋 계획 (12a~12d) |

> **참고** — 12 는 기능이 아니라 **횡단 하드닝 트랙**이다. 웹↔확장 동기화 + 멀티테넌시(Bearer 인증·
> 사용자 격리·팀 공유)는 구현됨. 12 는 그 위에서 다중 사용자 실서비스를 막는 잔여 과제(API 키
> 스코프·CORS·SSE 스케일아웃·저장소 DB화·배포 CI/CD·관측성)를 12a~12d 로 실행한다.

**의존성 그래프**

```
10 (프롬프트를 IR 에 명시)  ── 05·06 의 emit/preview 대상에 실체 부여 · 08 과 연동
      └ 05/06 직전·병행 권장
05 (eject: IR→네이티브)  ─┬─▶ 06 (프리뷰; 방출 뷰 공유)
   └ 즉시 착수 가능        ├─▶ 07 (adopt; 포맷 매핑의 역)
                          └─▶ 09 (피드백; eject 실사용 신호)
08 (정책; resolver 단계 추가) ── 독립, 아무 때나 병행 가능
```

**추천 착수 순서**: `10 → 05 → (06 병행) → 07 · 08 병행 → 09`. 10 을 앞에 두는 이유 —
05(eject)·06(프리뷰)가 다루는 "시스템 프롬프트"를 1급 아티팩트로 명시화하는 토대라, 먼저
깔면 05/06 이 방출·표시할 실체가 생긴다. 05 를 그 다음 두는 이유 — IR 이 이미 있어 저비용이고,
"설명→검증"에서 멈추던 데모가 **"→ 진짜 `.claude/` 가 생성돼 실행"**까지 완결되며 이식성이라는
차별화 서사를 초반에 증명한다.

> **현재 위치** — `10`·`05` 완료(프롬프트 코어 + Claude Code eject 관통). 다음 후보:
> `06`(프리뷰) · `07·08` 병행 · 신뢰도용 `11`(경험적 검증). `05` 는 Cursor/Cline/Raw API
> Emitter 로 이식 폭을 넓힌다.

## 검증 원칙

- **키 없이도 도는 로컬 폴백은 절대 깨지 않는다** — 모든 Phase 에서 폴백 경로가 그대로
  통과해야 한다(회귀 테스트로 고정).
- Phase 1·2 의 실연동 코드는 키 없이 라이브 검증이 불가하므로, 클라이언트를 **주입 가능**하게
  만들고 fake/mock 로 코드 경로를 테스트한다(실제 네트워크 호출은 키 있을 때만).
- Phase 3·4 는 빌드·프록시·pytest 로 완전 검증한다.

## 진행 규칙

각 Phase 완료 시: 테스트/빌드 통과 확인 → 해당 문서의 완료 기준 체크 → 이 표의 상태를
✅ 로 갱신 → 다음 Phase.
