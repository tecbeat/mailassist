"""Add plugin_results JSON column to tracked_emails.

Revision ID: 20260502_add_plugin_results
Revises: 20260501_fix_notif_mode
Create Date: 2026-05-02

Stores per-plugin execution results (status, display_name, summary,
details) so the queue UI can show detailed plugin outcomes.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260502_add_plugin_results"
down_revision = "20260501_fix_notif_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tracked_emails",
        sa.Column("plugin_results", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tracked_emails", "plugin_results")
