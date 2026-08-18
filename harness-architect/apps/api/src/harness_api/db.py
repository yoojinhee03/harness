"""DB 스키마·엔진 — 저장소 영속층(SQLAlchemy Core).

개발/테스트는 SQLite(파일), 프로덕션은 `DATABASE_URL` 로 Postgres. 같은 코드로 양쪽을 돈다
(SQLAlchemy 가 방언을 흡수). 파일 JSON 저장소 대비: 동시성 안전(트랜잭션)·영속·인덱스·스케일.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

# 사용자 = OAuth 신원(이메일). 토큰은 더 이상 users 에 안 둔다(api_tokens 로 분리).
# provider+provider_sub 로 공급자 계정을 유일 식별, email 은 표시·초대·복구용(유일).
users = Table(
    "users",
    metadata,
    Column("id", String(64), primary_key=True),  # uuid hex
    Column("email", String(320), nullable=False, unique=True, index=True),
    Column("name", String(128), nullable=False, default=""),
    Column("avatar_url", String(512), nullable=False, default=""),
    Column("provider", String(32), nullable=False),  # github | dev
    Column("provider_sub", String(128), nullable=False),  # 공급자 측 사용자 id
    Column("created_at", String(40), nullable=False),
    UniqueConstraint("provider", "provider_sub", name="uq_users_provider_sub"),
)

# 토큰 = 자격증명. 웹 세션(kind=session)과 VSCode/기계용 PAT(kind=pat)를 한 사용자에 여러 개.
# 발급/폐기가 서로 독립 — 설정에서 PAT 를 만들어도 웹 세션이 안 끊긴다(기존 단일토큰 모델의 결함 해소).
api_tokens = Table(
    "api_tokens",
    metadata,
    Column("id", String(64), primary_key=True),  # uuid hex
    Column("user_id", String(64), nullable=False, index=True),
    Column("kind", String(16), nullable=False),  # session | pat
    Column("name", String(128), nullable=False, default=""),
    Column("token_sha", String(64), nullable=False, index=True),
    Column("created_at", String(40), nullable=False),
    Column("last_used_at", String(40), nullable=True),
    Column("expires_at", String(40), nullable=True),
)

teams = Table(
    "teams",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("name", String(128), nullable=False),
    Column("owner_id", String(128), nullable=False),
)

team_members = Table(
    "team_members",
    metadata,
    Column("team_id", String(128), primary_key=True),
    Column("user_id", String(128), primary_key=True),
    Column("role", String(16), nullable=False, default="editor"),  # owner | editor | viewer
)

harnesses = Table(
    "harnesses",
    metadata,
    Column("scope", String(160), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("owner_id", String(128), nullable=False),
    Column("name", String(256), nullable=False),
    Column("description", Text, nullable=False, default=""),
    Column("yaml", Text, nullable=False),
    Column("version", Integer, nullable=False, default=1),
    Column("updated_at", String(40), nullable=False),
)

harness_versions = Table(
    "harness_versions",
    metadata,
    Column("scope", String(160), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("yaml", Text, nullable=False),
    Column("updated_at", String(40), nullable=False),
)

# 유저 저작 컴포넌트 — 채팅으로 만든 카탈로그 구성요소(v1: context). 하네스와 동일하게 스코프
# (`personal:<uid>` / `team:<tid>`)로 격리하고 버전 이력을 둔다. status 로 검증/테스트 게이트를 표현하고
# (draft→valid→ready), ready 만 팀 공유·위저드 사용 가능. `data` 는 Component 직렬화(JSON).
user_components = Table(
    "user_components",
    metadata,
    Column("scope", String(160), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("owner_id", String(128), nullable=False),
    Column("type", String(16), nullable=False, index=True),  # v1: context
    Column("name", String(256), nullable=False),
    Column("description", Text, nullable=False, default=""),
    Column("data", Text, nullable=False),  # Component.model_dump_json()
    Column("status", String(16), nullable=False, default="draft"),  # draft | valid | ready
    Column("version", Integer, nullable=False, default=1),  # 이력/낙관적락 카운터(컴포넌트 semver 와 별개)
    Column("updated_at", String(40), nullable=False),
)

user_component_versions = Table(
    "user_component_versions",
    metadata,
    Column("scope", String(160), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("data", Text, nullable=False),
    Column("updated_at", String(40), nullable=False),
)

# 스튜디오 대화 — 채팅으로 카탈로그 구성요소를 만드는/추천받는 대화 스레드(1급 객체). 하네스처럼
# 스코프(`personal:<uid>` / `team:<tid>`)로 격리한다. 대화당 산출물 1개: `draft`(현재 초안 Component
# JSON, "" = 없음) + `draft_type`(오케스트레이터가 추론한 타입). commit 하면 user_components 로 저장하고
# `component_id` 로 링크한다. `version` 은 초안 리비전 카운터(리파인마다 +1, diff 타임라인 근거).
studio_conversations = Table(
    "studio_conversations",
    metadata,
    Column("scope", String(160), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("owner_id", String(128), nullable=False),
    Column("title", String(256), nullable=False, default=""),  # 자동 생성(첫 턴 요약)
    Column("draft", Text, nullable=False, default=""),  # 현재 초안 Component.model_dump_json() ("" = 없음)
    Column("draft_type", String(16), nullable=False, default=""),  # context | skill | mcp | hook (추론)
    Column("component_id", String(128), nullable=True),  # commit 후 링크된 user_components.id
    Column("status", String(16), nullable=False, default="active"),  # active | committed
    Column("version", Integer, nullable=False, default=0),  # 초안 리비전(리파인 횟수)
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False, index=True),
)

# 스튜디오 메시지 — 대화의 턴 이력. `meta` 는 구조화 페이로드 JSON(intent/type 분류·추천 목록·초안
# 스냅샷·테스트 결과 등)이라 프런트가 인라인 카드로 렌더한다. 전역 자동증가 id 로 대화 내 순서를 잡는다.
studio_messages = Table(
    "studio_messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("scope", String(160), nullable=False, index=True),
    Column("conversation_id", String(128), nullable=False, index=True),
    Column("role", String(16), nullable=False),  # user | assistant
    Column("content", Text, nullable=False, default=""),  # 사람이 읽는 텍스트
    Column("meta", Text, nullable=False, default=""),  # 구조화 페이로드 JSON("" = 없음)
    Column("created_at", String(40), nullable=False),
)

# 앱(인스턴스) 레벨 LLM 설정 — 화면에서 등록하는 LLM/임베딩 키(at-rest 암호화). 서버 env 키는 안 쓴다.
# 단일 행(id='app'). 카탈로그 임베딩 인덱스가 전역이라 키도 인스턴스 단위(자체호스팅/단일조직 전제).
app_settings = Table(
    "app_settings",
    metadata,
    Column("id", String(16), primary_key=True),  # 항상 'app'
    Column("provider", String(16), nullable=False, default="anthropic"),  # LLM provider: anthropic | openai
    Column("llm_key_enc", Text, nullable=False, default=""),  # 선택 provider 의 LLM 키(Fernet 암호문)
    Column("embedding_key_enc", Text, nullable=False, default=""),  # OpenAI 임베딩 키
    Column("search_key_enc", Text, nullable=False, default="", server_default=""),  # 웹검색(Tavily) 키
    Column("updated_at", String(40), nullable=False),
)

# 카탈로그 컴포넌트 — 스케줄 harvest(MCP 레지스트리·마켓플레이스)가 origin 별로 적재하고,
# 서빙은 여기서 읽는다(네트워크 무의존·즉시·레플리카 공유·재시작 생존). data 는 Component 직렬화(JSON).
# 복합 PK(origin, id): 같은 id 가 서로 다른 origin 에서 와도 충돌 없이 각자 보관(읽을 때 dedup).
catalog_components = Table(
    "catalog_components",
    metadata,
    Column("origin", String(32), primary_key=True),  # registry | marketplace | local
    Column("id", String(256), primary_key=True),  # 컴포넌트 id(레지스트리 역DNS·마켓플레이스 이름 등)
    Column("type", String(16), nullable=False, index=True),  # skill | mcp | context | hook
    Column("name", String(256), nullable=False, default=""),
    Column("version", String(64), nullable=False, default=""),
    Column("data", Text, nullable=False),  # Component.model_dump_json() — 나머지 필드 전부
    Column("updated_at", String(40), nullable=False, index=True),
)

# harvest 스케줄 상태(origin별) — 하이브리드 sync 를 위한 워터마크·시각.
# watermark: 상류 updatedAt 최대치(다음 증분의 updated_since 기준). last_full_at: 마지막 full 대조.
# last_sync_at: 마지막 sync 시각(delta/full 무관) — 스케줄러 throttle 기준.
catalog_sync_state = Table(
    "catalog_sync_state",
    metadata,
    Column("origin", String(32), primary_key=True),
    Column("watermark", String(40), nullable=True),
    Column("last_full_at", String(40), nullable=True),
    Column("last_sync_at", String(40), nullable=True),
)


def resolve_database_url(store_dir: Path) -> str:
    """`DATABASE_URL`(프로덕션 Postgres) 또는 기본 SQLite(store 폴더 밑)."""
    env = os.environ.get("DATABASE_URL")
    if env:
        return env
    return f"sqlite:///{store_dir / 'harness.db'}"


def make_engine(url: str) -> Engine:
    # SQLite 는 FastAPI 멀티스레드 대응(check_same_thread=False). Postgres 는 기본 풀 사용.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
    metadata.create_all(engine)
    return engine
