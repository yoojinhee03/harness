"""component_feedback — 실사용 keep/drop 관측 durable 집계 (Phase 9 피드백 루프)

ranking 의 usage_count·retention_score 를 채우는 파이프의 저장소. 그 전엔 시드에서 전부 0 이라
두 가중이 상수처럼 죽어 있었다(랭킹 골든셋이 그 축을 못 재던 이유).

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-07 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — component_feedback 신설."""
    op.create_table(
        "component_feedback",
        sa.Column("component_id", sa.String(length=256), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dropped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.String(length=40), nullable=False),
        sa.Column("last_seen_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("component_id"),
    )


def downgrade() -> None:
    """Downgrade schema — component_feedback 제거."""
    op.drop_table("component_feedback")
