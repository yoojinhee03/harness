"""gap_demand — durable gap 수요 집계 + provenance (하드닝 TASK 2)

인메모리 Counter(재시작 리셋·레플리카 개별)를 DB 테이블로 승격한다. provenance(catalog_revision·
caps_source·vocab_version·candidate_count)는 빈 caps 탓 거짓 gap 을 나중에 재평가·정화하기 위한 것.

Revision ID: d4e5f6a7b8c9
Revises: 5d5984e8d30c
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "5d5984e8d30c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — gap_demand 신설."""
    op.create_table(
        "gap_demand",
        sa.Column("capability", sa.String(length=128), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.String(length=40), nullable=False),
        sa.Column("last_seen_at", sa.String(length=40), nullable=False),
        sa.Column("suggested_type", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("resolved_at", sa.String(length=40), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("catalog_revision", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("caps_source", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("vocab_version", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("capability"),
    )


def downgrade() -> None:
    """Downgrade schema — gap_demand 제거."""
    op.drop_table("gap_demand")
