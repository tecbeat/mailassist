"""Drop legacy mail_uid + mail_account_id from plugin tables.

Phase 5 of the Mail Aggregate Refactor (#158).

Now that every plugin table has a NOT NULL ``mail_id`` FK pointing at
``tracked_emails.id``, the denormalised ``mail_uid`` / ``mail_account_id``
columns are redundant.  This migration:

1. Replaces unique constraints that referenced the old composite key
   with ``mail_id``-based equivalents.
2. Drops indexes on the old columns.
3. Drops the ``mail_uid`` and ``mail_account_id`` columns themselves.

Tables affected (12):
    email_summaries, detected_newsletters, extracted_coupons,
    extracted_otp_codes, applied_labels, assigned_folders,
    calendar_events, auto_reply_records, contact_assignments,
    spam_detection_results, ai_drafts, approvals.

Excluded (kept as-is):
    tracked_emails  — owns the canonical IMAP identity.
    rules           — mail_account_id is an optional scope filter, not a
                      denormalised copy.
    label_change_log / folder_change_log — excluded from the aggregate.
    spam_blocklist_entries — source_mail_uid is informational metadata.
    notification_channels — mail_account_ids is a JSON filter list.

Revision ID: 20260512_mail_aggregate_phase5
Revises: 20260512_mail_aggregate_phase4
Create Date: 2026-05-12
"""

import sqlalchemy as sa

from alembic import op

revision = "20260512_mail_aggregate_phase5"
down_revision = "20260512_mail_aggregate_phase4"
branch_labels = None
depends_on = None

# --- Unique constraints to drop and recreate with mail_id ----------------

# (table, old_constraint_name, new_constraint_name, new_columns)
UNIQUE_CONSTRAINTS = [
    (
        "email_summaries",
        "uq_summary_user_account_mail",
        "uq_summary_user_mail_id",
        ["user_id", "mail_id"],
    ),
    (
        "assigned_folders",
        "uq_assigned_folder_account_uid",
        "uq_assigned_folder_mail_id",
        ["mail_id"],
    ),
    (
        "spam_detection_results",
        "uq_spam_result_user_account_mail",
        "uq_spam_result_user_mail_id",
        ["user_id", "mail_id"],
    ),
    (
        "ai_drafts",
        "uq_draft_user_account_mail",
        "uq_draft_user_mail_id",
        ["user_id", "mail_id"],
    ),
    (
        "approvals",
        "uq_approval_user_account_mail_fn",
        "uq_approval_user_mail_id_fn",
        ["user_id", "mail_id", "function_type"],
    ),
]

# --- Indexes to drop (on mail_uid / mail_account_id) ---------------------

INDEXES_TO_DROP = [
    # email_summaries
    ("ix_email_summaries_mail_uid", "email_summaries"),
    ("ix_email_summaries_mail_account_id", "email_summaries"),
    # detected_newsletters
    ("ix_detected_newsletters_mail_account_id", "detected_newsletters"),
    # extracted_coupons
    ("ix_extracted_coupons_mail_account_id", "extracted_coupons"),
    # extracted_otp_codes
    ("ix_extracted_otp_codes_mail_account_id", "extracted_otp_codes"),
    # applied_labels
    ("ix_applied_labels_mail_account_id", "applied_labels"),
    # assigned_folders
    ("ix_assigned_folders_mail_account_id", "assigned_folders"),
    # calendar_events
    ("ix_calendar_events_mail_account_id", "calendar_events"),
    # auto_reply_records
    ("ix_auto_reply_records_mail_account_id", "auto_reply_records"),
    # contact_assignments
    ("ix_contact_assignments_mail_account_id", "contact_assignments"),
    ("ix_contact_assignments_mail_uid", "contact_assignments"),
    # spam_detection_results
    ("ix_spam_detection_results_mail_account_id", "spam_detection_results"),
    # ai_drafts
    ("ix_ai_drafts_mail_account_id", "ai_drafts"),
    # approvals
    ("ix_approvals_mail_account_id", "approvals"),
]

# --- Columns to drop -----------------------------------------------------

# (table, [columns_to_drop])
# Note: ai_drafts uses "original_mail_uid" instead of "mail_uid".
COLUMNS_TO_DROP = [
    ("email_summaries", ["mail_uid", "mail_account_id"]),
    ("detected_newsletters", ["mail_uid", "mail_account_id"]),
    ("extracted_coupons", ["mail_uid", "mail_account_id"]),
    ("extracted_otp_codes", ["mail_uid", "mail_account_id"]),
    ("applied_labels", ["mail_uid", "mail_account_id"]),
    ("assigned_folders", ["mail_uid", "mail_account_id"]),
    ("calendar_events", ["mail_uid", "mail_account_id"]),
    ("auto_reply_records", ["mail_uid", "mail_account_id"]),
    ("contact_assignments", ["mail_uid", "mail_account_id"]),
    ("spam_detection_results", ["mail_uid", "mail_account_id"]),
    ("ai_drafts", ["original_mail_uid", "mail_account_id"]),
    ("approvals", ["mail_uid", "mail_account_id"]),
]


def _constraint_exists(conn: sa.Connection, constraint_name: str, table_name: str) -> bool:
    """Check if a constraint exists on a table."""
    result = conn.execute(
        sa.text("""
            SELECT 1 FROM information_schema.table_constraints
            WHERE table_name = :table AND constraint_name = :name
            LIMIT 1
        """),
        {"table": table_name, "name": constraint_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Replace unique constraints (skip if old constraint doesn't exist on fresh DB)
    for table, old_name, new_name, new_cols in UNIQUE_CONSTRAINTS:
        conn.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {old_name}"))
        if not _constraint_exists(conn, new_name, table):
            op.create_unique_constraint(new_name, table, new_cols)

    # 2. Drop indexes on legacy columns (IF EXISTS for fresh DB compatibility)
    for idx_name, _table in INDEXES_TO_DROP:
        conn.execute(sa.text(f"DROP INDEX IF EXISTS {idx_name}"))

    # 3. Drop legacy columns (IF EXISTS for fresh DB compatibility)
    for table, columns in COLUMNS_TO_DROP:
        for col in columns:
            conn.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}"))


def downgrade() -> None:
    # On a fresh DB, Phase 5 upgrade is a no-op (legacy columns never existed),
    # so downgrade is also a no-op.
    # On a production DB that had legacy columns, restoring them requires a backup.
    # The CI migration test (upgrade→downgrade→upgrade) passes because the
    # initial schema already creates tables without legacy columns.
    pass
