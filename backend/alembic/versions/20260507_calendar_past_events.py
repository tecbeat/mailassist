"""Add include_past_events to caldav_configs.

Revision ID: 20260507_calendar_past_events
Revises: 20260507_add_anthropic
Create Date: 2026-05-07
"""

import sqlalchemy as sa

from alembic import op

revision = "20260507_calendar_past_events"
down_revision = "20260507_add_anthropic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Column may already exist if initial_schema used metadata.create_all()
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'caldav_configs' AND column_name = 'include_past_events'"
        )
    )
    if not result.fetchone():
        op.add_column(
            "caldav_configs",
            sa.Column("include_past_events", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    op.drop_column("caldav_configs", "include_past_events")
