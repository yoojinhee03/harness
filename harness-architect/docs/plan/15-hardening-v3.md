# harness-architect 하드닝 작업 지시서 v3

> **v1 → v2**: 코드 검증 결과 v1이 코드에 대해 주장한 전제 4건이 부정확했다. 전부 정정하고
> **TASK 0(팩트체크 게이트)**을 신설했다.
> **v2 → v3**: 코드 재검증으로 v2에 6개 보강을 반영했다 — 게이트 halt 규칙 정교화, hot-gap
> 노출 게이팅, **caps 분류 임베더 고정(결정성)**, adopt 분해 경고, TASK 6 실효성 게이트,
> pgvector 정렬 기준 완화. 핵심은 **①/③ 임베더 핀**과 **② hot-gap 게이팅**이다.
>
> **사용법**: `## 공통 컨텍스트` + `TASK 0`을 먼저 붙이고, 이후 TASK를 하나씩 붙여라.
>
> **진행 로그(2026-08-19)**: TASK 0 게이트 통과(12참·2무해부분참). TASK 1 실측 완료
> ([caps-coverage-baseline](../caps-coverage-baseline.md): registry 87%·marketplace 52% 미스율 → 분기 A).
> TASK 2 완료(gap_demand DB 영속·provenance·게이팅). **TASK 7 은 병행 세션이 이미 구현(중복, 착수 금지).**
> 이에 따라 **TASK 0 #14("pgvector 미구현")는 낡음** — 작업트리에 `pgvector_store.py` 존재. TASK 6 은
> pgvector 증분 캐시로 긴급도가 더 낮아짐(백로그 강등 검토).

---

## 공통 컨텍스트

이 레포는 `harness-architect`(백엔드+프론트 모노레포)다.

**카탈로그 데이터 위치** — `harness-catalog/`는 **형제 폴더**다. git submodule이 아니다.
`.gitmodules`도 `catalog-data/`도 존재하지 않는다. 백엔드는 `../harness-catalog/components`를
읽는다(`main.py`의 `resolve_catalog_dir`, CLI의 `--catalog`/`CATALOG_DIR`). 향후 submodule
분리 여지는 경계로만 유지한다. 지금은 형제 폴더다.

먼저 아래를 읽어라. **추측하지 말고 실제 코드를 확인해라.**

- `registry_source.py` — FederatedRegistry (로컬 시드 / 공식 MCP 레지스트리 / 마켓플레이스)
- `catalog_store.py` — DbCatalogSource, sync_catalog
- `harvest.py`, `enrichment.py`, `vocabulary.py` — 수확 및 능력 태깅
- `recommender.py`, `ranking.py`, `store.py` — 추천 파이프라인
- `gap_demand.py` — GapDemand
- `adopt.py` — 기존 역파싱기 (**이미 존재한다**), `apps/cli`의 `adopt`/`harvest` 커맨드
- `harness_build.py`, 이미터(`emit/`), `emit/MAPPING.md`, `emit/base.py`의 `Emitter` Protocol
- `harness_resolver` 패키지
- `main.py`, `apps/mcp/.../server.py`, `settings.py`

### 불변 제약 (모든 TASK에 적용)

1. **리졸버는 순수함수로 유지한다.** I/O·네트워크·전역 상태를 리졸버에 넣지 마라. 기존
   테스트가 인라인 시드 데이터로 자립하는 성질을 깨지 마라.
2. **서빙과 하베스트의 분리를 유지한다.** 서빙 경로(DB 읽기)에 네트워크 호출을 추가하지 마라.
   특히 `DbCatalogSource`에 라이브 폴백을 넣지 마라 — 지금 없는 것이 의도된 설계다.
3. **그라운딩 3중 보증을 약화시키지 마라** — 스키마 봉쇄(카탈로그 id만 참조), id 검증 게이트,
   통제어휘 기반 결정적 gap 판정. (TASK 3이 이 결정성에 영향을 주므로 그 안의 결정성 제약을 지켜라.)
4. 기존 리졸버 테스트는 전부 통과 상태를 유지한다. 각 TASK 종료 시 전체 테스트를 돌려라.
5. 스키마·DB 변경은 alembic 마이그레이션을 반드시 동반한다.

