"""Add mail aggregate columns and mail_id FK to all plugin tables.

Phase 1 of the Mail Aggregate Refactor (#158).

New columns on tracked_emails:
    message_id, uidvalidity, recipient, body_excerpt, has_attachments,
    attachment_filenames, headers_subset, first_seen_uid, first_seen_folder.

New nullable mail_id FK (-> tracked_emails.id, ON DELETE CASCADE) on:
    email_summaries, detected_newsletters, extracted_coupons,
    extracted_otp_codes, applied_labels, assigned_folders, calendar_events,
    auto_reply_records, contact_assignments, spam_detection_results,
    ai_drafts, approvals.

Backfill: sets mail_id by joining each plugin table to tracked_emails
on (mail_account_id, mail_uid).  Rows with no matching tracked_email
are left with mail_id = NULL and counted in the migration output.

Revision ID: 20260512_mail_aggregate_phase1
Revises: 20260508_last_seen_version
Create Date: 2026-05-12
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260512_mail_aggregate_phase1"
down_revision = "20260508_last_seen_version"
branch_labels = None
depends_on = None

# Plugin tables that need mail_id + backfill.
# (table_name, uid_column_name) — most use "mail_uid", ai_drafts uses "original_mail_uid".
PLUGIN_TABLES = [
    ("email_summaries", "mail_uid"),
    ("detected_newsletters", "mail_uid"),
    ("extracted_coupons", "mail_uid"),
    ("extracted_otp_codes", "mail_uid"),
    ("applied_labels", "mail_uid"),
    ("assigned_folders", "mail_uid"),
    ("calendar_events", "mail_uid"),
    ("auto_reply_records", "mail_uid"),
    ("contact_assignments", "mail_uid"),
    ("spam_detection_results", "mail_uid"),
    ("ai_drafts", "original_mail_uid"),
    ("approvals", "mail_uid"),
]


def _column_exists(conn: sa.Connection, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # --- 1. New columns on tracked_emails ---
    te_new_columns = [
        ("message_id", sa.Column("message_id", sa.String(998), nullable=True)),
        ("uidvalidity", sa.Column("uidvalidity", sa.Integer(), nullable=True)),
        ("recipient", sa.Column("recipient", sa.String(320), nullable=True)),
        ("body_excerpt", sa.Column("body_excerpt", sa.Text(), nullable=True)),
        ("has_attachments", sa.Column("has_attachments", sa.Boolean(), nullable=True)),
        ("attachment_filenames", sa.Column("attachment_filenames", postgresql.JSON(), nullable=True)),
        ("headers_subset", sa.Column("headers_subset", postgresql.JSON(), nullable=True)),
        ("first_seen_uid", sa.Column("first_seen_uid", sa.String(100), nullable=True)),
        ("first_seen_folder", sa.Column("first_seen_folder", sa.String(500), nullable=True)),
    ]
    for col_name, col_def in te_new_columns:
        if not _column_exists(conn, "tracked_emails", col_name):
            op.add_column("tracked_emails", col_def)

    # Backfill first_seen_uid / first_seen_folder from existing data.
    conn.execute(
        sa.text(
            "UPDATE tracked_emails SET first_seen_uid = mail_uid, first_seen_folder = current_folder "
            "WHERE first_seen_uid IS NULL"
        )
    )

    # Partial unique constraint on (mail_account_id, message_id) where message_id is not null.
    conn.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_tracked_email_account_message_id "
            "ON tracked_emails (mail_account_id, message_id) WHERE message_id IS NOT NULL"
        )
    )
    # Index on message_id for lookups.
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_tracked_emails_message_id ON tracked_emails (message_id)"))

    # --- 2. Add mail_id to every plugin table + backfill ---
    for table_name, uid_col in PLUGIN_TABLES:
        if not _column_exists(conn, table_name, "mail_id"):
            op.add_column(
                table_name,
                sa.Column("mail_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
            op.create_foreign_key(
                f"fk_{table_name}_mail_id",
                table_name,
                "tracked_emails",
                ["mail_id"],
                ["id"],
                ondelete="CASCADE",
            )
            op.create_index(
                f"ix_{table_name}_mail_id",
                table_name,
                ["mail_id"],
            )

        # Backfill mail_id from tracked_emails.
        # For most tables the join is on (mail_account_id, mail_uid).
        # tracked_emails has a unique constraint on (mail_account_id, mail_uid, current_folder),
        # so we pick the most recently updated tracked_email if multiple folders exist.
        conn.execute(
            sa.text(f"""
                UPDATE {table_name} AS p
                SET mail_id = te.id
                FROM (
                    SELECT DISTINCT ON (mail_account_id, mail_uid)
                        id, mail_account_id, mail_uid
                    FROM tracked_emails
                    ORDER BY mail_account_id, mail_uid, updated_at DESC
                ) AS te
                WHERE p.mail_account_id = te.mail_account_id
                  AND p.{uid_col} = te.mail_uid
                  AND p.mail_id IS NULL
            """)
        )

        # Report orphans.
        result = conn.execute(sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE mail_id IS NULL"))
        orphan_count = result.scalar() or 0
        if orphan_count > 0:
            print(f"  [WARN] {table_name}: {orphan_count} rows have no matching tracked_email (mail_id = NULL)")


def _get_fk_constraint_name(conn: sa.Connection, table: str, column: str) -> str | None:
    """Find the actual FK constraint name for a column from the DB catalog."""
    result = conn.execute(
        sa.text("""
            SELECT tc.constraint_name
            FROM information_schema.key_column_usage kcu
            JOIN information_schema.table_constraints tc
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            WHERE kcu.table_name = :table
              AND kcu.column_name = :column
              AND tc.constraint_type = 'FOREIGN KEY'
            LIMIT 1
        """),
        {"table": table, "column": column},
    )
    row = result.fetchone()
    return row[0] if row else None


def downgrade() -> None:
    conn = op.get_bind()

    # Drop mail_id from plugin tables.
    for table_name, _ in reversed(PLUGIN_TABLES):
        if _column_exists(conn, table_name, "mail_id"):
            fk_name = _get_fk_constraint_name(conn, table_name, "mail_id")
            if fk_name:
                op.drop_constraint(fk_name, table_name, type_="foreignkey")
            op.drop_index(f"ix_{table_name}_mail_id", table_name)
            op.drop_column(table_name, "mail_id")

    # Drop new indexes on tracked_emails.
    conn.execute(sa.text("DROP INDEX IF EXISTS uq_tracked_email_account_message_id"))
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_tracked_emails_message_id"))

    # Drop new columns on tracked_emails.
    for col_name in [
        "message_id",
        "uidvalidity",
        "recipient",
        "body_excerpt",
        "has_attachments",
        "attachment_filenames",
        "headers_subset",
        "first_seen_uid",
        "first_seen_folder",
    ]:
        if _column_exists(conn, "tracked_emails", col_name):
            op.drop_column("tracked_emails", col_name)
