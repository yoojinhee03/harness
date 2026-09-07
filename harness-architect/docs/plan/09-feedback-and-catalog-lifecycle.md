# Phase 9 — 피드백 루프 활성화 & 카탈로그 생애주기

> 설계: 피드백 루프(설계 문서) — `usage_count`·`retention_score` 필드는 카탈로그 스키마에
> 이미 있고 랭킹이 가중까지 하지만, **신호를 채우는 파이프가 비어 있다.** 이 Phase 는 카탈로그를
> 살아있는 자산으로 만든다: (a) 실사용 신호 되먹임, (b) 버전 드리프트 감지, (c) 레시피 승격.

## 왜 (차별화)

기존 플러그인은 "무엇이 실제로 유지·폐기되는지" 학습하지 못한다. 카탈로그가 최우선 자산인 이
프로젝트에선, 실사용 피드백이 랭킹 품질로 복리 누적되는 게 해자(moat)가 된다.

## 목표

- 생성/eject 시점의 **선택·폐기**를 옵트인 신호로 수집 → `usage_count`/`retention_score` 갱신
  → 랭킹 반영(가중은 이미 존재).
- 저장된 하네스가 카탈로그 갱신에 뒤처졌는지 **드리프트 diff** 제안.
- 검증된 시나리오를 **1클릭 레시피**로 승격.

## 작업

1. **피드백 수집(옵트인)** — 확정(`/generate`)·`eject` 시 선택된/폐기된 컴포넌트를 이벤트로
   기록(로컬 우선·익명, 전송은 명시 옵트인). `usage_count` 증가, keep/drop 비율로
   `retention_score` 갱신하는 순수 집계 함수 + 랭킹 반영 테스트.
2. **드리프트 / 업그레이드 (`harness doctor`)** — 저장된 하네스의 컴포넌트 `version`·`status`
   를 현재 카탈로그와 비교 → `deprecated`·상위 버전 존재 시 "교체/업그레이드" diff 제안.
   CLI `harness doctor` + API `POST /doctor`.
3. **레시피** — 시드 3 시나리오(PR 리뷰·이슈 분류·문서 초안)를 시작점 템플릿으로 승격:
   프론트 화면 A 의 "레시피로 시작" + `harness init --recipe pr-review`. 레시피는 카탈로그
   위의 큐레이션(별도 데이터, 컴포넌트 재사용).

## 완료 기준

- [x] 피드백 이벤트 기록(옵트인) + 갱신 순수 함수 + 랭킹 반영 테스트 — `harness_catalog/feedback.py`(순수),
      `harness_api/feedback.py`(스토어), `component_feedback` 테이블(alembic a7b8c9d0e1f2),
      `POST /feedback`·`GET /feedback/top`, eject 시 selected 자동 기록.
- [x] `harness doctor`(드리프트/deprecated diff, `--fix`) + `POST /doctor` +
      `POST /harnesses/{id}/doctor` + 테스트 16건.
- [x] 레시피 3종(`harness-catalog/recipes/`) + 프론트 "레시피로 시작" + CLI `harness init --recipe`.
- [x] **옵트인 꺼짐이 기본** — `HARNESS_FEEDBACK` 미설정 시 아무것도 기록하지 않고 랭킹도 불변
      (테스트로 고정). pytest 427 통과.

## 구현 노트 (2026-09-07)

- **보수적으로 센다.** 관측 `MIN_OBSERVATIONS`(5) 미만은 usage·retention 둘 다 중립(0) — 신호가
  붙기 전과 점수가 정확히 같다. 소량 데이터가 랭킹을 우연으로 흔들면 안 된다.
- **Component 를 안 건드리고 `rank(usage=...)` 로 덮는다.** Component 를 복사·변형하면 임베딩
  `content_hash` 계산 경로를 건드려 전량 재임베딩 위험이 생긴다. 덕분에 신호 갱신이 재색인을
  유발하지 않는다(TTL 60초 캐시로 주입).
- **retention 은 노출이 아니라 채택률이다**(분모 = selected+dropped). 그래서 `dropped` 수집이
  핵심이다 — 없으면 늘 1.0 이라 변별력이 0 이다. eject 는 selected 만 알 수 있으므로 drop 은
  클라이언트가 `POST /feedback` 으로 보낸다.
- **eject 를 자동 기록 지점으로 골랐다.** "실제로 런타임에 가져간다"가 가장 강한 확정 신호이고
  노이즈가 적다(매 편집 저장을 세면 부풀고, `/generate` 는 검증 클릭마다 돈다).
- **doctor 는 고치지 않고 제안만 한다.** `--fix` 도 같은 id 의 상위 버전 교체만 적용한다 —
  deprecated 를 타 컴포넌트로 바꾸는 건 능력이 겹쳐도 config 계약이 달라 조용히 깨진다.
  업그레이드 권고로는 CI 를 깨지 않는다(blocking = missing·deprecated 뿐).
- **`unpinned` 를 드리프트로 센다.** 버전을 안 박으면 카탈로그가 움직일 때마다 조용히 다른 걸
  쓴다 — 그 자체가 드리프트다. 레시피는 전부 핀을 박아 준다(테스트로 고정).
- **깨진 레시피는 없는 것보다 나쁘다.** 처음 쓰는 사람이 맨 먼저 만나는 게 레시피라, 3종 전부
  시드 카탈로그에서 resolve·gap 0 임을 테스트로 고정했다.

### 남은 것

- 랭킹 골든셋은 여전히 *선언값* 만 쓴다(`rank(usage=...)` 미주입) — 실사용 신호가 기준선을
  흔들면 회귀 판정이 재현 불가가 되기 때문이다. 신호 기반 품질 측정은 별도 트랙이 필요하다.
- 백로그 #2(공출현 → 랭킹)의 데이터 게이트는 이제 adopt·verify·eject 세 경로가 채운다.

## 의존성

**Phase 5**(eject 시점이 실사용 keep/drop 신호의 주 출처) · 카탈로그 `version`/`status`
필드(완료) · 랭킹 가중(완료). → 05 이후(P2).

## 검증 한계

프라이버시: 신호는 로컬 집계가 기본, 외부 전송은 명시 옵트인. 소량 데이터에서 `retention_score`
가 과적합하지 않도록 가중은 보수적으로(사용량 임계 이하 컴포넌트는 중립 처리) — 튜닝은 실데이터
누적 후 후속.