### 작업 방식

각 TASK마다: **① 관련 파일을 읽고 ② 변경 계획을 먼저 제시하고 ③ 내 승인 후 구현하고
④ 테스트를 추가하고 ⑤ 전체 테스트를 돌려라.** 계획 없이 코드를 쓰지 마라.
(TASK 0은 코드 변경이 없으니 승인 없이 실행·보고한다.)

---

## TASK 0 — 팩트체크 게이트 (최우선, 코드 변경 없음)

### 왜 이게 있는가

v1 지시서는 코드에 대한 전제 4건이 틀렸다. 설계 문서와 요약을 현재 코드로 착각했고, 조건부
서술을 단정으로 증폭했다. 이 지시서도 같은 실수를 하고 있을 수 있다.

**아래 전제를 하나씩 코드에서 확인해라.** 틀린 전제 위에 코드를 쓰지 마라.

### 확인 목록

| # | 전제 | 확인 방법 |
|---|---|---|
| 1 | `harness-catalog/`는 형제 폴더이고 submodule이 아니다 | `.gitmodules` 부재, 백엔드의 실제 읽기 경로 |
| 2 | `adopt.py`가 `.claude/`·`.cursor/`를 읽어 `HarnessConfig`로 역파싱하고, 매칭 실패는 `unknown_mcp`로 보존한다 | 함수 본문 |
| 3 | `adopt.py`는 CLAUDE.md 본문을 inline prompt로 흡수하며, `SKILL.md`·settings hooks를 개별 컴포넌트로 분해하지는 **않는다** | 분해 로직 부재 확인 |
| 4 | CLI에 `verify` 커맨드가 없다 | CLI 엔트리포인트 |
| 5 | `extract_capabilities_heuristic`은 통제어휘 키워드에 안 걸리면 `[]`를 반환한다 | `vocabulary.py` |
| 6 | `harvest.py`의 `uncovered()`가 caps를 하나도 못 뽑은 컴포넌트 id를 열거한다 | 함수 본문 |
| 7 | `CapabilityEnricher`는 caps가 **빈 것만** 보강하며 상한이 150이다 | `enrichment.py` |
| 8 | API 서빙 레지스트리의 소스는 로컬 시드 + `DbCatalogSource` 단독이며, TTL 라이브 소스가 들어가지 않는다 | `main.py` |
| 9 | `DbCatalogSource.components()`는 DB만 읽고 DB가 비어도 라이브로 폴백하지 않는다 | `catalog_store.py` |
| 10 | MCP in-process 경로(`server.py`)는 TTL 라이브 소스를 직접 federate한다 | `server.py` |
| 11 | 저작 산출물에 `apiVersion: harness/v1` + `kind: Harness` 헤더가 이미 있다 | 직렬화 코드 |
| 12 | `GET /gaps/top`이 이미 존재하고 `gap_demand.py`는 인메모리 Counter다 | 라우터 + 모듈 |
| 13 | 이미터 손실은 `emit/MAPPING.md` 산문으로만 있고 기계판독 capability matrix가 없다 | `emit/base.py` Protocol + 파일 확인 |
| 14 | `VectorStore`는 인메모리이고 pgvector는 미구현이다 | `store.py` |

### 산출물

각 항목에 대해 **참 / 거짓 / 부분참** 판정 + 파일:라인 근거.

**halt 규칙** — 단순히 "부분참이면 멈춤"이 아니다. 각 항목에 추가로
**"이 판정이 의존 TASK의 접근을 무효화하는가?"**를 판단해라.

- **무효화하는 거짓/부분참** → 멈추고 보고. 틀린 전제 위에 코드를 쓰지 마라.
- **무해한 부분참**(접근이 그대로 유효) → 근거만 기록하고 진행.
  - 예: #7 enricher는 기본 빈 caps만 보강하나 `retag=True`면 전체 재분류(무해).
  - 예: #11 `$schema`는 없으나 `apiVersion`+`kind`가 있어 구조적 구별 가능(무해 —
    TASK 4의 근거를 오히려 정정한다).

---

## TASK 1 — `uncovered()` 실측 (코드 변경 최소, 30분)

TASK 3의 스코핑 근거를 먼저 만든다.

