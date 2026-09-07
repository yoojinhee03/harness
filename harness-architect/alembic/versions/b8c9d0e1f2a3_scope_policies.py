"""scope_policies — 스코프별 조직 정책 영속 (Phase 8 잔여)

정책이 요청 본문에서만 오면 클라이언트가 안 보내서 우회할 수 있다. 저장된 정책은 서버가 항상
적용하고 본문 정책과는 엄격한 쪽으로 합친다.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-07 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — scope_policies 신설."""
    op.create_table(
        "scope_policies",
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("doc", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("scope_key"),
    )


def downgrade() -> None:
    """Downgrade schema — scope_policies 제거."""
    op.drop_table("scope_policies")
