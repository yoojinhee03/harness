"""Alembic 환경 — harness_api.db 의 메타데이터로 마이그레이션.

DB URL 은 DATABASE_URL 환경변수를 우선한다(없으면 로컬 sqlite). 개발/테스트는 create_all 로
자동 생성하고, 프로덕션만 `alembic upgrade head` 로 이 마이그레이션을 적용한다.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from harness_api.db import metadata
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.environ.get("DATABASE_URL", "sqlite:///harness.db")
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
