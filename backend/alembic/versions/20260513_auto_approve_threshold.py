"""Add auto_approve_threshold to user_settings.

Allows users to configure a confidence score threshold above which
plugin actions are auto-approved without manual review.

Revision ID: 20260513_auto_approve_threshold
Revises: 20260513_mail_aggregate_dedup
Create Date: 2026-05-13
"""

import sqlalchemy as sa

from alembic import op

revision = "20260513_auto_approve_threshold"
down_revision = "20260513_mail_aggregate_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("auto_approve_threshold", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "auto_approve_threshold")
