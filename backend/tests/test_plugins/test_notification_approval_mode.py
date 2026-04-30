"""Tests for notification plugin approval_mode configuration."""

from app.models.user import ApprovalMode, UserSettings


def test_user_settings_approval_mode_notifications_default_is_auto() -> None:
    """New UserSettings rows must default to AUTO for notifications.

    The NotificationsPlugin declares supports_approval=False, so the
    'approval' mode is invalid for this column. The default must be
    AUTO to avoid a broken UI state on first login.
    """
    settings = UserSettings.__new__(UserSettings)
    col = UserSettings.__table__.c["approval_mode_notifications"]
    default = col.default.arg
    assert default == ApprovalMode.AUTO, (
        f"Expected default ApprovalMode.AUTO for approval_mode_notifications, got {default!r}"
    )


def test_notification_plugin_does_not_support_approval() -> None:
    """NotificationsPlugin must have supports_approval=False."""
    from app.plugins.notifications import NotificationsPlugin

    assert NotificationsPlugin.supports_approval is False