1. 현재 카탈로그(로컬 시드 + 라이브 하베스트 켠 상태)에 대해 `uncovered()`를 실행해라.
   (CLI `harness harvest`가 이미 `uncovered()`를 출력하고, `MCPRegistrySource`/`MarketplaceSource`가
   라이브 디스크립터를 준다 — 이 둘을 엮는 소형 스크립트로 충분하다.)
2. 측정: **전체 컴포넌트 수 / caps 보유 수 / 빈 caps 수 및 비율**. origin별(local·registry·marketplace)로 분리.
3. 빈 caps 컴포넌트 20개를 샘플링해 **왜 못 뽑혔는지** 분류해라 — 통제어휘에 해당 도메인이 없음 /
   설명이 너무 짧음 / 표현이 어휘와 다름(동의어) / 비영어.
4. 결과를 `docs/caps-coverage-baseline.md`에 기록해라.

**기본 가정은 "비율이 높다"다.** `extract_capabilities_heuristic`이 의도적으로 빈 태그 쪽으로
편향되어 있고(도크스트링: 틀린 태그보다 빈 태그가 낫다), 단어경계 매칭으로 오탐을 억제하며,
통제어휘 밖 도메인은 아예 못 뽑는다. 낮게 나오면 그 자체가 의외의 결과이므로 원인을 파악해라.

3번의 분류 결과가 TASK 3의 해법을 결정한다 — 동의어 문제면 임베딩 매칭이 잘 듣고, 어휘 부재
문제면 통제어휘 자체를 확장해야 한다.

---

## TASK 2 — GapDemand 영속화 + provenance

### 배경

`gap_demand.py`의 인메모리 Counter는 재시작하면 사라지고 다중 레플리카에서 집계되지 않는다.

우선순위가 높은 이유는 성능이 아니라 **복구 불가능성**이다. pgvector·caps 개선은 나중에 넣어도
과거에 소급 적용된다. GapDemand는 지금 버려지는 데이터를 되찾을 방법이 없다.

**단, 지금 기록되는 gap의 상당수는 거짓 gap일 수 있다.** 빈 caps 컴포넌트가 능력 매칭에서
이탈하므로, 실제로 그 능력을 제공할 수 있는 컴포넌트가 있어도 gap으로 보고된다. 그래서
**provenance 없이 저장하면 오염된 데이터를 나중에 정화할 수 없다.**

### 해야 할 일

1. 테이블 신설:
   - `capability` (통제어휘 문자열)
   - `requested_count`
   - `first_seen_at`, `last_seen_at`
   - `suggested_type` (skill/mcp/context/hook)
   - `resolved_at` (nullable)
   - `source` (recommend / studio / verify)
   - **provenance — 재평가용 (이 4개가 핵심이다)**
     - `catalog_revision` — 판정 당시 카탈로그 상태
     - `caps_source` — heuristic / enricher / zeroshot
     - `vocab_version` — 통제어휘 버전
     - `candidate_count` — 판정 당시 후보 컴포넌트 수
2. alembic 마이그레이션.
3. 인메모리 Counter를 원자적 upsert로 교체. **다중 레플리카 안전**하게.
4. 기록은 **비차단**. GapDemand 쓰기 실패가 추천 응답을 깨뜨리면 안 된다.
5. **`GET /gaps/top`과 계약을 정합시켜라.** 새 엔드포인트를 만들지 말고 기존 것을 확장하는 게
   우선이다. 중복 엔드포인트를 만들지 마라.
6. 카탈로그 sync 후 공급이 생긴 능력의 `resolved_at`을 채우는 후처리.
7. **재평가 유틸리티** — 과거 gap 기록을 현재 caps 상태로 다시 판정해 거짓 gap을 표시하는
   스크립트. TASK 3 이후 실행할 것이므로 지금 인터페이스만 만들어 둬라.
8. **hot-gap 사용자 노출 게이팅.** 지금 스튜디오는 hot gap을 "★만들면 재사용됨"으로 사용자에게
   노출한다(orchestrator 검색 경로). TASK 3 전에는 빈 caps 탓 거짓 gap이 섞여 있으므로, 이미
   공급 가능한 능력을 "만들라"고 오도할 수 있다. **데이터 기록은 계속하되, 사용자 대면 hot-gap
   표면화는 confidence로 게이팅**(또는 저신뢰 표시)해라. provenance의 `candidate_count`·`caps_source`를
   신뢰 신호로 쓸 수 있다. TASK 3 완료 후 게이트를 완화한다.

