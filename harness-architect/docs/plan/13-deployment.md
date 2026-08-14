# Phase 13 — 배포 (추후 작업용 런북)

> 코드·이미지 파이프라인은 준비됨(`.github/workflows/deploy.yml`). 남은 건 **배포 타깃 선택**과
> **프로덕션 시크릿 주입** 뿐 — 둘 다 외부 결정이라 여기에 절차를 남긴다. 착수 시 이 문서대로.

## 지금 상태 (준비된 것)

- **이미지 빌드·푸시**: `deploy.yml` 이 태그(`v*`) 또는 수동 실행 시 API·web 이미지를 GHCR 로
  빌드·푸시한다(`ghcr.io/<owner>/harness-{api,web}`). 내장 `GITHUB_TOKEN` 사용 — 외부 시크릿 불필요.
- **런타임 설정**: 전부 env 로 주입 가능(아래 표). SQLite/인메모리 폴백이라 최소 구성으로도 뜬다.
- **DB 마이그레이션**: Alembic 준비됨 — `uv run alembic upgrade head`(§ 마이그레이션).
- **관측성/보안**: `/health`·`/ready`·`/metrics`, 요청 ID, 레이트리밋, CORS 기본거부, 키 배포-env 전용.

## 착수 시 결정할 것 (2개)

### 1) 배포 타깃 선택 → `deploy.yml` 의 `deploy` 잡 채우기

`deploy.yml` 의 `deploy` 잡은 골격이다. 타깃 하나를 골라 채운다:

- **Fly.io** — `superfly/flyctl-actions/setup-flyctl` + `flyctl deploy`. 시크릿: `FLY_API_TOKEN`.
  Postgres/Redis 는 `fly postgres`·`fly redis`(Upstash) 애드온.
- **Railway/Render** — 대시보드에서 GHCR 이미지 연결 + env 설정. CI 는 이미지 푸시까지만.
- **VPS(도커)** — `appleboy/ssh-action` 로 SSH 후 `docker compose pull && docker compose up -d`.
  compose 에 `DATABASE_URL`·`REDIS_URL` 지정(`--profile scale` 로 redis, `--profile pgvector` 로 pg).
  시크릿: `SSH_HOST`·`SSH_KEY`.
- **k8s** — `kubectl set image deploy/api api=ghcr.io/<owner>/harness-api:<tag>`. Secret/ConfigMap 로 env.

### 2) 프로덕션 시크릿 → repo Settings > Secrets (and variables)

| env | 용도 | 필수 |
|-----|------|:---:|
| `DATABASE_URL` | Postgres(`postgresql+psycopg://user:pw@host:5432/db`). 비우면 SQLite | 스케일 시 ✅ |
| `REDIS_URL` | SSE 스케일아웃(`redis://host:6379`). 비우면 인메모리(단일 인스턴스) | 워커≥2 시 ✅ |
| `ANTHROPIC_API_KEY` | Claude 랭킹·/run(품질 모드) | 선택 |
| `VOYAGE_API_KEY` | 임베딩 품질 모드 | 선택 |
| `SENTRY_DSN` | 에러 트래킹([sentry] extra) | 선택 |
| `HARNESS_CORS_ORIGINS` | 웹을 크로스 오리진으로 직접 노출할 때만(쉼표 구분) | 선택 |
| `HARNESS_RATELIMIT` | 기본 on. `off` 로 비활성 | 선택 |

> **이미지 extras**: 프로덕션 Postgres/Redis 를 쓰면 이미지에 `psycopg`·`redis` 가 필요하다.
> Dockerfile 의 `uv sync` 를 `--extra postgres --extra redis`(필요 시 `--extra sentry`)로 확장한다.

## 마이그레이션 (배포 파이프라인에 넣기)

- 최초/업데이트: 앱 기동 전에 `cd harness-architect && uv run alembic upgrade head`.
- 개발/테스트는 `create_all` 로 자동 생성(마이그레이션 불필요). 프로덕션만 alembic.
- 스키마 바꾸면: `uv run alembic revision --autogenerate -m "설명"` → 리뷰 → 커밋.

## 배포 전 체크리스트

- [ ] `deploy.yml` 의 `deploy` 잡을 타깃에 맞게 채움
- [ ] repo Secrets 에 프로덕션 env 입력
- [ ] Dockerfile `uv sync` 에 `--extra postgres --extra redis` 추가(Postgres/Redis 사용 시)
- [ ] Postgres 프로비저닝 + `alembic upgrade head`
- [ ] `HARNESS_CORS_ORIGINS` 를 실제 웹 오리진으로(또는 동일 오리진이면 비움)
- [ ] `/health`·`/ready` 를 LB 헬스체크에 연결, `/metrics` 를 Prometheus 스크레이프에
- [ ] `v0.1.0` 태그 푸시 → 이미지 자동 빌드 확인 → 배포 잡 동작 확인
