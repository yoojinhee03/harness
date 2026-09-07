"""component_approvals — 공유 카탈로그 승격의 다인 승인 (하드닝 후속 #5 잔여)

승격은 origin='promoted' 로 전 유저에게 노출되므로 단독 행위로 두면 공급망 위험이 크다.
grain = (스코프, 컴포넌트, 승인자) — 한 사람이 여러 번 승인해 정족수를 채울 수 없다.
component_version 을 함께 저장해 컴포넌트가 바뀌면 과거 승인이 무효화된다.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-07 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — component_approvals 신설."""
    op.create_table(
        "component_approvals",
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("component_id", sa.String(length=256), nullable=False),
        sa.Column("approver_id", sa.String(length=64), nullable=False),
        sa.Column("component_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("scope_key", "component_id", "approver_id"),
    )


def downgrade() -> None:
    """Downgrade schema — component_approvals 제거."""
    op.drop_table("component_approvals")
