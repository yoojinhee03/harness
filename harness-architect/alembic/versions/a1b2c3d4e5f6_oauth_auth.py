"""oauth auth — 이메일(OAuth) 신원 + api_tokens 분리 (그린필드 리셋)

기존 handle/토큰=비밀번호 모델을 제거하고, 사람은 OAuth(이메일)로 로그인하며 자격증명은
api_tokens(세션 + PAT)로 분리한다. users 를 재생성하므로 기존 계정은 초기화된다(의도된 리셋).

Revision ID: a1b2c3d4e5f6
Revises: 11f898df57c9
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "11f898df57c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — users 를 OAuth 신원으로 재생성 + api_tokens 신설(그린필드)."""
    op.drop_index(op.f("ix_users_token_sha"), table_name="users")
    op.drop_table("users")

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("avatar_url", sa.String(length=512), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_sub", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_sub", name="uq_users_provider_sub"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("token_sha", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("last_used_at", sa.String(length=40), nullable=True),
        sa.Column("expires_at", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_api_tokens_user_id"), "api_tokens", ["user_id"], unique=False)
    op.create_index(op.f("ix_api_tokens_token_sha"), "api_tokens", ["token_sha"], unique=False)


def downgrade() -> None:
    """Downgrade — 이전(handle/token_sha) users 로 되돌리고 api_tokens 제거."""
    op.drop_index(op.f("ix_api_tokens_token_sha"), table_name="api_tokens")
    op.drop_index(op.f("ix_api_tokens_user_id"), table_name="api_tokens")
    op.drop_table("api_tokens")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("handle", sa.String(length=128), nullable=False),
        sa.Column("token_sha", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_token_sha"), "users", ["token_sha"], unique=False)