### 완료 기준

- 재시작 후 카운트 유지.
- 두 프로세스 동시 기록 시 카운트 정확.
- DB 장애 시 추천 요청이 정상 응답(경고 로그만).
- provenance 필드가 채워지고, 재평가 유틸리티가 과거 레코드를 읽을 수 있다.
- TASK 3 이전에는 저신뢰 hot-gap이 사용자에게 "만들라"고 노출되지 않는다(데이터 기록은 지속).

---

## TASK 3 — 능력 태깅 커버리지 (구 TASK 4)

### 배경 — v1의 메커니즘 서술은 틀렸다

**v1이 말한 "상한 150 때문에 상위 150개만 정상이고 나머지 1900개가 비어 있다"는 부정확하다.**
통제어휘 키워드에 걸린 컴포넌트는 150 밖이라도 caps를 가진다.

**실제 메커니즘:**

```
최종 caps 보유 = (휴리스틱이 vocab 키워드에 걸린 것) + min(150, 휴리스틱이 비운 것)   ← enricher 폴백
최종 빈 caps   = (휴리스틱이 비운 것) − min(150, 휴리스틱이 비운 것)
```

원인은 상한이 아니라 **`extract_capabilities_heuristic`의 의도적 편향**이다. 통제어휘에 안
걸리면 `[]`를 반환하고, 단어경계 매칭으로 오탐을 억제하며, 어휘 밖 도메인은 못 뽑는다.
`uncovered()`의 존재가 빈 caps를 예외가 아닌 예상 결과로 취급한다는 증거다.

**결과는 v1의 결론과 같다.** 빈 caps 컴포넌트는 지배 신호인 능력 매칭(가중치 2.5)에서 이탈하고,
기본 임베더만으로 평가된다. 그리고 그 방향은 **거짓 gap 과다 생성**이다 — 제공 가능한 컴포넌트가
있는데도 미충족으로 보고된다.

**참고**: 기본 임베더가 MD5 해싱이라는 점은 사실이지만, DB에 OpenAI 키가 등록되면 임베더가
교체되므로 "전부 MD5로 랭킹된다"는 서술은 조건부다.

### ⚠ 결정성 제약 — caps 분류 임베더를 서빙 임베더와 분리·고정해라

제로샷 caps는 **caps를 임베더 의존적으로** 만든다. 그런데 서빙 임베더는 `main.py`에서 DB 등록
OpenAI 키 유무로 런타임에 바뀐다(키 있으면 OpenAI, 없으면 Local). 이를 방치하면 **"OpenAI 키
등록"이라는 운영 행위 하나가 전체 카탈로그를 재태깅하고 모든 gap 판정을 이동**시킨다 —
불변제약 #3의 gap 판정 *메커니즘*은 결정적으로 남지만 그 *입력(caps)*이 비결정적이 된다.

- caps 분류에는 **고정 임베더**를 써라(LocalEmbedder 또는 명시적으로 핀된 모델 ID). 서빙
  임베더(런타임 키 의존)를 caps 분류에 재사용하지 마라.
- 통제어휘 벡터도 같은 고정 임베더로 한 번 계산해 캐시하고, `vocab_version`과 함께 핀해라.
- 이 결정성 변화(caps가 무엇에 의존하는지, 무엇을 고정했는지)를 설계문서에 명문화해라.
- TASK 2의 provenance(`caps_source`·`vocab_version`)는 *추적*용이다. *재현성*은 임베더 핀으로만
  보장된다.

### 해야 할 일

TASK 1의 실측 결과, 특히 **빈 caps 원인 분류**에 따라 해법을 정해라.

