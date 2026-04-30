"""User and user-settings models."""

import enum
from datetime import UTC, datetime
from uuid import uuid4
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, ForeignKey
from sqlalchemy.dialects.postgresql import JSON, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ApprovalMode(str, enum.Enum):
    """Approval mode for AI function plugins."""

    AUTO = "auto"
    APPROVAL = "approval"
    DISABLED = "disabled"


class User(Base):
    """User provisioned via SSO/OIDC."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    oidc_subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    mail_accounts: Mapped[list["MailAccount"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    ai_providers: Mapped[list["AIProvider"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    prompts: Mapped[list["Prompt"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    rules: Mapped[list["Rule"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    extracted_coupons: Mapped[list["ExtractedCoupon"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    detected_newsletters: Mapped[list["DetectedNewsletter"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    ai_drafts: Mapped[list["AIDraft"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    email_summaries: Mapped[list["EmailSummary"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    user_settings: Mapped["UserSettings | None"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    spam_blocklist_entries: Mapped[list["SpamBlocklistEntry"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    applied_labels: Mapped[list["AppliedLabel"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    assigned_folders: Mapped[list["AssignedFolder"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    calendar_events: Mapped[list["CalendarEvent"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    auto_reply_records: Mapped[list["AutoReplyRecord"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    contact_assignments: Mapped[list["ContactAssignment"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSettings(Base):
    """Per-user application settings (approval modes, defaults, timezone).

    ``max_concurrent_processing`` controls how many of the user's mails
    can be in ``PROCESSING`` status simultaneously.  The scheduler checks
    this limit before dispatching new jobs.
    """

    __tablename__ = "user_settings"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    default_polling_interval_minutes: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    draft_expiry_hours: Mapped[int] = mapped_column(Integer, default=168, nullable=False)
    max_concurrent_processing: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    ai_timeout_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    _approval_enum = Enum(ApprovalMode, values_callable=lambda e: [m.value for m in e], name="approvalmode")
    approval_mode_spam: Mapped[ApprovalMode] = mapped_column(_approval_enum, default=ApprovalMode.APPROVAL, nullable=False)
    approval_mode_labeling: Mapped[ApprovalMode] = mapped_column(_approval_enum, default=ApprovalMode.APPROVAL, nullable=False)
    approval_mode_smart_folder: Mapped[ApprovalMode] = mapped_column(_approval_enum, default=ApprovalMode.APPROVAL, nullable=False)
    approval_mode_newsletter: Mapped[ApprovalMode] = mapped_column(_approval_enum, default=ApprovalMode.APPROVAL, nullable=False)
    approval_mode_auto_reply: Mapped[ApprovalMode] = mapped_column(_approval_enum, default=ApprovalMode.APPROVAL, nullable=False)
    approval_mode_coupon: Mapped[ApprovalMode] = mapped_column(_approval_enum, default=ApprovalMode.APPROVAL, nullable=False)
    approval_mode_calendar: Mapped[ApprovalMode] = mapped_column(_approval_enum, default=ApprovalMode.APPROVAL, nullable=False)
    approval_mode_summary: Mapped[ApprovalMode] = mapped_column(_approval_enum, default=ApprovalMode.APPROVAL, nullable=False)
    approval_mode_rules: Mapped[ApprovalMode] = mapped_column(_approval_enum, default=ApprovalMode.APPROVAL, nullable=False)
    approval_mode_contacts: Mapped[ApprovalMode] = mapped_column(_approval_enum, default=ApprovalMode.APPROVAL, nullable=False)
    approval_mode_notifications: Mapped[ApprovalMode] = mapped_column(_approval_enum, default=ApprovalMode.AUTO, nullable=False)
    plugin_order: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
    plugin_provider_map: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="user_settings")
