# Phase 12 — 프로덕션 하드닝 (MVP → 실서비스)

> 설계 근거: 전체 시스템 프로덕션 준비도 검토(2026-08-12). MVP·VSCode 확장·웹↔확장 동기화·
> **멀티테넌시(Bearer 인증·사용자 격리·팀 공유)** 까지 구현된 상태에서, "실제 서비스 배포"를
> 막는 잔여 과제를 설계한다. 이 문서는 여러 하위 Phase(12a~12d)로 쪼개 실행한다.

## 배경 — 지금 어디까지 왔나

**구현됨**: 카탈로그 그라운딩 추천 → resolve → eject(claude-code·cursor) 파이프라인, 순수함수
코어(resolver·catalog·runtime), FastAPI·React 웹·VSCode 네이티브 확장(+번들 서버), 웹↔확장
공유 저장소 + SSE 동기화, **Bearer 토큰 인증 + 사용자별 격리 + 자가서브 팀 공유**.

**아직 MVP 자세인 부분**(이 문서의 대상): 아래 표. 우선순위는 P0(다중 사용자 실서비스 잠금) →
P1(신뢰성·규모) → P2(운영 성숙도).

| # | 영역 | 현재 | 목표 | P |
|---|------|------|------|---|
| 1 | 인증 하드닝 | Bearer 토큰(격리 O) | register 레이트리밋·토큰 폐기/회전·역할(RBAC)·TLS | P0 |
| 2 | API 키 스코프 | `os.environ` 전역 변조(사용자 간 누수) | 요청/사용자 스코프 주입(암호화 저장) | P0 |
| 3 | CORS | 기본 `*` | env allowlist·프로덕션 deny | P0 |
| 4 | SSE 스케일아웃 | 인프로세스 브로드캐스터(단일 프로세스 전용) | Redis pub/sub — 워커·레플리카 다중화 | P0/P1 |
| 5 | 저장소 | 평면 JSON 파일 | Postgres + 마이그레이션·낙관적 잠금·페이징·백업 | P1 |
| 6 | 배포/CI·CD | lint/type/test만 | 이미지 빌드·스캔·배포·워커·레이트리밋·e2e | P1 |
| 7 | 관측성 | 기본 로깅·선택 OTel | 구조적 로깅·요청ID·메트릭·Sentry·probe | P2 |
| 8 | 프론트/확장 | 에러바운더리·CSP·마켓 준비 없음 | web 견고화·확장 마켓플레이스화 | P2 |
| 9 | LLM 회복력 | SDK 기본 | 타임아웃·백오프·사용자별 비용 가드 | P2 |

---

## Phase 12a — 보안 잠금 (P0)

> 다중 사용자에게 열기 전 반드시. 국소적이라 먼저 친다.

### 목표
사용자 간 데이터·자격 누수 0, 오리진·전송 보안.

### 작업
1. **API 키 요청 스코프화** — 지금 `_apply_keys` 가 `os.environ` 를 전역 변조하고 단일 공유
   `Recommender` 를 재생성해, A 의 키가 B 요청에 샌다. 설계:
   - 키를 사용자별로 저장(암호화 at-rest; `AccountStore` 에 `keys` 필드 또는 별도 KeyStore).
   - `Recommender`/`Reasoner`/`Embedder` 를 **요청 시점에 그 사용자 키로 구성**(전역 env 금지).
     핫패스면 사용자별 LRU 캐시. 키 없으면 로컬 폴백(현행 유지).
2. **CORS 고정** — `HARNESS_CORS_ORIGINS` 기본을 `*` → 빈 값(=거부), 배포는 명시 오리진만.
3. **register 레이트리밋 + 남용 방지** — `slowapi`(IP 기준) 로 `/auth/register`·`/recommend`·
   `/run` 제한. 계정 스팸·비용 유발 차단.
4. **토큰 수명주기** — 폐기(`DELETE /auth/token`)·회전, 만료(TTL) 옵션. 해시는 이미 sha256 —
   토큰 프리픽스 인덱스로 조회 O(1) 화(선형 스캔 제거).
5. **TLS·헤더** — 리버스 프록시 TLS 종단, `Strict-Transport-Security`·보안 헤더. 토큰은 URL 로그에
   남지 않게(SSE `?token=` 는 프록시 액세스로그 마스킹 또는 짧은 수명 SSE 티켓으로 교체 검토).

### 완료 기준
- [ ] 키가 전역 env 를 건드리지 않고 사용자별로만 적용됨(교차 누수 테스트).
- [ ] CORS 기본 거부, 배포 오리진 화이트리스트 문서화.
- [ ] register/recommend 레이트리밋 동작(테스트).
- [ ] 토큰 폐기·회전 엔드포인트 + O(1) 조회.

---

## Phase 12b — 데이터·스케일 (P0/P1)

> 멀티테넌시가 붙은 이상 파일 저장소·인프로세스 SSE 는 한계. 여기서 스케일 경계를 넘는다.

### 목표
영속·동시성 안전·수평 확장 가능한 저장소와 실시간 채널.