**동의어·표현 차이가 주 원인이면 — 제로샷 임베딩 분류:**
1. 통제어휘 전체 항목을 **한 번** 임베딩해 고정 벡터로 유지(어휘 변경 시에만 재계산).
2. 컴포넌트의 description + 툴 이름/스키마를 임베딩해 어휘 벡터와 코사인 매칭 → 임계값 위 상위 N개를 caps로.
3. **컴포넌트당 임베딩 1회, LLM 호출 0회 → 상한 제거.**
4. 휴리스틱은 유지해라. 제로샷은 휴리스틱이 비운 것에만 적용한다 — 휴리스틱의 높은 정밀도를 버리지 마라.
5. 모호한 케이스(1·2위 점수 차 작음, 전부 임계값 미달)만 LLM enricher로 승격. 상한에 걸려도
   제로샷 결과가 폴백으로 남게 해라.

**통제어휘 부재가 주 원인이면 — 어휘 확장 우선:**
1. 빈 caps 컴포넌트의 설명을 클러스터링해 누락된 `domain.capability` 후보를 도출.
2. 통제어휘에 추가하고 `vocab_version`을 올려라.
3. 그 다음 제로샷을 적용해라. 어휘가 빈약한 상태에서 제로샷을 돌리면 없는 카테고리로 매칭할 수 없다.

**공통 후처리:**
- 전량 커버 후 IDF `cap_weight`를 **재계산**해라 — 분포가 달라진다.
- `RELEVANCE_FLOOR=0.20`을 재보정해라(주석이 임베더 교체 시 재보정 필요를 이미 명시). **보정 근거를
  숫자로 남겨라** — 샘플 쿼리 세트에 대한 재현율/정밀도.
- caps 정밀도를 검증해라. 제로샷은 휴리스틱보다 오탐이 많다. 라벨링 샘플 50개에 대한 정밀도가
  휴리스틱보다 크게 떨어지면 임계값을 올려라. **거짓 gap을 줄이려다 거짓 충족을 만들면 더 나쁘다.**
- TASK 2의 재평가 유틸리티를 실행해 과거 gap 기록을 정화해라.

### 완료 기준

- 빈 caps 비율이 baseline 대비 측정 가능하게 감소(목표는 TASK 1 실측 후 확정).
- LLM 키 없이 전량 태깅이 완료된다.
- caps 정밀도가 휴리스틱 baseline 이상이다.
- caps 분류 임베더가 서빙 임베더와 분리·고정되어, DB 키 등록/해제가 caps·gap 판정을 바꾸지 않는다(테스트).
- 재보정 전후 랭킹 비교와 gap 정화 결과가 문서로 남는다.

---

## TASK 4 — IR 파일명·스키마 충돌 해소 (구 TASK 1)

### 배경

`harnessprotocol/harness-kit`가 구현하는 **Harness Protocol v1**이 동일 파일명 `harness.yaml`을
점유했다. 스키마가 완전히 다르다.

```yaml
# 우리 것 (선언적 저작 산출물 = 리졸버 입력)
apiVersion: harness/v1
kind: Harness
components:
  - ref: "github-mcp@1.2.0"

# Harness Protocol v1
$schema: https://harnessprotocol.io/schema/v1/harness.schema.json
version: "1"
metadata: { name: ... }
```

**v1 정정**: v1은 "구분할 방법조차 없다"고 했으나 과장이다. 우리 파일에는 `apiVersion` + `kind`가
이미 있어 구조적으로 구별된다. `$schema` 추가는 여전히 권장하지만 방어 조치이지 부재 해소가 아니다.

**v1 정정 2**: v1이 제안한 `harness.lock.yaml`은 의미가 틀렸다. 우리 파일은 `ref: id@version`을 담은
**선언적 소스**이고 해소·핀된 lock이 아니다. "lock"은 오해를 부른다.

### 해야 할 일

1. 파일을 **`.harness/` 아래로 이동**해라.
2. basename에 대해 두 안의 트레이드오프를 판단해 제안해라:
   - `.harness/harness.yaml` — 경로 충돌은 사라지지만 basename이 그대로다. `**/harness.yaml`
     글롭과 파일명 기반 스키마 연결(yaml-language-server 등)이 여전히 우리 파일을 HP v1로 오인할 수 있다.
   - `.harness/source.yaml` 또는 `.harness/authoring.yaml` — 완전히 회피되고 "선언적 저작
     산출물"이라는 실제 역할과도 맞는다. **(권장)**
