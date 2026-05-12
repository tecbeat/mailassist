"""Make mail_id NOT NULL on all plugin tables.

Phase 4 of the Mail Aggregate Refactor (#158).

Deletes orphan rows (mail_id IS NULL) from plugin tables, then sets
mail_id to NOT NULL.  These orphans are plugin results whose parent
TrackedEmail was already deleted.

Revision ID: 20260512_mail_aggregate_phase4
Revises: 20260512_mail_aggregate_phase1
Create Date: 2026-05-12
"""

import sqlalchemy as sa

from alembic import op

revision = "20260512_mail_aggregate_phase4"
down_revision = "20260512_mail_aggregate_phase1"
branch_labels = None
depends_on = None

# All tables that received a mail_id FK in Phase 1.
TABLES = [
    "email_summaries",
    "detected_newsletters",
    "extracted_coupons",
    "extracted_otp_codes",
    "applied_labels",
    "assigned_folders",
    "calendar_events",
    "auto_reply_records",
    "contact_assignments",
    "spam_detection_results",
    "ai_drafts",
    "approvals",
]


def upgrade() -> None:
    conn = op.get_bind()

    for table in TABLES:
        # Delete orphan rows that could not be backfilled in Phase 1
        result = conn.execute(
            sa.text(f"DELETE FROM {table} WHERE mail_id IS NULL")  # noqa: S608
        )
        if result.rowcount:
            print(f"  {table}: deleted {result.rowcount} orphan rows")

        # Set NOT NULL
        op.alter_column(table, "mail_id", nullable=False)


def downgrade() -> None:
    for table in TABLES:
        op.alter_column(table, "mail_id", nullable=True)
