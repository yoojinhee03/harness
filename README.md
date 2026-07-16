# AI 하네스 아키텍트 — 프로젝트 개요

> 여러 레포·문서를 하나로 묶는 상위 개요. 개별 레포의 실행법은 각 레포 README를,
> 설계 근거는 Notion 설계 문서를 본다.

## 무엇인가

프로젝트를 자연어로 설명하면 **하네스 구성요소(Skill · MCP · Context · Hook)를 추천**하고,
선택한 구성을 검증해 **실행 가능한 `harness.yaml`** 로 만들어 주는 도구.

"하네스"는 4개 요소의 고정된 정의가 아니라 모델을 감싸는 스캐폴딩 전체를 뜻하는 넓은
용어이고, 위 4개는 그중 MVP에서 프로젝트별로 조립·설정하는 표면이다.

### 핵심 가치
- **그라운딩된 추천** — 범용 생성이 아니라 실제 컴포넌트 카탈로그에 근거한다.
- **실행 가능한 설정** — 산출물이 문서가 아니라 그대로 도는 `harness.yaml`이다.
- **피드백 루프** — 무엇이 유지·폐기되는지 관찰해 카탈로그(=최우선 자산) 품질을 키운다.

### 스코프
- **In**: 카탈로그 기반 추천, `harness.yaml` 생성·검증, 피드백 루프.
- **Out**: 일반적인 아키텍처 생성(베이스 LLM이 잘 함), 서브에이전트(재귀 구조만 예약, 미래 확장).

## 아키텍처 (2계층)

저작 레이어가 "무엇을"을 정하고, 런타임 레이어가 "어떻게"를 실행한다.

```
[저작 레이어 — RAG]                         [런타임 레이어]
프로젝트 설명(자연어)
      │  ① 요구 능력 추출 (Claude)
      ▼
  카탈로그 검색 (임베딩 top-K)
      │  ② 랭킹·근거 (Claude)
      ▼
  구성요소 추천 ──선택──► harness.yaml ──► resolve() ──► ResolvedHarness
      ▲                    (선언)          검증·해석        (실행 명세)
      └──── gap 되돌림 ────────────────────────┘   │
         (화면 C→B)                                ▼
                                          build_request + 훅 엔진 → Anthropic API
```

리졸버는 순수 함수 파이프라인(참조 해소 → 상속 병합 → 능력 충족 → 충돌 감지 →
예산 확인 → 훅 순서 → 권한 수집)이며, gap(미충족 requires)은 에러가 아니라 추천기로
되돌리는 신호다.

## 프로젝트 구성 (한 레포, 두 프로젝트)

지금은 **한 레포 안에 두 프로젝트가 나란히** 있다(별도 git 레포·submodule 아님).

| 프로젝트 | 역할 | 내용 |
|------|------|------|
| **harness-architect** | 코드 (모노레포) | 백엔드(FastAPI) · 프론트(React) · `packages/`(resolver·catalog·runtime) |
| **harness-catalog** | 자산 (데이터) | `components/*.yaml` — 추천 대상 컴포넌트 레지스트리. 백엔드가 옆 폴더로 소비 |

코드 ↔ 자산의 수명주기를 분리한 결정: 프론트는 카탈로그를 직접 읽지 않고 API로만 보므로
FE/BE 분리가 카탈로그 분리를 강제하지 않는다. RAG 엔진 *코드*(`packages/catalog`)는 백엔드에
잔류하고 데이터만 폴더로 분리한다. 나중에 이 데이터 폴더만 별도 자산 레포로 떼어내 submodule로
마운트할 수 있게 경계는 유지한다(현재는 미적용).

```
harness/                       # 한 레포
├─ docker-compose.yml          # 풀스택 로컬 실행 진입점 (api + web + optional pgvector)
├─ .env.example                # compose 가 읽는 키·포트 (선택)
├─ harness-architect/          # 코드
│  ├─ Dockerfile               # 백엔드(FastAPI) 이미지
│  ├─ apps/{api, web}          # web/ 에 프론트 Dockerfile + nginx.conf
│  └─ packages/{resolver, catalog, runtime}
└─ harness-catalog/            # 자산 (백엔드가 ../harness-catalog/components 로 읽음)
   └─ components/*.yaml
```

## 기술 스택 (요약)

- **백엔드**: Python 3.12 · FastAPI · Pydantic v2 · anthropic SDK (Claude Sonnet 5)
- **RAG**: pgvector · Voyage AI 임베딩(스왑 가능, 로컬 폴백) · Claude 랭킹
- **프론트**: React · TypeScript · Vite · Tailwind · shadcn/ui · TanStack Query
- **툴링**: uv 워크스페이스 · ruff · mypy · pytest · GitHub Actions · docker-compose

## 실행 (Docker — 한 번에)

로컬 툴체인(uv·pnpm) 설치 없이 **레포 루트에서** 풀스택을 한 번에 띄운다. 백엔드
(FastAPI)와 프론트(정적 빌드를 nginx 로 서빙)를 각각 이미지로 굽고, 카탈로그 데이터
(`harness-catalog/components`)는 API 컨테이너에 읽기전용으로 마운트한다.

```bash
# 레포 루트(harness/)에서
docker compose up --build            # 최초 빌드 후 기동
```