3. `$schema`를 부여해라(우리 스키마 URL 또는 상대 경로). `apiVersion`·`kind`는 유지.
4. **하위 호환 리더** — 옛 경로/이름이 있으면 읽되 deprecation 경고. 쓰기는 새 위치로만.
5. 로드 시 HP v1 스키마를 가리키는 파일은 **명확한 에러**로 거부. 스택트레이스가 아니라 설명 메시지.
6. **저장 데이터 마이그레이션** — ConversationStore·harness store에 이미 쌓인 문서를 새 포맷으로
   옮기는 마이그레이션을 작성해라. 이게 v1에서 빠진 항목이다.
7. blast radius 전체를 갱신해라: `adopt.py`, `harness_build.py`, 이미터, MCP server, CLI,
   ConversationStore/harness store, README, 설계문서, 픽스처.

### 완료 기준

- 새 위치로만 쓴다. 옛 위치는 경고와 함께 읽힌다.
- 기존 저장 문서가 마이그레이션 후 정상 로드된다.
- HP v1 프로필을 넣으면 설명적 에러가 난다.
- 전체 테스트 통과.

---

## TASK 5 — `adopt.py` 확장 + `verify` 진입점 (구 TASK 3)

### 배경 — v1 정정

**v1은 "이미터의 역방향이 없다"고 했으나 틀렸다.** `adopt.py`가 이미 `.claude/`·`.cursor/`를 읽어
`HarnessConfig`로 역파싱하고, 매칭 실패는 `unknown_mcp`로 보존한다. 테스트와 계획(07), CLI
`adopt` 커맨드도 있다. **새로 만들지 말고 확장해라.**

