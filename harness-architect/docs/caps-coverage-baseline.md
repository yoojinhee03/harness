# 능력 태깅 커버리지 baseline (하드닝 TASK 1)

> **목적**: TASK 3(능력 태깅 커버리지)의 해법 분기를 결정하기 위한 실측. **미스율 숫자보다
> 원인 분류가 우선 산출물**이다 — 동의어·표현 차이면 제로샷 임베딩이 듣고(분기 A), 통제어휘
> 부재면 어휘부터 확장한다(분기 B).
>
> 측정 도구: [`packages/catalog/scripts/measure_caps.py`](../packages/catalog/scripts/measure_caps.py)
> PRIMARY 지표 = **오프라인 휴리스틱 미스율**(`extract_capabilities_heuristic` 재실행, LLM·네트워크 무관).
> 측정 일시 기준: registry 는 `--sample 200`(앞 ~2페이지, **최신순 편향**), marketplace·local 은 전수.

## TL;DR — 결정

- **커버리지 문제는 실재하고 심각하다**: 하베스트 origin 의 휴리스틱 미스율이 **registry 87.3% · marketplace 52.1%**.
  → TASK 3(능력 태깅 개선) 착수는 정당하다.
- **분기는 A(제로샷 임베딩) 쪽**: 빈 caps 중 "가까운 통제어휘가 아예 없음(low)"은 **registry 3.6% · marketplace 1.3%**
  뿐이다. 대부분은 어휘는 있으나 휴리스틱이 표현을 놓친 것 → 임베딩으로 회수 가능.
- **단, 분기 확정은 TASK 3 초입에서 OpenAI 프록시로 재확인**할 것. 아래 §3 의 한계 참조(LocalEmbedder 헛매칭).

---

## 1. 미스율 (PRIMARY, origin 분리 — 합산 금지)

| origin | 전체 | 휴리스틱 빈 caps | **미스율** | (참고) 로딩시 tagged 빈 caps | 대표성 |
|---|---:|---:|---:|---:|---|
| **registry** | 126 | 110 | **87.3%** | 110 | 최신순 편향 표본(200 요청 → classify 후 126) |
| **marketplace** | 286 | 149 | **52.1%** | 149 | 전수(단일 파일) |
| local | 13 | 0 | 0.0% | 0 | **비대표**(수큐레이션, caps 태생적 보유) |

- registry 표본은 `--sample 200`(앞 2페이지)이라 **최신순 편향**이다. 2페이지에서 커서 잔존(절단) —
  전체 모집단은 더 크다. 무편향 전량은 `--full` 로 재측정(§4).
- "tagged 빈 caps"가 "휴리스틱 빈 caps"와 같은 건, 하베스트 시 `harvest_component` 가 같은 휴리스틱을
  쓰기 때문이다(즉 로딩된 caps = 휴리스틱 결과). enricher(LLM, 상한 150)는 이 측정에서 제외했다.

## 2. 원인 신호 — 포섭 가능성 (우선 산출물, TASK 3 분기 결정)

빈 caps 컴포넌트를 임베딩해 통제어휘 벡터와의 최대 코사인으로 버킷팅. high(≥0.20)=제로샷 회수 가능,
low(<0.10)=가까운 어휘 없음(어휘부재 후보).

| origin | 빈 caps | high(제로샷↑) | mid | **low(어휘부재?)** | → 분기 |
|---|---:|---:|---:|---:|---|
| registry | 110 | 32 | 74 | **4 (3.6%)** | **A: 제로샷 임베딩** |
| marketplace | 149 | 68 | 79 | **2 (1.3%)** | **A: 제로샷 임베딩** |

**해석**: 어휘부재(low)가 극소수라는 것은, 실측된 하베스트 서버들의 도메인(DB·결제·배포·관측·데이터
분석 등)이 대부분 이미 통제어휘 안에 있고, 휴리스틱의 **키워드 매칭 재현율**이 낮아 놓쳤다는 뜻이다.
이는 제로샷 임베딩 분류(분기 A)로 회수 가능한 유형이다. 어휘 확장(분기 B)은 소수 잔여에만 필요.

## 3. ⚠ 신호의 한계 — 확정은 OpenAI 프록시로

기본 `LocalEmbedder`(문자/단어 해싱)는 **의미가 아니라 표면 문자 겹침**으로 매칭한다. 실측에서 헛매칭 관찰:

| 컴포넌트(실제 도메인) | 프록시 최근접 vocab | cos | 버킷 | 평가 |
|---|---|---:|---|---|
| `aiven` (PostgreSQL·Kafka DB) | `web.search` | 0.403 | high | ✗ 헛매칭("OpenSearch"의 search) |
| `alloydb` (PostgreSQL) | `data.vector` | 0.309 | high | △ 근접(DB 계열) |
| `discord` (메시징) | `comms.messaging` | 0.155 | mid | ✓ 타당 |

