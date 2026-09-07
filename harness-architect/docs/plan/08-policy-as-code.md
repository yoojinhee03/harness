# Phase 8 — 정책 as code (조직 가드레일)

> 설계: 리졸버 검증 로직(순수 함수 파이프라인)의 확장. 개인이 하네스를 자유 조립하는 도구에서,
> **조직이 규칙을 선언하면 리졸버가 강제**하는 팀 표준화 도구로 격상한다.

## 왜 (차별화)

기존 플러그인엔 "우리 조직은 PII 훅 필수, 이 MCP 금지, 컨텍스트 예산 8k 상한" 같은 **거버넌스
레이어가 없다**. 리졸버가 이미 순수 함수 검증 파이프라인이라, 정책 단계를 하나 더 얹으면
저비용으로 상업적 차별화(팀/엔터프라이즈)를 만든다.

## 목표

`policy.yaml` 을 선언하면 `resolve()` 가 위반을 **gap 과 구분되는 `policy_violation`** 진단으로
차단한다. 정책은 harness.yaml 과 분리(조직 자산).

## 작업

1. **Policy 스키마** — `policy.yaml`: `require`(필수 capability/컴포넌트 id), `forbid`(금지
   id/capability), `budget`(context_tokens/added_tools 상한), `auth`(허용 scope 제약).
   스키마·로더는 카탈로그 스키마 규약(`schema/`)과 일관되게.
2. **리졸버 정책 단계** — 기존 8단계 뒤에 "정책 충족" 단계 추가(순수 함수 유지, 부작용 없음).
   위반은 `diagnostics.py` 에 `policy_violation`(위반 규칙·사유 포함)로. gap(미충족 requires)과
   **의미를 구분**한다 — gap 은 추천기로 되돌릴 신호, 정책 위반은 차단.
3. **API/CLI 수용** — `/resolve`·`/generate`(및 `harness resolve`)가 선택적 정책 컨텍스트를
   받는다. 위반 시 생성 차단 + 사유 리포트.
4. **정책 프리셋** — 예: `presets/security-baseline.yaml`(PII redact + secret scan 필수,
   미검증 외부 훅 금지). 조직이 바로 쓰거나 확장.

## 완료 기준

- [x] `policy.yaml` 스키마 + 로더 + 검증 — `harness_resolver/policy.py`.
      **별도 파일을 만들지 않았다**: `.harness/policy.yaml` 은 이미 verify 심각도 오버라이드
      (`severity:`)로 쓰이고 있어, 같은 파일에 거버넌스 섹션(`require`/`forbid`/`budget`/`auth`)을
      나눠 담는다. `policy_from_document()` 는 거버넌스 키가 없으면 None 을 돌려주므로 severity 만
      있던 기존 레포는 정책 미지정으로 읽힌다(하위호환).
- [x] 리졸버 정책 단계(순수, 11단계) + `policy_violation` 진단 + 테스트 24건.
      severity 는 기존 `error` 를 재사용하고 `code="policy_violation"` + `detail["rule"]` 로 구분한다 —
      새 severity 를 만들면 프론트·CLI 의 기존 분기가 전부 깨진다.
- [x] `/resolve`·`/generate` **및 `/run`·`/eject`·`/preview`** 정책 수용 + 차단 리포트.
      문서는 앞 둘만 적었지만 그러면 구멍이 난다 — 같은 본문(`ResolveRequest`)을 쓰는 경로가
      정책을 무시하면 우회 가능하다. `harness resolve/eject/preview --policy` 도 같은 이유로 함께.
- [x] `security-baseline` 프리셋(`harness-catalog/policies/security-baseline.yaml`) + 적용 테스트.
- [x] **정책 미지정 시 기존 리졸버 동작 완전 불변** — `resolve()` 의 세 번째 인자는 기본 None 이고,
      None·빈 정책 모두 진단이 한 줄도 늘지 않음을 테스트로 고정(378 전체 통과, 회귀 0).

## 구현 노트 (2026-09-07)

