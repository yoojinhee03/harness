# AI 하네스 아키텍트

프로젝트를 자연어로 설명하면 하네스 구성요소(Skill·MCP·Context·Hook)를 **추천**하고,
선택하면 실행 가능한 **harness.yaml**을 생성하는 도구. RAG 기반 추천(검색 후 랭킹) +
순수 함수 리졸버(검증·해석)로 구성된다. 설계 전문은 Notion "하네스 프로젝트" 참고.

## 구조 (한 레포 — 코드와 카탈로그 데이터를 프로젝트 폴더로만 분리)

지금은 **한 레포 안에 두 프로젝트가 나란히** 있다. `harness-architect`(코드)와
`harness-catalog`(데이터)는 별도 git 레포·submodule 이 아니라 같은 레포의 사이드바이사이드
디렉터리다. 백엔드 카탈로그 로더는 옆 폴더 `../harness-catalog/components` 를 기본으로 읽는다.
(설계상으로는 나중에 카탈로그를 별도 자산 레포로 떼어낼 수 있게 경계는 유지한다 — 코드는
`packages/catalog` 에 잔류하고 데이터만 이동.)

```
harness/                          # 한 레포
├─ harness-architect/             # 코드 (백엔드 + 프론트)
│  ├─ apps/
│  │  ├─ api/            FastAPI 백엔드 (/catalog, /recommend, /resolve)
│  │  └─ web/            React + TS + Tailwind (화면 A→B→C…)
│  ├─ packages/
│  │  ├─ resolver/       순수 함수 리졸버 (8단계 파이프라인, 테스트 통과) ✅
│  │  ├─ catalog/        카탈로그 엔진 + RAG (임베딩 검색 · 랭킹, 로컬 폴백으로 실행 가능)
│  │  └─ runtime/        빌더 + 훅 엔진 (스켈레톤)
│  └─ docs/              설계 문서 링크
└─ harness-catalog/               # 데이터 (자산)
   └─ components/*.yaml   시드 카탈로그 (4 컴포넌트, 4타입)
```

## 빠른 시작

카탈로그 데이터는 옆 폴더(`../harness-catalog/components`)를 자동으로 읽는다. 다른 위치에
두면 `export CATALOG_DIR=/path/to/harness-catalog/components`.

```bash
# harness-architect/ 에서 — 최초 1회 의존성 설치 + 테스트
uv sync --all-packages --dev
uv run pytest                            # 전체 (리졸버·카탈로그·API)
uv run pytest packages/resolver          # 리졸버만 (자체 완결형, 자산 비의존)
```

### 화면 확인 (터미널 2개)

```bash
# ① 백엔드 — harness-architect/ 에서
uv run uvicorn harness_api.main:app --reload      # http://localhost:8000/docs (OpenAPI)

# ② 프론트 — harness-architect/apps/web/ 에서
corepack pnpm install                             # pnpm 없으면 corepack 이 받아줌
corepack pnpm dev                                 # http://localhost:5173
```

- 브라우저에서 **http://localhost:5173** 접속. 프론트의 `/api/*` 요청은 자동으로 백엔드
  `:8000` 으로 프록시된다(`vite.config.ts`).
- `5173` 이 사용 중이면 Vite 가 자동으로 다음 포트(5174…)로 올린다 — 터미널에 찍힌 URL 을
  본다. 특정 포트로 고정하려면 `corepack pnpm dev -- --port 5188`.
- 화면 흐름: 상단 네비 **생성 / 카탈로그 / 대시보드**.
  - **생성** — A(설명, 예시 프롬프트 클릭) → "추천 받기" → B(추천·선택) → "검증하기" →
    C(진단, gap 시 B로 되돌림) → "확정 → 생성" → D(harness.yaml, 복사·대시보드 자동 저장).
  - **카탈로그(E)** — 컴포넌트 탐색·검색·타입/능력 필터·상세.
  - **대시보드(F)** — 생성한 하네스 목록·재열기.

```bash
# DB (RAG 확장 시 — pgvector). MVP 는 인메모리라 없어도 됨.
docker compose up -d db
```

> **풀스택을 도커로 한 번에** 띄우려면(백엔드+프론트, 툴체인 설치 없이) 레포 루트에서
> `docker compose up --build` → http://localhost:8080. 위 `docker compose up -d db` 는
> 네이티브 개발 중 DB 만 컨테이너로 쓰는 헬퍼다. 자세히는 루트 [README](../README.md#실행-docker--한-번에).

키 없이도 RAG 추천이 로컬 임베딩 폴백으로 돈다(기본). 품질 모드는 `.env` 에
`VOYAGE_API_KEY`(임베딩)·`ANTHROPIC_API_KEY`(추출·랭킹)를 넣으면 자동 활성 — `.env.example` 참고.

## 코드 ↔ 설계 문서 대응

| 코드 | 설계 문서 |
|------|-----------|
| `packages/resolver` (8단계) | 리졸버 검증 로직 §2·§3 |
| `packages/resolver/merge.py` | 리졸버 §4 + 훅 실행 모델 §6 |
| `packages/catalog/recommender.py` | 기획 §3.1 RAG 추천 엔진 |
| `packages/catalog/embeddings.py` | 개발: 기술 스택 (Voyage/스왑) |
| `packages/runtime/builder.py` | 기획 §3.2 런타임 빌더 + 훅 실행 모델 |
| `../harness-catalog/components/*.yaml` | 카탈로그 스키마 + 시드 셋 |
| `apps/api` 엔드포인트 | 화면 기획 A·B·C·E |

## 상태

- ✅ 리졸버: 성공/gap/충돌/미지 케이스 테스트 통과
- ✅ RAG 추천: 로컬 폴백으로 관통 (추출→검색→랭킹)
- ✅ RAG 실연동: Voyage 임베더 · Claude Reasoner 를 **주입 가능**하게(키 있으면 자동 활성,
  없으면 로컬 폴백). 진행 상세는 [docs/plan](./docs/plan/README.md).
- ✅ 런타임: 요청 빌더 + 훅 엔진(sandbox 실행기·timeout·권한 강제) + Anthropic 러너
  (키 없으면 dry_run). `POST /run` 으로 관통.
- ✅ 프론트엔드 화면 A~F (생성 스파인 A~D + 카탈로그 E + 대시보드 F).
- ✅ 카탈로그 확장: 10 컴포넌트(4타입, 다facet) · 3 시나리오(PR 리뷰·이슈 분류·문서 초안).
- 🚧 남은 하드닝: Voyage/Claude/Anthropic **실 네트워크 호출**(키 필요) · 훅 진짜 프로세스/
  WASM 격리 · pgvector 백엔드 전환.
- 📋 **v2 차별화 로드맵** — 다중 런타임 컴파일(`eject`)·프롬프트 관리·실행 전 프리뷰·역방향
  `adopt`·정책 as code·피드백 루프 활성화. `ResolvedHarness` IR 을 소스 오브 트루스로 두고
  아무 런타임으로나 내보낸다. 우선순위·의존성·완료 기준은 [docs/plan/](./docs/plan/README.md) 의 "v2" 섹션.

> 검증: 백엔드 pytest **47 통과** · ruff/mypy 클린 · 프론트 `pnpm build` 통과. 진행 플랜과
> 단계별 완료 기준은 [docs/plan/](./docs/plan/README.md).