`adopt.py`의 실제 한계는 CLAUDE.md 본문을 inline prompt로 흡수만 하고 `SKILL.md`·settings hooks를
개별 컴포넌트로 분해하지 않는다는 점이다(현재 `adopt_dir`이 읽는 파일: CLAUDE.md · .mcp.json ·
.claude/settings.json[model만] · .cursor/mcp.json · .cursor/rules/*.mdc). 그게 확장 지점이다.

**진짜 신규 가치는 5b·5c·5d·5e다.**

### 5a. `adopt.py` 분해 확장

- `.claude/skills/*/SKILL.md`를 개별 skill 컴포넌트로 분해(이산 파일 = 안전).
- `.claude/settings.json`의 hooks를 개별 hook 컴포넌트로 분해(이벤트·matcher·timeout·failure 보존, 이산 엔트리 = 안전).
- CLAUDE.md의 섹션 구조로 context 컴포넌트를 분리하는 것은 **best-effort로만** 해라. 섹션 경계
  분할은 휴리스틱이라 경계를 지어낼 위험이 있고, 이는 adopt.py의 "구조적으로 식별 가능한 것만
  복원(환각 금지)" 원칙과 충돌한다. **불확실하면 inline prompt가 기본**이다 — 버리지도, 지어내지도 마라.
- **hook 이벤트 역매핑은 손실적이다.** eject가 `after_request`를 드롭하므로(emit/MAPPING.md) 그
  이벤트는 라운드트립으로 복원 불가다. `PreToolUse→before_tool_call` 등 복원 가능한 매핑만 역으로
  적용하고, 복원 불가 이벤트는 note로 남겨라(없는 걸 지어내지 마라).
- unknown 보존 정책을 유지·확장.

### 5b. 보안 스탠스 — 구현 전에 문서로 먼저 박아라

인제스트 대상은 **전부 데이터이고 명령이 아니다.** 나중에 붙이기 어려운 종류의 결정이다.

- CLAUDE.md·규칙 파일의 텍스트가 LLM에게 지시하는 형태여도 **실행 지시로 해석하지 않는다.**
  인제스트 결과를 LLM 프롬프트에 넣을 때 데이터 경계를 명시해라.
- 환경변수는 **존재만 검증하고 값을 읽거나 로깅하지 않는다.**
- 시크릿으로 보이는 값은 파싱 결과에 담지 말고 마스킹.
- `SECURITY.md` 또는 설계문서에 명문화해라. 코드 주석이 아니다.

### 5c. `verify` 커맨드 — 3종 판정

```
harness verify <repo> [--require <capabilities>] [--target cursor]
```

**① 능력 미충족** — 기존 `_compute_gaps`를 재사용해라. 새로 만들지 마라. **TASK 3 완료 후에만
신뢰할 수 있다** — 그 전에는 거짓 gap이 과다 보고된다.

**② 이식 손실** — 지금 `emit/MAPPING.md` 산문으로만 존재하는 손실 정보를 **기계판독 capability
matrix로 승격**해라. `emit/base.py`의 `Emitter` Protocol에 "표현 불가 필드 선언" 메서드를 추가하고,
각 이미터가 자신의 손실을 선언하게 만든 뒤 그 교집합을 리포트해라.

```
⚠ .cursor/ 방출 시 손실 3건
    permissions.deny (rm -rf, curl|sh) — 대응 없음, 가드레일 소실
    hook depends_on 순서       — 표현 불가, 실행 순서 미보장
    timeout_ms                 — 무시됨
```

손실 목록을 하드코딩하지 마라. 이미터가 선언하게 해라 — 하드코딩하면 이미터 변경 시 즉시 거짓말이 된다.

**③ 훅 계약 위반** — `depends_on` 순환, `timeout_ms` 예산 초과, `failure` 정책 누락, 훅이
non-lifecycle 능력을 제공하는 경우.

### 5d. 출력 — 사람용 리포트가 아니라 CI 게이트

- 종료 코드: 0 통과 / 1 위반 / 2 실행 오류
- `--format json` 기본. 사람용 텍스트는 부가.
- 심각도를 `.harness/policy.yaml`로 조정 가능하게 — 조직 게이트가 목표다.
- **거짓 양성을 줄이는 쪽으로 기본값을 잡아라.** CI 린터에서 거짓 양성은 신뢰를 죽인다. 확신이 낮은
  판정은 경고로 내려라.

### 5e. 데이터 수집

- 발생 gap을 TASK 2에 `source=verify` + provenance로 기록.
- **공출현 테이블 신설** — 한 하네스 안에서 함께 등장한 컴포넌트 id 집합 + 카운트. alembic 포함.
  협업 필터링 신호이고, 추천 품질에서 의미 유사도보다 강할 가능성이 있다.
- **옵트인.** 기본은 로컬 전용. 전송은 명시적 플래그.

### 완료 기준

- 픽스처 레포 3개(정상 / 능력 미충족 / 훅 순환)에 대해 올바른 종료 코드.
- Cursor 손실 리포트가 실제 이미터 제약과 일치(matrix 기반이므로 자동 정합).
- env 값이 어떤 출력·로그에도 나타나지 않는 테스트.
- 기존 `adopt.py` 테스트가 전부 통과.

---

## TASK 6 — MCP in-process 경로의 TTL/인덱스 분리

### 배경 — v1 정정

**v1은 "5분 TTL이 전체 재임베딩을 유발한다"고 했으나 API 백엔드에는 해당되지 않는다.**

- `main.py`: 서빙 레지스트리는 로컬 시드 + `DbCatalogSource` 단독. TTL 라이브 소스가 들어가지 않는다.
- `DbCatalogSource.components()`는 `_store.all()`만 읽고 DB가 비어도 라이브로 폴백하지 않는다.
- `_sync_loop`는 DB에만 쓰고 서빙 레지스트리를 교체하지 않는다.
- 하베스트의 `build_live_sources`는 매 sync마다 fresh 인스턴스라 300초 TTL이 사실상 무효.

**따라서 문제가 실존하는 곳은 MCP in-process 경로(`server.py`의 `federate(local)`) 하나다.** 여기서만
TTL 라이브 소스가 직접 federate되어 generation을 흔들고 재색인을 유발한다.

### 해야 할 일

0. **착수 전 실효성 확인(게이트).** 이 TASK는 실이득이 낮을 수 있다 — MCP in-process는
   `LiveRecommender(get_registry())`가 임베더 미지정이라 **LocalEmbedder(값쌈)**로 재색인하고,
   재색인은 **레지스트리 id-set이 실제 변할 때만** 발생한다(공식 레지스트리는 서버 목록을
   5분마다 바꾸지 않는다). 착수 전 다음을 실측해라:
   - MCP 경로가 실제로 OpenAI 임베더로 도는가?
   - 세션이 장시간 상주하며 그동안 id-set이 재색인을 유발할 만큼 자주 바뀌는가?
   **둘 다 아니면 이 TASK를 백로그로 강등하고 보고해라.** 값싼 로컬 재색인을 최적화하는 것은
   가치가 낮다.
1. MCP in-process 경로에 한정해 `serve_revision`(표시용)과 `index_revision`(임베딩용)을 분리해라.
2. `index_revision`은 내용 해시 변경에만 반응하게 해라. TTL refresh가 재색인을 유발하지 않게.
3. **API 백엔드는 손대지 마라.** 이미 DB로 분리되어 있다.
4. 두 revision의 의미와 갱신 주기를 설정 문서에 명시.

### 완료 기준

- (착수 시) 실효성 게이트를 통과했다 — 실측 근거가 문서로 남는다. 미통과면 백로그로 강등하고 종료.
- MCP 경로에서 TTL refresh가 재임베딩을 유발하지 않는 테스트.
- API 백엔드 동작에 변화가 없다.

---

## TASK 7 — pgvector + 증분 임베딩 — ✅ 동시 작업으로 완료(중복)

> **상태(2026-08-19 확인)**: 병행 세션이 이미 구현했다 →
> [`apps/api/src/harness_api/pgvector_store.py`](../apps/api/src/harness_api/pgvector_store.py)
> (+ `main.py` 배선, `store.py`/`recommender.py` `store=` 파라미터, `test_vector_store.py`).
> **이 TASK 는 착수하지 마라 — 중복이다.** 구현이 이 사양과 일치한다:
> - `catalog_embeddings`(pgvector `vector` 컬럼, 차원 미고정 → 임베더 무관).
> - **id + content_hash 증분 캐시** — 내용 해시가 같으면 재임베딩 스킵, stale 행 삭제.
> - **정확 코사인 `ORDER BY embedding <=>`** (ANN 인덱스 미사용) → 아래에서 우려했던 근사 정렬
>   불일치가 **자동 해소**됨(정확 정렬).
> - Postgres 일 때만 활성, SQLite 는 인메모리 폴백 유지(개발).
>
> 남은 확인: (1) alembic 마이그레이션 동반 여부(현재 런타임 `CREATE TABLE IF NOT EXISTS` — 불변제약 #5
> 상 마이그레이션 권장), (2) README 🚧 표시 갱신. 이 둘만 후속으로 점검.

<details><summary>원안(참고용, 착수 금지)</summary>

1. 임베딩을 pgvector 컬럼으로 이동. alembic 마이그레이션.
2. **id별 증분 캐시** — 내용 해시가 바뀐 것만 재임베딩.
3. 인메모리 O(N) 정렬을 벡터 인덱스 쿼리로 교체.
4. SQLite 폴백은 인메모리 방식 유지(개발 환경).
5. README의 🚧 갱신.

완료 기준: 1개 변경 시 1개만 재임베딩 · Postgres/SQLite 추천 결과 일치(정확거리 정렬 강제 또는 집합 동등).

</details>

---

## 백로그 (기록만, 착수하지 마라)

- **Harness Protocol v1 이미터** — 세 번째 이미터. 남의 배포 인프라를 얻으면서 파일명 충돌에서도
  벗어난다. TASK 4 완료 후 검토.
- **skillsmp 소스 추가** — 주석의 Smithery/Glama/mcp.so는 전부 MCP라서 공식 레지스트리와 겹친다.
  실제 공백은 non-mcp 타입이고 마켓플레이스 단일 파일 500개 상한이 병목이다. skillsmp가 SKILL.md를
  REST API로 열어두고 있어 델타가 훨씬 크다.
- **승격 거버넌스** — 현재 스코프 write 권한만으로 공유 카탈로그 승격이 가능하다. 다인 승인 +
  `sandbox:none` 훅 추가 심사.
- **공출현 신호를 랭킹에 투입** — TASK 5에서 데이터가 쌓인 뒤. 작동하면 임베딩은 콜드스타트
  폴백으로만 남는다.
- **`verify --fix`** — gap을 스튜디오 저작 루프로 연결. verify 판정이 안정된 뒤에.
