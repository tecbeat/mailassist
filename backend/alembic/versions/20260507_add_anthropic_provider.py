"""Add anthropic to providertype enum.

Revision ID: 20260507_add_anthropic
Revises: 20260506_notification_channels
Create Date: 2026-05-07
"""

from alembic import op

revision = "20260507_add_anthropic"
down_revision = "20260506_notification_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providertype ADD VALUE IF NOT EXISTS 'anthropic'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; requires recreating the type.
    pass
