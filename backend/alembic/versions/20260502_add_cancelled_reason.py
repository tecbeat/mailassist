"""Add 'cancelled' to completionreason enum.

Revision ID: 20260502_add_cancelled_reason
Revises: 20260502_add_plugin_results
Create Date: 2026-05-02
"""

from alembic import op

revision = "20260502_add_cancelled_reason"
down_revision = "20260502_add_plugin_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE completionreason ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; no-op.
    pass
