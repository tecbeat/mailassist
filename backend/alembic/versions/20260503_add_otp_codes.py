"""Add extracted_otp_codes table and approval_mode_otp column.

Revision ID: 20260503_add_otp_codes
Revises: 20260502_add_cancelled_reason
Create Date: 2026-05-03
"""

import sqlalchemy as sa

from alembic import op

revision = "20260503_add_otp_codes"
down_revision = "20260502_add_cancelled_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extracted_otp_codes",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "mail_account_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mail_accounts.id"),
            nullable=False,
        ),
        sa.Column("mail_uid", sa.String(100), nullable=False),
        sa.Column("sender_email", sa.String(320), nullable=True),
        sa.Column("mail_subject", sa.String(998), nullable=True),
        sa.Column("code", sa.String(2000), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("service", sa.String(100), nullable=True),
        sa.Column("code_type", sa.String(30), nullable=False),
        sa.Column("url", sa.String(2000), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_expired", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_extracted_otp_codes_user_id", "extracted_otp_codes", ["user_id"])
    op.create_index("ix_extracted_otp_codes_mail_account_id", "extracted_otp_codes", ["mail_account_id"])
    op.create_index("ix_extracted_otp_codes_expires_at", "extracted_otp_codes", ["expires_at"])
    op.create_index(
        "ix_extracted_otp_codes_active",
        "extracted_otp_codes",
        ["is_expired"],
        postgresql_where=sa.text("is_expired = false"),
    )

    op.add_column(
        "user_settings",
        sa.Column(
            "approval_mode_otp",
            sa.Enum("auto", "approval", "disabled", name="approvalmode", create_type=False),
            nullable=False,
            server_default="approval",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "approval_mode_otp")
    op.drop_index("ix_extracted_otp_codes_active", table_name="extracted_otp_codes")
    op.drop_index("ix_extracted_otp_codes_expires_at", table_name="extracted_otp_codes")
    op.drop_index("ix_extracted_otp_codes_mail_account_id", table_name="extracted_otp_codes")
    op.drop_index("ix_extracted_otp_codes_user_id", table_name="extracted_otp_codes")
    op.drop_table("extracted_otp_codes")
