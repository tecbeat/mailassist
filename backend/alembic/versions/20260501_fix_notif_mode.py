"""Fix approval_mode_notifications default: approval -> auto.

Revision ID: 20260501_fix_notif_mode
Revises: 20260424_initial_schema
Create Date: 2026-05-01

The NotificationsPlugin declares supports_approval=False, so storing
'approval' as the default mode for notifications is incorrect. This
migration changes all existing rows that still have the wrong default
to 'auto', and the model default is updated to ApprovalMode.AUTO.
"""

from alembic import op

revision = "20260501_fix_notif_mode"
down_revision = "20260424_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE user_settings
        SET approval_mode_notifications = 'auto'
        WHERE approval_mode_notifications = 'approval'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE user_settings
        SET approval_mode_notifications = 'approval'
        WHERE approval_mode_notifications = 'auto'
        """
    )
