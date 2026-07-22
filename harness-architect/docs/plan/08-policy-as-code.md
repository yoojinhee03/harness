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

- [ ] `policy.yaml` 스키마 + 로더 + 검증.
- [ ] 리졸버 정책 단계(순수) + `policy_violation` 진단 + 테스트(require/forbid/budget/auth).
- [ ] `/resolve`·`/generate` 정책 수용 + 위반 차단 리포트.
- [ ] `security-baseline` 프리셋 + 적용 테스트.
- [ ] **정책 미지정 시 기존 리졸버 동작 완전 불변**(회귀 테스트) · 로컬 폴백 불변.

## 의존성

리졸버 파이프라인(완료). **Phase 5 와 독립** — 아무 때나 병행 착수 가능(P1, 상업 가치 높음).

## 검증 한계

정책 강제는 resolve 시점의 정적 검증이다. 런타임에서 훅이 실제로 정책대로 동작하는지(예:
PII 훅이 실제 마스킹)는 Phase 2 런타임 실행기 영역이며, 여기선 "선언 강제"까지만 책임진다.
