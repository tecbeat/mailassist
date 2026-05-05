"""Add plugin_results JSON column to tracked_emails.

Revision ID: 20260502_add_plugin_results
Revises: 20260501_fix_notif_mode
Create Date: 2026-05-02

Stores per-plugin execution results (status, display_name, summary,
details) so the queue UI can show detailed plugin outcomes.

Note: The initial migration uses Base.metadata.create_all() which
creates all columns from the current model state. This column may
already exist — the guard prevents a DuplicateColumnError.
"""

from sqlalchemy import inspect, text

from alembic import op

revision = "20260502_add_plugin_results"
down_revision = "20260501_fix_notif_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    columns = [c["name"] for c in insp.get_columns("tracked_emails")]
    if "plugin_results" not in columns:
        op.execute(text("ALTER TABLE tracked_emails ADD COLUMN plugin_results JSON"))


def downgrade() -> None:
    op.drop_column("tracked_emails", "plugin_results")