- 브라우저에서 **http://localhost:8080** 접속 (프론트).
- 프론트의 `/api/*` 는 nginx 가 API 컨테이너(`:8000`)로 프록시한다 — 개발의 Vite 프록시와
  동일한 계약을 컨테이너에서 재현하므로 브라우저는 오리진 한 곳(`:8080`)만 본다.
- OpenAPI 문서는 **http://localhost:8000/docs**.

```bash
docker compose down                  # 정리 (DB 볼륨까지 지우려면 -v)
docker compose --profile pgvector up # + pgvector DB (MVP 는 인메모리라 평소엔 불필요)
```

키 없이도 로컬 임베딩/휴리스틱 폴백으로 전 구간이 돈다. 품질 모드는 루트에 `.env` 를 두고
`ANTHROPIC_API_KEY`·`VOYAGE_API_KEY` 를 넣으면 자동 활성(`cp .env.example .env`).

> **포트 충돌** — 기본 웹 `8080`·API `8000`. 이미 쓰는 스택이 있으면
> `WEB_PORT=9000 API_PORT=9001 docker compose up` 처럼 바꾼다(또는 `.env`).
> Vite 기본 포트(`5173`)는 다른 개발 서버가 점유한 경우가 많아 기본값에서 피했다.

## 실행 (로컬 — 네이티브 툴체인)

Docker 없이 직접 돌릴 때. 키 없이도 로컬 폴백으로 전 구간이 돈다. 터미널 2개로 백엔드·프론트를 띄운다.

```bash
# ① 백엔드 — harness-architect/ 에서
uv sync --all-packages --dev
uv run uvicorn harness_api.main:app --reload      # http://localhost:8000/docs

# ② 프론트 — harness-architect/apps/web/ 에서
corepack pnpm install
corepack pnpm dev                                 # http://localhost:5173
```

브라우저에서 **http://localhost:5173** 접속 → 상단 네비 **생성 / 카탈로그 / 대시보드**.
프론트의 `/api/*` 는 백엔드 `:8000` 으로 프록시된다. `5173` 이 사용 중이면 Vite 가 자동으로
다음 포트로 올린다(터미널의 URL 확인). 전체 실행·화면 흐름·품질 모드(`.env`) 상세는
[harness-architect/README.md](./harness-architect/README.md#빠른-시작).

## 설계 문서 (Notion "하네스 프로젝트")

- [기획: AI 하네스 아키텍트](https://app.notion.com/p/39636745494f81288fecdbe4dc491794)
- [설계: 카탈로그 스키마](https://app.notion.com/p/39636745494f81539a3bd9093d2e3ffe)
- [설계: 리졸버 검증 로직](https://app.notion.com/p/39636745494f817999c9d99f8dfbed9c)
- [설계: 화면 기획](https://app.notion.com/p/39636745494f8148960bdf10510bba36)
- [결정: 하네스 스코프](https://app.notion.com/p/39d36745494f81c0ae35f36d69589898)
- [설계: harness.yaml 스펙](https://app.notion.com/p/39d36745494f8133a34cf7538ae58c8d)
- [설계: 훅 실행 모델](https://app.notion.com/p/39d36745494f817081d0efef9b8149f4)
- [설계: 피드백 루프](https://app.notion.com/p/39d36745494f8152a8b3ebe53651d68b)
- [개발: 기술 스택](https://app.notion.com/p/39d36745494f8132869afccffe41d7b0)
- [카탈로그 시드 셋 (PR 리뷰 봇 경로)](https://app.notion.com/p/39d36745494f8156a5afe62f2b3fb353)

## 현재 상태 & 로드맵

- ✅ 설계 완료 (스코프·카탈로그 스키마·리졸버·harness.yaml 스펙·훅 실행 모델·피드백 루프·화면)
- ✅ 리졸버 슬라이스 — 8단계 파이프라인, 성공/gap/충돌/미지 테스트 통과
- ✅ RAG 추천 — 로컬 폴백으로 관통 (추출 → 검색 → 랭킹)
- ✅ RAG 실연동 — Voyage 임베더·Claude Reasoner 주입 가능(키 있으면 자동, 없으면 폴백)
- ✅ 런타임 — 빌더 + 훅 엔진(sandbox·timeout·권한 강제) + Anthropic 러너(dry_run), `POST /run`
- ✅ 프론트엔드 — 화면 A~F (생성 A~D · 카탈로그 E · 대시보드 F)
- ✅ 카탈로그 확장 — 10 컴포넌트 · 3 시나리오(PR 리뷰·이슈 분류·문서 초안)
- 🚧 하드닝 — 실 네트워크 호출(키 필요) · 훅 프로세스/WASM 격리 · pgvector 전환

> 진행 플랜과 단계별 완료 기준: `harness-architect/docs/plan/`. 검증: 백엔드 pytest 47 ·
> ruff/mypy 클린 · 프론트 build 통과.

## 용어

- **capability**: `domain.capability` 2레벨 통제 어휘 (예: `vcs.code-hosting`, `lifecycle.guardrail`).
- **gap**: 선택 집합이 채우지 못한 `requires`. 추천기로 되돌리는 신호이지 에러가 아니다.
- **harness.yaml**: 저작 레이어의 선언적 산출물이자 리졸버의 입력.
- **ResolvedHarness**: 리졸버가 검증·해석해 만든 실행 명세.