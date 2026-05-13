"""Add unique constraints on mail_id for single-row plugin tables.

Prevents duplicate plugin rows on re-processing.  Tables that produce
a list of rows per mail (coupons, OTP codes, applied labels) use
delete-then-reinsert in the persistence layer instead.

Revision ID: 20260513_mail_aggregate_dedup
Revises: 20260512_mail_aggregate_phase6
Create Date: 2026-05-13
"""

import sqlalchemy as sa

from alembic import op

revision = "20260513_mail_aggregate_dedup"
down_revision = "20260512_mail_aggregate_phase6"
branch_labels = None
depends_on = None

# (table, constraint_name)
_CONSTRAINTS = [
    ("detected_newsletters", "uq_newsletter_mail_id"),
    ("calendar_events", "uq_calendar_event_mail_id"),
    ("auto_reply_records", "uq_auto_reply_mail_id"),
    ("contact_assignments", "uq_contact_assignment_mail_id"),
]


def _constraint_exists(conn, table: str, name: str) -> bool:  # type: ignore[no-untyped-def]
    row = conn.execute(
        sa.text("SELECT 1 FROM information_schema.table_constraints WHERE table_name = :t AND constraint_name = :c"),
        {"t": table, "c": name},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()
    for table, name in _CONSTRAINTS:
        if not _constraint_exists(conn, table, name):
            # Remove duplicates first: keep the newest row per mail_id
            op.execute(
                sa.text(
                    f"""
                    DELETE FROM {table}
                    WHERE id NOT IN (
                        SELECT DISTINCT ON (mail_id) id
                        FROM {table}
                        ORDER BY mail_id, created_at DESC
                    )
                    """
                )
            )
            op.create_unique_constraint(name, table, ["mail_id"])


def downgrade() -> None:
    conn = op.get_bind()
    for table, name in _CONSTRAINTS:
        if _constraint_exists(conn, table, name):
            op.drop_constraint(name, table, type_="unique")
