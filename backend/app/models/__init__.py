"""SQLAlchemy ORM models for mailassist.

Re-exports all models from sub-modules so existing imports
(e.g. ``from app.models import User, MailAccount``) continue to work.
"""

from app.models.base import Base
from app.models.user import User, UserSettings, ApprovalMode
from app.models.mail import (
    CompletionReason,
    DraftStatus,
    ErrorType,
    MailAccount,
    AIDraft,
    EmailSummary,
    UrgencyLevel,
    DetectedNewsletter,
    ExtractedCoupon,
    AppliedLabel,
    AssignedFolder,
    CalendarEvent,
    AutoReplyRecord,
    ContactAssignment,
    SpamDetectionResult,
    TrackedEmailStatus,
    TrackedEmail,
)
from app.models.contacts import (
    Contact,
    CardDAVConfig,
    CalDAVConfig,
)
from app.models.ai import ProviderType, AIProvider, Prompt
from app.models.rules import ApprovalStatus, Approval, Rule
from app.models.notifications import SummaryFilterConfig, NotificationConfig
from app.models.spam import BlocklistEntryType, BlocklistSource, SpamBlocklistEntry
from app.models.reprocessing import (
    LabelChangeLog,
    FolderChangeLog,
)

__all__ = [
    "Base",
    # user
    "User",
    "UserSettings",
    "ApprovalMode",
    # mail
    "CompletionReason",
    "DraftStatus",
    "ErrorType",
    "MailAccount",
    "AIDraft",
    "EmailSummary",
    "UrgencyLevel",
    "DetectedNewsletter",
    "ExtractedCoupon",
    "AppliedLabel",
    "AssignedFolder",
    "CalendarEvent",
    "AutoReplyRecord",
    "ContactAssignment",
    "SpamDetectionResult",
    "TrackedEmailStatus",
    "TrackedEmail",
    # contacts / DAV
    "Contact",
    "CardDAVConfig",
    "CalDAVConfig",
    # ai
    "ProviderType",
    "AIProvider",
    "Prompt",
    # rules / approvals
    "ApprovalStatus",
    "Approval",
    "Rule",
    # notifications
    "SummaryFilterConfig",
    "NotificationConfig",
    # spam blocklist
    "BlocklistEntryType",
    "BlocklistSource",
    "SpamBlocklistEntry",
    # change logs
    "LabelChangeLog",
    "FolderChangeLog",
]