- **같은 수치라도 누가 정했느냐로 강도가 갈린다.** harness 자신의 `budget` 초과는 warning(작성자가
  스스로 정한 목표)이고, 정책 상한 초과는 차단(조직이 정한 선)이다. 테스트로 이 대비를 고정했다.
- **`forbid.unsandboxed_hooks`** — 훅은 라이프사이클 시점에 임의 로직을 실행하므로 공급망 위험이
  가장 크다. 공유 카탈로그의 sandbox=none 승격 차단 게이트와 같은 근거를 조직 정책에서도 쓴다.
- **패턴은 정확 일치 + 접두 glob 만.** 정규식을 넣지 않았다 — 정책은 읽고 감사할 수 있어야 한다.
  연합 레지스트리 네임스페이스 차단(`io.github.randomdev/*`)이 실사용 동기다.
- **미지 키는 거부한다**(`extra="forbid"`). 오타를 조용히 삼키면 "정책을 걸었다고 믿는데 안 걸린"
  최악의 실패가 된다. API 는 422 로 떨어진다.
- 프리셋을 시드 pr-bot 하네스에 걸면 실제로 두 건을 잡는다 — `lifecycle.transform` 미충족과
  `slack-mcp` 의 미축소 권한(프리뷰가 "인증 미충족"으로 표시하던 바로 그것).

## 후속 — 스코프 정책 영속 (2026-09-07)

초기 구현은 정책을 **요청 본문에서만** 받았다. CI(`harness resolve --policy`)는 운영자가 직접
주니 맞지만, 제품 안에서는 **클라이언트가 그냥 안 보내면 아무 강제도 없었다** — 조직이 멤버를
묶을 수 없으니 사실상 정책이 없는 것과 같았다. 그 절반을 채웠다.

- `scope_policies` 테이블 + `PolicyStore` + alembic `b8c9d0e1f2a3`. grain = 스코프 키
  (`personal:<uid>` | `team:<tid>`).
- `GET/PUT/DELETE /policies?scope=` — **팀은 owner 만** 변경. `_resolve_scope(write=True)` 는
  owner/editor 를 통과시키는데 정책은 그보다 좁아야 한다(editor 가 가드레일을 풀 수 있으면
  가드레일이 아니다).
- 저장된 정책을 **서버가 항상 적용**한다: `/resolve`·`/generate`·`/run`·`/eject`·`/preview`·
  `/eval` + 저장본 경로(`/harnesses/{id}/validate·preview·eject·eval`). 스코프는 쿼리 파라미터.
- 요청 본문 정책과는 `harness_resolver.strictest` 로 **엄격한 쪽으로** 합친다:
  require/forbid 합집합 · budget 최소값 · allowed_scopes 교집합 · 불리언 OR.
  즉 **저장된 정책은 클라이언트가 낮출 수 없는 하한**이고, 클라이언트는 더 엄격해질 수만 있다.
- 웹 UI — 워크스페이스 정책 편집기(`components/PolicyEditor.tsx`). owner 아니면 읽기 전용으로
  표시하고 이유를 밝힌다(서버가 403 으로 최종 판정).

### 판단

- **정책 조회 실패는 삼키지 않는다.** GapDemand·Cooccurrence 는 비차단이지만(신호를 놓쳐도
  기능은 돈다), 정책은 "못 읽었으니 없음"으로 넘기면 가드레일이 조용히 사라진다 — 그건 사고다.
- **`doctor` 에는 정책을 적용하지 않는다.** 버전 드리프트 진단은 정책과 무관한 축이고, 정책
  위반으로 진단 자체가 막히면 "왜 막혔는지"를 볼 수단이 사라진다.
- **정책 미저장 시 동작 완전 불변** — 저장이 없으면 `strictest(None, body)` = 본문 그대로다.

## 의존성

리졸버 파이프라인(완료). **Phase 5 와 독립** — 아무 때나 병행 착수 가능(P1, 상업 가치 높음).

## 검증 한계

정책 강제는 resolve 시점의 정적 검증이다. 런타임에서 훅이 실제로 정책대로 동작하는지(예:
PII 훅이 실제 마스킹)는 Phase 2 런타임 실행기 영역이며, 여기선 "선언 강제"까지만 책임진다.
