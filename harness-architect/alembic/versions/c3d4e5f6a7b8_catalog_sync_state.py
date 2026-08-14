"""catalog sync state — 하이브리드 harvest(증분+주기 full)용 origin별 워터마크

증분 sync 의 updated_since 기준(watermark)과 마지막 full 대조 시각을 origin 별로 보관한다.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — catalog_sync_state 신설."""
    op.create_table(
        "catalog_sync_state",
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("watermark", sa.String(length=40), nullable=True),
        sa.Column("last_full_at", sa.String(length=40), nullable=True),
        sa.Column("last_sync_at", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("origin"),
    )


def downgrade() -> None:
    """Downgrade schema — catalog_sync_state 제거."""
    op.drop_table("catalog_sync_state")
