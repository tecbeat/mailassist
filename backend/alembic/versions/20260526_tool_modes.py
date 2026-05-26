"""add tool_modes to user_settings

Revision ID: 20260526_tool_modes
Revises: 20260513_mail_aggregate_dedup
Create Date: 2026-05-26
"""

import sqlalchemy as sa
from alembic import op

revision = "20260526_tool_modes"
down_revision = "20260513_auto_approve_threshold"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_settings", sa.Column("tool_modes", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_settings", "tool_modes")
