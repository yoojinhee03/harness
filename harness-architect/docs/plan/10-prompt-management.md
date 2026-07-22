# Phase 10 — 프롬프트 관리 (Prompt Composition & Lifecycle)

> 설계: 하네스 스코프(`model`·`permissions`에 이어 프롬프트를 최상위 관리 대상으로) + 훅 실행
> 모델(build_request 조립). 지금 시스템 프롬프트는 `context`/`skill` 컴포넌트에서 **암묵적으로
> emergent 하게** 조립될 뿐, harness.yaml 에도 `ResolvedHarness` IR 에도 명시돼 있지 않다.
> 이 Phase 는 프롬프트를 **명시적·버전·검증 가능한 1급 아티팩트**로 승격한다.

## 왜 (차별화)

기존 프롬프트옵스 툴(LangSmith·PromptLayer·Langfuse·Humanloop)은 프롬프트를 **앱에서 분리된
문자열**로 버전·평가한다. 여기선 프롬프트가 **하네스 구성의 일부** — 같은 RAG 추천으로 조각을
찾고, 리졸버가 예산·충돌·변수를 진단하고, 프리뷰(06)로 보고, eject(05)로 이식하고, doctor(09)로
드리프트를 잡는다. **단일 소스 오브 트루스에서 일관성이 보장**되는 게 standalone 툴과의 차이다.
또한 이 Phase 는 05·06 이 emit/preview 하는 "프롬프트"에 실체를 줘 그 둘을 완성시킨다.

## 목표

`harness.yaml` 에 `prompt` 블록, 리졸버에 **프롬프트 합성 단계**, IR 에 `ResolvedHarness.prompt`
(합성 텍스트 + provenance + 변수 바인딩 + 경고 + 해시)가 관통한다. `build_request` 는 암묵 조립
대신 이 합성 결과를 쓴다.

### harness.yaml `prompt` 블록 (제안 형태)

```yaml
prompt:
  # 시스템 프롬프트를 레이어로 선언 — 순서 = 합성 우선순위(위 → 아래).
  system:
    - ref: prompt/role-senior-reviewer@1.2.0   # 카탈로그 조각 참조(버전 핀)
    - ref: prompt/format-structured-review@1.0.0
    - inline: |                                 # 인라인 조각
        프로젝트: {{project_name}}. 컨벤션은 {{convention}} 를 따른다.
  variables:
    project_name: { type: string, required: true }
    convention:   { type: string, default: "google-style" }
  compose:
    dedup: true            # 동일 조각 중복 제거
    on_conflict: warn      # warn | error | last-wins
    budget_tokens: 4000    # 초과 시 진단(cost 모델과 연동)
```

### `ResolvedHarness.prompt` (IR 출력)

```
prompt:
  system_text:  "<합성된 최종 시스템 프롬프트>"
  segments:                                  # provenance — 누가 뭘 기여했나
    - source: "prompt/role-senior-reviewer@1.2.0"  layer: 0  tokens: 320
    - source: "component:coding-convention-ctx"    layer: 2  tokens: 210
  variables_resolved: { project_name: "harness", convention: "google-style" }
  warnings: [ "budget: 4200/4000 초과", ... ]
  hash: "sha256:…"                           # 드리프트·캐시·버전 키
```

## 작업

1. **`prompt` 블록 스키마 + `HarnessConfig` 확장** — `harness_resolver.models` 에 `PromptSpec`
   (system 레이어[`ref` | `inline`], variables[type/default/required], compose[dedup/on_conflict/
   budget_tokens]). 로더·검증.
2. **프롬프트 조각 카탈로그화 (새 타입 없이)** — 4개 타입 스코프를 지키기 위해 조각은 `context`
   컴포넌트의 **facet** 으로 큐레이션한다: `capability_tags: [prompt.role]` / `[prompt.format]` /
   `[prompt.safety]`, `refresh: static`. 기존 `Recommender` 가 그대로 발견 — "이 프로젝트엔 이런
   시스템 프롬프트가 어울린다"가 추천으로 나온다.
3. **리졸버 프롬프트 합성 단계** — 8단계 뒤(또는 병합 단계 인접)에 순수 함수 단계 추가:
   레이어 순서 병합 → 변수 치환·검증(미해결 변수는 gap 과 유사한 진단) → dedup → 충돌/예산
   진단 → provenance·hash 기록. `diagnostics.py` 어휘 재사용(`prompt_warning`).
4. **`build_request` 연결** — 암묵 조립 대신 `ResolvedHarness.prompt.system_text` 사용.
   **기존 조립 결과와 동치**임을 회귀 테스트로 고정(리팩터링이지 동작 변경 아님).
5. **프롬프트 린트** — 예산 초과 · 미해결 변수 · 중복/빈 조각 · 상충 지시(휴리스틱) · 언어 혼용
   경고. resolver 진단으로 표면화(프리뷰·CLI 에서 노출).
