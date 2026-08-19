# 카탈로그 기여 규약

카탈로그는 추천 품질을 좌우하는 **1순위 자산**이다. 컴포넌트 하나 = `components/<id>.yaml`
파일 하나. 아래 규약을 지켜야 리졸버 계약과 RAG 검색이 함께 동작한다.

## 1. 이중 필드 원칙 (두 주인을 섬긴다)

모든 컴포넌트는 두 소비자를 동시에 만족시켜야 한다. 필드를 의식적으로 나눈다.

- **검색/랭킹용 (RAG, 퍼지해도 됨)** — `summary`, `description`, `use_when`,
  `capability_tags`, `keywords`, `examples`. 임베딩·랭킹에만 쓰이므로 자연어로 풍부하게.
- **계약용 (리졸버/빌더, 엄격해야 함)** — `provides`, `requires`, `conflicts_with`,
  `constraints`, `auth`, `config_schema`, `defaults` + 타입 델타. 검증·의존성 해소·실행에
  쓰이므로 통제 어휘와 스키마를 정확히.

`use_when` 은 임베딩의 핵심 신호다. "무엇을 하는가"가 아니라 "언제 이걸 쓰나"를 쓴다.

## 2. 통제 어휘 (capability)

`provides` / `requires` / `capability_tags` 는 **자유 문자열이 아니라 통제 어휘**를 쓴다.
명명 규칙: `domain.capability` — 2단계, 소문자, 하이픈. `provides`와 `requires`가 같은
어휘를 써야 cross-type 연결(skill → mcp)이 성립한다.

- capability **추가**는 자유롭게. 가능하면 기존 도메인 아래에 넣는다(도메인 폭증 방지).
- **도메인 추가·이름 변경은 리뷰 필수** (도메인은 척추). 도메인 목록은 [DOMAINS.md](DOMAINS.md)
  (코드 상수 `harness_catalog.vocabulary.DOMAIN_VOCAB` 와 동기). 아직 컴포넌트 없는 도메인도 등재해
  요구가 카탈로그보다 넓게 잡히게 한다 → gap 이 표면화되고 시딩 큐로 흐른다.
- 프로젝트마다 내용이 다른 지식은 `domain.knowledge` 예외 버킷으로.

facet 분류(메타): `access`(주로 MCP) · `task`(주로 Skill) · `knowledge`(주로 Context) ·
`lifecycle`(주로 Hook) · `prompt`(Context 프롬프트 조각).

새 컴포넌트는 [TEMPLATE.yaml](TEMPLATE.yaml) 을 복사해 시작한다(각 필드 좋은/나쁜 예 포함).

## 3. 훅 리뷰 게이트 (공급망 신뢰)

hook 타입은 라이프사이클 시점에 임의 로직을 실행하므로 등록 시 추가 심사한다.

- `sandbox: none` (인프로세스) 은 **명시 승인 필요**. 기본은 `restricted`.
- `blocking: true` (요청 차단 가능) 은 리뷰 게이트 대상.
- `failure` 는 guardrail·validation 계열이면 `fail_closed`, 관찰용(logging)이면 `fail_open`.
- `timeout_ms` 필수(격리 런타임이 강제).
- `can_modify_request` / `can_modify_response` 는 선언 = 상한이며 런타임이 강제한다.

## 4. 버전·상태

- `version` 은 semver. 파괴적 변경은 major 상승.
- `status`: `stable` | `beta` | `deprecated`. deprecated 는 리졸버가 warning 을 낸다.
- `id` 는 불변 slug (참조 키). 바꾸면 기존 harness.yaml 참조가 깨진다.

## 5. 제출 전 체크

```bash
# 스키마 검증 (백엔드 레포에서)
uv run python -m harness_catalog.loader --validate ../harness-catalog/components
```

- 4타입 델타 필드가 타입에 맞게 채워졌는가.
- `requires` 로 선언한 능력을 제공하는 컴포넌트가 카탈로그 어딘가에 존재하는가
  (없으면 영구 gap → 콜드스타트 큐로).
- `conflicts_with` / `exclusive_group` 는 양방향 일관적인가.
- hook 이면 `failure`·`timeout_ms` 가 있는가, 다른 컴포넌트 능력을 provides 로 중복 선언하지 않는가
  (리졸버가 하드 에러로 잡는다).

## 6. 카탈로그 성장 (추측 아닌 수요 데이터로)

무엇을 다음에 시딩할지는 추측하지 않는다. recommender 가 남기는 gap 신호를 집계해 정한다:

```bash
# 요구됐지만 카탈로그에 없던 능력을 빈도순으로 — 콜드스타트 시딩 우선순위
python ../harness-architect/packages/catalog/scripts/aggregate_gaps.py <서버로그…>
```

상위 항목부터 **실존 도구**(공개 API/패키지가 실제 존재)를 찾아 TEMPLATE.yaml 로 작성한다. 시드
컴포넌트를 대량 생성하지 않는다 — 검증 불가능하면 넣지 않는다.
