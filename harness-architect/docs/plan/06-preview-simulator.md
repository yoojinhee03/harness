# Phase 6 — 실행 전 프리뷰 / 시뮬레이터

> 설계: 훅 실행 모델 + 화면 기획(생성 D 다음 단계). 지금 `POST /run` 에 `dry_run` 이 있지만
> 데이터일 뿐 표면이 없다. 이 Phase 는 "실행하면 무슨 일이 벌어지는지"를 **호출 없이** 눈으로
> 보게 만들어, 런타임에서야 터지던 문제(예산 초과·충돌·권한 누락)를 확정 전에 잡는다.

## 왜 (차별화)

기존 플러그인은 돌려봐야 안다. 여기선 정규화 IR + `build_request` 조립 결과를 그대로 분해해
보여주므로, 사용자가 "이 하네스가 실제로 어떤 요청을 만드는지"를 실행 전에 이해·신뢰한다.

## 목표

`harness.yaml`/`ResolvedHarness` → 조립 분해 뷰(실제 API 미호출):
- 최종 **시스템 프롬프트 골격**(어떤 context/skill 이 어떤 순서로 들어가는지)
- **툴 목록**(N개, 각 툴의 출처 컴포넌트·added_tools)
- **컨텍스트 토큰** 누계 vs 모델 예산(컴포넌트별 breakdown)
- **훅 파이프라인**(event별 정렬된 스텝 타임라인, blocking·sandbox·timeout 표기)
- **권한·auth 요구**(`permissions`, `auth_needs`)
- **경고**: 예산 초과 / `conflicts_with` / 미충족 권한 / deprecated 컴포넌트

## 작업

1. **`POST /preview`** — `ResolvedHarness` + `build_request` 산출을 구조화 JSON 으로 분해
   (프롬프트 섹션[], tools[], context_budget{총량·컴포넌트별}, hook_timeline{event→steps},
   auth[], permissions[]). **실제 Anthropic 호출 없음**(dry 분해만).
2. **경고 계산** — `cost.context_tokens` 누계 vs `ModelConfig` 예산; `conflicts_with`;
   미선언/미충족 권한; `status=deprecated`. resolver 진단(`diagnostics.py`)과 형식 통일.
3. **프론트 프리뷰 화면** — 생성 스파인의 D 다음(또는 옆 탭). 토큰 바(예산 대비), 훅 타임라인,
   툴 카드, 경고 배너. 확정(generate) 전에 프리뷰를 강제 노출.
4. **eject 미리보기 연계** — "이 하네스를 Claude Code 로 내보내면 이런 파일 트리" 프리뷰를
   Phase 5 `ClaudeCodeEmitter` 결과로 함께 표시(방출 뷰 공유).

## 완료 기준

- [ ] `POST /preview` — 조립 분해 JSON (무호출) + 테스트.
- [ ] 예산·충돌·권한·deprecated 경고 계산 + 테스트.
- [ ] 프론트 프리뷰 화면(토큰 바·훅 타임라인·툴 카드·경고).
- [ ] eject 파일 트리 프리뷰 연계(05 존재 시).
- [ ] **로컬 폴백·기존 테스트 회귀 불변**.

## 의존성

`build_request`(완료), `diagnostics`(완료). **Phase 5 와 "방출 뷰"를 공유**하므로 05 직후
또는 병행이 효율적(같은 IR 순회 로직 재사용).

## 검증 한계

분해·경고 로직은 pytest 로 완전 검증. "프롬프트 골격"은 실제 모델 토크나이저가 아니라 추정치
(`cost.context_tokens`) 기반 — 실측 토큰은 실호출(키) 시에만. 프리뷰는 근사임을 UI 에 명시.