### 작업
1. **저장소 Postgres 화** — 지금 스코프별 JSON 파일(동시성 잠금 없음, 이력·백업 없음). 스키마:
   `users(id, handle, token_sha, created_at)`, `teams(id, name, owner_id)`,
   `team_members(team_id, user_id, role)`, `harnesses(id, scope, owner_id, name, description,
   yaml, version, updated_at, PRIMARY KEY(scope, id))`. 마이그레이션은 Alembic.
   - **낙관적 잠금**: `version`/`updated_at` 로 If-Match, 충돌 시 409.
   - **페이지네이션**: `GET /harnesses` 커서 기반.
   - 파일 저장소는 인터페이스 뒤에 두고(현행 `HarnessStore` 계약 유지) 어댑터 교체.
2. **SSE 스케일아웃 — Redis pub/sub** — 인프로세스 `Broadcaster` 는 워커 2개↑에서 이벤트가
   교차 전달 안 됨. 설계: 변경 시 `redis.publish("harness-events", {scope,...})`, 각 인스턴스는
   구독해 자기 로컬 SSE 구독자에게 **가시 스코프 필터** 후 전달. `Broadcaster` 인터페이스는 유지,
   구현만 in-memory ↔ Redis 스왑. 단일 인스턴스 개발은 in-memory 폴백.
3. **벡터 인덱스** — 카탈로그가 커지면 인메모리 코사인 → pgvector(compose 에 이미 프로파일 존재).
   콜드스타트 비용·영속 확보.

### 완료 기준
- [ ] Postgres 어댑터로 CRUD·격리·팀 공유 테스트가 그대로 통과(계약 불변).
- [ ] 낙관적 잠금(409)·페이징 동작.
- [ ] uvicorn 워커 2개↑에서 SSE 가 교차 전달됨(Redis) — 스케일아웃 e2e.
- [ ] Alembic 마이그레이션 + 백업 문서.

---

## Phase 12c — 배포·CI/CD (P1)

### 목표
재현 가능·자동화된 배포와 게이트.

### 작업
1. **런타임** — SSE 스케일아웃(12b) 후 gunicorn+uvicorn 워커 다중화, 리소스 리밋·재시작 정책,
   요청 크기 상한, `slowapi` 레이트리밋(12a 와 통합).
2. **CI 확장** — 현재 lint/type/test(push=main 만) → (a) 트리거를 PR·모든 브랜치로, (b) 도커
   이미지 빌드·`trivy` 스캔·레지스트리 푸시, (c) docker compose 스모크 + SSE 실HTTP e2e,
   (d) `dependabot`/`pip-audit`·`npm audit`.
3. **배포 파이프라인** — 태그→이미지→배포(환경별). 시크릿은 시크릿 매니저(env·인메모리 키 제거).

### 완료 기준
- [ ] PR 마다 lint/type/test/e2e/스캔 게이트.
- [ ] 이미지 빌드·스캔·푸시 자동화.
- [ ] 워커 다중화 + 레이트리밋 프로덕션 설정.

---

## Phase 12d — 관측성·프론트·확장 (P2)

### 목표
운영 가시성과 사용자 대면 성숙도.

### 작업
1. **관측성** — 구조적 로깅(JSON)+요청 ID 미들웨어, Prometheus 메트릭(`/metrics`), Sentry 에러
   트래킹, OTel 트레이싱 상시화, `/health`·`/ready` 분리 probe.
2. **웹 견고화** — 에러 바운더리(렌더 throw 백지 방지), 로딩/빈/에러 상태 표준화, nginx CSP·보안
   헤더, 토큰 저장 방식 재검토(localStorage XSS 노출 vs httpOnly 쿠키 — CSRF 트레이드오프).
3. **확장 마켓플레이스화** — 실 publisher 등록, 갤러리 아이콘(128px PNG), 멀티플랫폼 서버 바이너리
   CI 매트릭스(darwin/linux/win × arch) + `vsce publish --target`, 텔레메트리 동의.
4. **LLM 회복력** — anthropic/voyage 호출 타임아웃·지수백오프 재시도, 사용자별 비용/쿼터 가드.
5. **API 계약** — `/v1` 버저닝, OpenAPI 계약 테스트, 입력 상한(하네스 크기·설명 길이).

### 완료 기준
- [ ] 구조적 로깅+요청ID, 메트릭·Sentry 연동.
- [ ] web 에러 바운더리·CSP.
- [ ] 확장 멀티플랫폼 vsix 배포 파이프라인.

---

## 실행 순서(권장)

**12a(보안 잠금) → 12b(데이터·SSE 스케일) → 12c(배포·CI) → 12d(관측·프론트·확장)**.
12a·12b 가 "다중 사용자 실서비스"의 핵심 잠금이고, 12c 는 안전한 반복 배포, 12d 는 운영 성숙도다.
각 하위 Phase 는 독립 배포 가능하도록 인터페이스 경계(저장소·브로드캐스터·키 주입)를 유지한다.

## 스코프 아웃(의식적 제외)

- 완전한 조직/SSO·감사로그·SOC2 류 컴플라이언스(수요 확인 후).
- 팀 역할(owner/editor/viewer)은 12a 에 훅만 두고 실제 권한 분리는 후속.
- 결제·요금제(비용 가드는 12d 에 최소만).
