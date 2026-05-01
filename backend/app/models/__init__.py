"""SQLAlchemy ORM models for mailassist.

Re-exports all models from sub-modules so existing imports
(e.g. ``from app.models import User, MailAccount``) continue to work.
"""

from app.models.ai import AIProvider, Prompt, ProviderType
from app.models.base import Base
from app.models.contacts import (
    CalDAVConfig,
    CardDAVConfig,
    Contact,
)
from app.models.mail import (
    AIDraft,
    AppliedLabel,
    AssignedFolder,
    AutoReplyRecord,
    CalendarEvent,
    CompletionReason,
    ContactAssignment,
    DetectedNewsletter,
    DraftStatus,
    EmailSummary,
    ErrorType,
    ExtractedCoupon,
    MailAccount,
    SpamDetectionResult,
    TrackedEmail,
    TrackedEmailStatus,
    UrgencyLevel,
)
from app.models.notifications import NotificationConfig, SummaryFilterConfig
from app.models.reprocessing import (
    FolderChangeLog,
    LabelChangeLog,
)
from app.models.rules import Approval, ApprovalStatus, Rule
from app.models.spam import BlocklistEntryType, BlocklistSource, SpamBlocklistEntry
from app.models.user import ApprovalMode, User, UserSettings

__all__ = [
    "AIDraft",
    "AIProvider",
    "AppliedLabel",
    "Approval",
    "ApprovalMode",
    # rules / approvals
    "ApprovalStatus",
    "AssignedFolder",
    "AutoReplyRecord",
    "Base",
    # spam blocklist
    "BlocklistEntryType",
    "BlocklistSource",
    "CalDAVConfig",
    "CalendarEvent",
    "CardDAVConfig",
    # mail
    "CompletionReason",
    # contacts / DAV
    "Contact",
    "ContactAssignment",
    "DetectedNewsletter",
    "DraftStatus",
    "EmailSummary",
    "ErrorType",
    "ExtractedCoupon",
    "FolderChangeLog",
    # change logs
    "LabelChangeLog",
    "MailAccount",
    "NotificationConfig",
    "Prompt",
    # ai
    "ProviderType",
    "Rule",
    "SpamBlocklistEntry",
    "SpamDetectionResult",
    # notifications
    "SummaryFilterConfig",
    "TrackedEmail",
    "TrackedEmailStatus",
    "UrgencyLevel",
    # user
    "User",
    "UserSettings",
]
