"""component_cooccurrence — 컴포넌트 공출현 durable 집계 (하드닝 TASK 5e)

verify 등에서 한 하네스에 함께 등장한 컴포넌트 쌍의 빈도. 협업 필터링 신호(랭킹 투입은 후속).
쌍은 comp_a < comp_b(사전순)로 정규화해 대칭 중복을 없앤다.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — component_cooccurrence 신설."""
    op.create_table(
        "component_cooccurrence",
        sa.Column("comp_a", sa.String(length=256), nullable=False),
        sa.Column("comp_b", sa.String(length=256), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.String(length=40), nullable=False),
        sa.Column("last_seen_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("comp_a", "comp_b"),
    )


def downgrade() -> None:
    """Downgrade schema — component_cooccurrence 제거."""
    op.drop_table("component_cooccurrence")
