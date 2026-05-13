"""Drop redundant content snapshot columns from plugin tables.

Phase 6 of the Mail Aggregate Refactor (#158).

With all plugin tables now referencing tracked_emails via mail_id FK,
the denormalised content columns (mail_subject, mail_from, mail_date,
sender_email) are redundant — this data lives on tracked_emails
(subject, sender, received_at).

Excluded:
    approvals — keeps mail_subject/mail_from/mail_date as immutable
                snapshots at approval-request time.

Revision ID: 20260512_mail_aggregate_phase6
Revises: 20260512_mail_aggregate_phase5
Create Date: 2026-05-12
"""

import sqlalchemy as sa

from alembic import op

revision = "20260512_mail_aggregate_phase6"
down_revision = "20260512_mail_aggregate_phase5"
branch_labels = None
depends_on = None

# (table, columns_to_drop)
COLUMNS_TO_DROP = [
    ("email_summaries", ["mail_subject", "mail_from", "mail_date"]),
    ("detected_newsletters", ["mail_subject"]),
    ("extracted_coupons", ["sender_email", "mail_subject"]),
    ("extracted_otp_codes", ["sender_email", "mail_subject"]),
    ("applied_labels", ["mail_subject", "mail_from"]),
    ("assigned_folders", ["mail_subject", "mail_from"]),
    ("calendar_events", ["mail_subject", "mail_from"]),
    ("auto_reply_records", ["mail_subject", "mail_from"]),
    ("contact_assignments", ["mail_subject", "mail_from"]),
    ("spam_detection_results", ["mail_subject", "mail_from"]),
]

INDEXES_TO_DROP = [
    ("ix_email_summaries_mail_date", "email_summaries"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Drop indexes first
    for idx_name, _table in INDEXES_TO_DROP:
        conn.execute(sa.text(f"DROP INDEX IF EXISTS {idx_name}"))

    # Drop columns (IF EXISTS for fresh-DB compatibility)
    for table, columns in COLUMNS_TO_DROP:
        for col in columns:
            conn.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}"))


def downgrade() -> None:
    # No-op: columns cannot be repopulated without original data.
    # Fresh-DB CI test never had these columns.
    pass
