"""studio_conversations.draft_type VARCHAR(16→64) — 멀티초안 결합 타입 수용

초안 세트의 타입들을 콤마 결합(예: "context,hook,skill")으로 저장하면서 16자를 넘겼다. 모델은
String(64)로 바뀌었으나(065f3ee) 마이그레이션이 누락돼 alembic check 드리프트가 났다. 이를 정합.
SQLite(개발·프리플라이트)는 컬럼 타입 변경에 batch(테이블 재생성)가 필요하므로 batch_alter_table 사용.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """draft_type 16 → 64."""
    with op.batch_alter_table("studio_conversations") as batch_op:
        batch_op.alter_column(
            "draft_type",
            existing_type=sa.String(length=16),
            type_=sa.String(length=64),
            existing_nullable=False,
        )


def downgrade() -> None:
    """draft_type 64 → 16(값이 16 초과면 truncate 될 수 있음)."""
    with op.batch_alter_table("studio_conversations") as batch_op:
        batch_op.alter_column(
            "draft_type",
            existing_type=sa.String(length=64),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
