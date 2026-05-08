"""Add last_seen_version to user_settings.

Revision ID: 20260508_last_seen_version
Revises: 20260507_calendar_past_events
Create Date: 2026-05-08
"""

import sqlalchemy as sa

from alembic import op

revision = "20260508_last_seen_version"
down_revision = "20260507_calendar_past_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'user_settings' AND column_name = 'last_seen_version'"
        )
    )
    if not result.fetchone():
        op.add_column(
            "user_settings",
            sa.Column("last_seen_version", sa.String(50), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("user_settings", "last_seen_version")