함의(두 방향 모두 노이즈):
- **high 과대**: 어휘 겹침으로 무관한 vocab 에 높은 점수(위 aiven).
- **low 과소**: LocalEmbedder 는 공통 트라이그램만 있어도 비영점 코사인을 줘, 진짜 어휘부재도 low 미만으로
  안 떨어질 수 있다. → **"low 가 작다"는 결론은 하한 신호이지 확정이 아니다.**

**그럼에도 미스율(87%/52%)은 확정적**이고, 분기 A 방향은 강하게 시사된다. **TASK 3 초입에서
OpenAI 임베더로 §2 를 재측정해 high/mid/low 를 확정**한 뒤 임계값·분기를 못박을 것.
(현재 `--embedder openai` 는 미배선 — LocalEmbedder 폴백+경고. TASK 3 에서 caps 분류 임베더를
서빙 임베더와 분리·고정해 배선하며 함께 활성화.)

## 4. 재현 / 확정 측정 (실행법)

```bash
# 이 baseline 재현(최신순 편향 표본)
python packages/catalog/scripts/measure_caps.py --source all --sample 200

# 무편향 전량(크롤 비쌈, 대표성↑) — registry 모집단 전체
python packages/catalog/scripts/measure_caps.py --source registry --full

# fetch/측정 분리(재현성) — 네트워크 있는 곳에서 스냅샷 저장 → 오프라인 반복 측정
python packages/catalog/scripts/measure_caps.py --source all --sample 200 --save-snapshot live.json
python packages/catalog/scripts/measure_caps.py --from-snapshot live.json
```

**표본 대표성(커서 페이지네이션 한계)**: 공식 레지스트리는 `updated_since` 순 커서라 offset·랜덤
접근이 없다. `--sample N`은 앞 N개 = 최신순 편향. 대표 수치가 필요하면 `--full`.

## 5. TASK 3 로 넘기는 결정

1. **착수 정당**: 미스율 registry 87% / marketplace 52% → 커버리지 개선 필요.
2. **분기 A(제로샷 임베딩) 우선**: 어휘부재(low)는 극소수(<4%). 어휘 확장(B)은 잔여 소수에 한정.
3. **선행 확인**: TASK 3 첫 단계에서 OpenAI 임베더로 원인 신호 재측정 → high/mid/low 확정 →
   caps 분류 임계값·재보정 근거 확보. **caps 분류 임베더는 서빙 임베더와 분리·고정**(결정성 제약).
4. **정밀도 가드**: 제로샷은 휴리스틱보다 오탐↑. 라벨링 샘플로 정밀도가 휴리스틱 baseline 이상인지
   검증하고, 미달 시 임계값 상향("거짓 gap 줄이려다 거짓 충족 만들면 더 나쁘다").

---

## 6. TASK 3 제로샷 측정 결과 (오프라인, LocalEmbedder) — 활성화 보류

제로샷 분류기([caps_zeroshot.py](../packages/catalog/src/harness_catalog/caps_zeroshot.py))를 라이브
스냅샷(425개)에 돌린 보정 결과([eval_zeroshot.py](../packages/catalog/scripts/eval_zeroshot.py)):

| threshold | 빈 caps(259) 중 채움 | 정밀도(육안) |
|---:|---:|---|
| 0.25 | 43 (16.6%) | 낮음 — 표면('search') 매칭 다수 |
| 0.30 | 17 (6.6%) | 낮음 |
| 0.35 | 4 (1.5%) | 여전히 헛매칭(`aiven`(DB)→`web.search`) |
| 0.40 | 1 (0.4%) | — |

**결론**: LocalEmbedder(문자 트라이그램) 제로샷은 **정밀도 부족** — 유효 커버리지 구간에서 헛매칭이
많아 켜면 **거짓 충족**(제공 못 하는 능력을 있는 척)이 발생한다("거짓 gap 보다 나쁘다"). 따라서
**제로샷을 기본 sync 파이프라인에 연결하지 않는다**(인프라·보정 하네스만 준비). **활성화 조건**:
OpenAI 등 semantic 임베더로 `eval_zeroshot.py --from-snapshot` 재측정 → 정밀도 확인 → 임계값 확정 →
caps 분류 임베더를 **서빙과 분리·고정**해 배선. 이때 IDF `cap_weight`·`RELEVANCE_FLOOR` 재보정 +
TASK 2 재평가(`reeval_gaps.py`)로 과거 거짓 gap 정화.

> 즉 TASK 3(caps 커버리지)은 **semantic 임베더 없이는 안전하게 완료 불가**임이 데이터로 확인됐다.
> 인프라는 준비 완료(키만 생기면 보정→배선). 그 전까진 60.9% 빈 caps 가 유지된다(정직 표기).

---

## 부록 — 스크립트 검증 노트

로컬 실측(빈 caps 0)은 원인 신호·샘플·버킷 경로를 타지 않으므로, 합성 스냅샷(빈 caps 포함)으로
그 경로를 별도 검증했다: 빈 caps 탐지 / 최근접 vocab·코사인·버킷 산출 / 샘플 테이블 / 분기 추천 /
"tagged vs 휴리스틱 재계산" 구분 / 스냅샷 라운드트립이 모두 정상 동작함을 확인했다.
