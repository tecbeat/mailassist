"""Tests for notification approval_mode configuration."""

from app.models.user import ApprovalMode, UserSettings


def test_user_settings_approval_mode_notifications_default_is_auto() -> None:
    """New UserSettings rows must default to AUTO for notifications.

    The notifications column default must be AUTO to avoid a broken UI
    state on first login.
    """
    UserSettings.__new__(UserSettings)
    col = UserSettings.__table__.c["approval_mode_notifications"]
    default = col.default.arg
    assert default == ApprovalMode.AUTO, (
        f"Expected default ApprovalMode.AUTO for approval_mode_notifications, got {default!r}"
    )
