"""catalog components — DB 백엔드 카탈로그(스케줄 harvest 적재, 서빙은 DB 읽기)

공식 MCP 레지스트리·플러그인 마켓플레이스에서 harvest 한 컴포넌트를 origin 별로 적재한다.
서빙 경로에서 네트워크를 제거하기 위한 테이블(catalog_store.CatalogStore 가 접근).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — catalog_components 신설(복합 PK origin+id)."""
    op.create_table(
        "catalog_components",
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("id", sa.String(length=256), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("origin", "id"),
    )
    op.create_index(op.f("ix_catalog_components_type"), "catalog_components", ["type"], unique=False)
    op.create_index(
        op.f("ix_catalog_components_updated_at"), "catalog_components", ["updated_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema — catalog_components 제거."""
    op.drop_index(op.f("ix_catalog_components_updated_at"), table_name="catalog_components")
    op.drop_index(op.f("ix_catalog_components_type"), table_name="catalog_components")
    op.drop_table("catalog_components")
