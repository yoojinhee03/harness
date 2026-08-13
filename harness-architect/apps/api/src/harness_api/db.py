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
