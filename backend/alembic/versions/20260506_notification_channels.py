"""Add notification_channels table and remove legacy columns.

Revision ID: 20260506_notification_channels
Revises: 20260503_add_otp_codes
Create Date: 2026-05-06

Migrates from the flat apprise_urls + notify_on columns on
notification_configs to a dedicated notification_channels table
with per-URL routing by mail account and event type.
"""

import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "20260506_notification_channels"
down_revision = "20260503_add_otp_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)

    # 1. Create the new notification_channels table
    if not insp.has_table("notification_channels"):
        op.create_table(
            "notification_channels",
            sa.Column("id", PgUUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("user_id", PgUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("url", sa.String(1000), nullable=False),
            sa.Column("mail_account_ids", sa.JSON, nullable=True),
            sa.Column("event_types", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    # 2. Migrate existing apprise_urls into notification_channels
    if insp.has_table("notification_configs"):
        columns = {c["name"] for c in insp.get_columns("notification_configs")}
        if "apprise_urls" in columns:
            # Read existing configs and insert as channels
            conn.execute(
                text("""
                    INSERT INTO notification_channels (id, user_id, url, mail_account_ids, event_types, created_at, updated_at)
                    SELECT
                        gen_random_uuid(),
                        nc.user_id,
                        url_elem::text,
                        NULL,
                        NULL,
                        NOW(),
                        NOW()
                    FROM notification_configs nc,
                         LATERAL jsonb_array_elements_text(nc.apprise_urls::jsonb) AS url_elem
                    WHERE jsonb_array_length(nc.apprise_urls::jsonb) > 0
                """)
            )

            # 3. Drop legacy columns
            op.drop_column("notification_configs", "apprise_urls")

        if "notify_on" in columns:
            op.drop_column("notification_configs", "notify_on")


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)

    # Re-add legacy columns
    if insp.has_table("notification_configs"):
        columns = {c["name"] for c in insp.get_columns("notification_configs")}
        if "apprise_urls" not in columns:
            op.add_column("notification_configs", sa.Column("apprise_urls", sa.JSON, nullable=False, server_default="[]"))
        if "notify_on" not in columns:
            op.add_column("notification_configs", sa.Column("notify_on", sa.JSON, nullable=False, server_default="{}"))

    # Drop the new table
    if insp.has_table("notification_channels"):
        op.drop_table("notification_channels")