6. **버전·핀·드리프트** — 조각은 semver 로 핀(`@1.2.0`). Phase 9 `doctor` 가 컴포넌트뿐 아니라
   **프롬프트 조각 버전/deprecated diff** 도 검사·업그레이드 제안.
7. **프리뷰/이식 연계** — Phase 6 프리뷰가 `segments`(조각별 토큰 provenance)와 두 구성/버전
   간 **프롬프트 diff** 를 렌더. Phase 5 eject 가 `system_text` 를 각 런타임 프롬프트 표면
   (Claude Code `CLAUDE.md`·system, Cursor rules, raw API `system`)으로 방출.

## 완료 기준

- [x] `prompt` 블록 스키마 + `HarnessConfig`(`PromptSpec`) 확장 + 로더/검증
      (`PromptLayer` ref/inline 배타 검증 포함).
- [ ] `context` 프롬프트 facet 큐레이션(role/format/safety) + RAG 추천 발견 테스트.
      → **다음 증분** (카탈로그 자산에 실제 조각 YAML 추가 + 개수 단언 4곳 갱신).
- [x] 리졸버 프롬프트 합성 단계(병합·변수·dedup·예산·provenance·hash) + 테스트
      (미해결 변수 · 예산 초과 · 충돌(warn/error/last_wins) · dedup · ref/미지 조각).
- [x] `build_request` 가 합성 프롬프트 사용 + **기존 조립 결과 동치** 회귀 테스트.
- [x] 프롬프트 린트 진단(예산·변수·중복·미지/빈/deprecated 조각) + 테스트.
      *(상충 지시 휴리스틱·언어 혼용은 후속 — 현재는 중복/예산/변수 위주.)*
- [ ] Phase 6 프리뷰 provenance/diff · Phase 5 eject 프롬프트 방출 연계(각 Phase 착수 시).
- [x] **로컬 폴백·기존 테스트 회귀 불변** — 전체 pytest 60 통과(기존 47 포함) · ruff/mypy 클린.

**구현 노트 (코어 완료):** `models.py`(`PromptSpec`/`PromptLayer`/`PromptVariable`/`PromptCompose`
+ `ResolvedPrompt`/`PromptSegment`, `Component.body`) · `prompt.py`(`compose_prompt`·`estimate_tokens`)
신설. `resolver.py` 9번째 단계로 합성 호출(`ResolvedHarness.prompt` 채움), `merge.py` 가 `extends`
로 prompt 전달. `builder.py` 는 `resolved.prompt.system_text` 사용, 없으면 폴백(동치 보장 — 두
포맷 문자열은 주석으로 상호 참조). 카탈로그 스키마에 `body` 추가. 검증: `test_prompt.py`(11) +
runtime 동치 2 + 실 리졸버 데모(provenance·해시·변수·예산 확인).

## 의존성

`HarnessConfig`/`ResolvedHarness`(완료) · 리졸버 파이프라인(완료) · cost 모델(완료). **Phase 5·6
을 강화**(그들이 emit/preview 하는 프롬프트를 명시화)하므로 **05/06 직전 또는 병행 권장** — 토대
성격이라 P0. Phase 8(정책)과 연동: 정책이 필수 preamble·금지 문구를 프롬프트에 강제할 수 있다.
독립 착수도 가능하나 05/06 과 묶으면 시너지가 가장 크다.

## 검증 한계

"상충 지시 감지"는 휴리스틱이라 완벽하지 않다(명백한 중복·부정 충돌 위주). 토큰은 실측이 아닌
추정(`cost.context_tokens`) — 실측은 실호출(키) 시에만.

**이중 주입 주의**: 한 조각을 `prompt.system[].ref` 로 참조하면서 동시에 `components[]` 에도
넣으면 내용이 두 번 들어간다(authored body 텍스트 + 컴포넌트 `## 컨텍스트:` 조립본은 텍스트가
달라 정확-텍스트 dedup 으로 걸러지지 않음). 현재는 둘 중 하나로만 쓰는 걸 전제한다 — 의미 기반
중복 감지는 후속.

## 이 Phase 밖 (후속 후보)

**프롬프트 eval** — 조각/구성에 eval 케이스(입력 → 기대 속성)를 첨부해 dry/live 실행하고, 결과를
Phase 9 피드백 루프(조각 retention 신호)로 되먹이는 프롬프트옵스 성격의 기능. Core(합성·변수·
린트·버전·프리뷰/eject 연계)를 먼저 확정하기로 해 **이 Phase 에서는 제외**한다. 별도 Phase 로
분리하면 Phase 9 와 강결합해 다루는 게 자연스럽다(조각 성능 신호 = retention 확장).
