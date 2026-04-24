"""Mail account and mail-related data models."""

import enum
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UrgencyLevel(str, enum.Enum):
    """Urgency level for email summaries."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorType(str, enum.Enum):
    """Classification of processing errors on tracked emails."""

    PROVIDER_IMAP = "provider_imap"
    PROVIDER_AI = "provider_ai"
    MAIL = "mail"
    TIMEOUT = "timeout"


class CompletionReason(str, enum.Enum):
    """Why the processing pipeline ended for a tracked email."""

    FULL_PIPELINE = "full_pipeline"
    PARTIAL_WITH_ERRORS = "partial_with_errors"
    ALL_PLUGINS_FAILED = "all_plugins_failed"
    PIPELINE_DID_NOT_RUN = "pipeline_did_not_run"
    SPAM_SHORT_CIRCUIT = "spam_short_circuit"



class MailAccount(Base):
    """IMAP mail account linked to a user.

    Health model
    ------------
    ``is_paused`` — account is not available for processing.
    ``paused_reason`` — why it was paused:
        * ``"manually_paused"`` — user clicked Pause in the UI.
        * ``"circuit_breaker"`` — too many consecutive errors.
        * ``"transient_error"`` — transient IMAP/connection error.
    ``manually_paused`` — set when the user explicitly pauses via the UI;
                          skipped by auto-recovery so only the user can unpause.
    """

    __tablename__ = "mail_accounts"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email_address: Mapped[str] = mapped_column(String(320), nullable=False)
    imap_host: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, default=993, nullable=False)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    polling_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    polling_interval_minutes: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    idle_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    initial_scan_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scan_existing_emails: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    excluded_folders: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
    # Legacy column kept for DB compat — always True, not used in code.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Pause state (unified: manual pause, circuit breaker, transient errors)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manually_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    paused_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="mail_accounts")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    rules: Mapped[list["Rule"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    extracted_coupons: Mapped[list["ExtractedCoupon"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    detected_newsletters: Mapped[list["DetectedNewsletter"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    ai_drafts: Mapped[list["AIDraft"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    email_summaries: Mapped[list["EmailSummary"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    label_change_logs: Mapped[list["LabelChangeLog"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    folder_change_logs: Mapped[list["FolderChangeLog"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    applied_labels: Mapped[list["AppliedLabel"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    assigned_folders: Mapped[list["AssignedFolder"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    calendar_events: Mapped[list["CalendarEvent"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    auto_reply_records: Mapped[list["AutoReplyRecord"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")
    contact_assignments: Mapped[list["ContactAssignment"]] = relationship(back_populates="mail_account", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_mail_accounts_user_id", "user_id"),
    )


class DraftStatus(str, enum.Enum):
    ACTIVE = "active"
    USED = "used"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    DELETED = "deleted"


class AIDraft(Base):
    """Tracks AI-generated draft replies for cleanup."""

    __tablename__ = "ai_drafts"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    original_mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    original_message_id: Mapped[str] = mapped_column(String(500), nullable=False)
    draft_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    draft_message_id: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[DraftStatus] = mapped_column(Enum(DraftStatus), default=DraftStatus.ACTIVE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    cleaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="ai_drafts")
    mail_account: Mapped["MailAccount"] = relationship(back_populates="ai_drafts")

    __table_args__ = (
        UniqueConstraint("user_id", "mail_account_id", "original_mail_uid", name="uq_draft_user_account_mail"),
        Index("ix_ai_drafts_user_id", "user_id"),
        Index("ix_ai_drafts_status", "status"),
        Index("ix_ai_drafts_mail_account_id", "mail_account_id"),
    )


class EmailSummary(Base):
    """AI-generated email summaries."""

    __tablename__ = "email_summaries"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    mail_subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    mail_from: Mapped[str | None] = mapped_column(String(320), nullable=True)
    mail_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    urgency: Mapped[UrgencyLevel] = mapped_column(
        Enum(UrgencyLevel, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    action_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    action_description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="email_summaries")
    mail_account: Mapped["MailAccount"] = relationship(back_populates="email_summaries")

    __table_args__ = (
        UniqueConstraint("user_id", "mail_account_id", "mail_uid", name="uq_summary_user_account_mail"),
        Index("ix_email_summaries_user_id", "user_id"),
        Index("ix_email_summaries_mail_uid", "mail_uid"),
        Index("ix_email_summaries_mail_account_id", "mail_account_id"),
        Index("ix_email_summaries_mail_date", "mail_date"),
    )


class DetectedNewsletter(Base):
    """Newsletters detected by AI from incoming emails."""

    __tablename__ = "detected_newsletters"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    newsletter_name: Mapped[str] = mapped_column(String(200), nullable=False)
    sender_address: Mapped[str] = mapped_column(String(320), nullable=False)
    mail_subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    unsubscribe_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    has_unsubscribe: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="detected_newsletters")
    mail_account: Mapped["MailAccount"] = relationship(back_populates="detected_newsletters")

    __table_args__ = (
        Index("ix_detected_newsletters_user_id", "user_id"),
        Index("ix_detected_newsletters_mail_account_id", "mail_account_id"),
        Index("ix_detected_newsletters_sender_address", "sender_address"),
    )


class ExtractedCoupon(Base):
    """Coupon codes extracted from emails by AI."""

    __tablename__ = "extracted_coupons"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    sender_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    mail_subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    store: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="extracted_coupons")
    mail_account: Mapped["MailAccount"] = relationship(back_populates="extracted_coupons")

    __table_args__ = (
        Index("ix_extracted_coupons_user_id", "user_id"),
        Index("ix_extracted_coupons_expires_at", "expires_at"),
        Index("ix_extracted_coupons_mail_account_id", "mail_account_id"),
        Index("ix_extracted_coupons_active", "is_used", postgresql_where=text("is_used = false")),
    )


class AppliedLabel(Base):
    """Record of a label applied to an email by the labeling plugin."""

    __tablename__ = "applied_labels"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    mail_subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    mail_from: Mapped[str | None] = mapped_column(String(320), nullable=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    is_new_label: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="applied_labels")
    mail_account: Mapped["MailAccount"] = relationship(back_populates="applied_labels")

    __table_args__ = (
        Index("ix_applied_labels_user_id", "user_id"),
        Index("ix_applied_labels_label", "label"),
        Index("ix_applied_labels_mail_account_id", "mail_account_id"),
    )


class AssignedFolder(Base):
    """Record of an email moved to a folder by the smart folder plugin."""

    __tablename__ = "assigned_folders"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    mail_subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    mail_from: Mapped[str | None] = mapped_column(String(320), nullable=True)
    folder: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_new_folder: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="assigned_folders")
    mail_account: Mapped["MailAccount"] = relationship(back_populates="assigned_folders")

    __table_args__ = (
        UniqueConstraint("mail_account_id", "mail_uid", name="uq_assigned_folder_account_uid"),
        Index("ix_assigned_folders_user_id", "user_id"),
        Index("ix_assigned_folders_folder", "folder"),
        Index("ix_assigned_folders_mail_account_id", "mail_account_id"),
    )


class CalendarEvent(Base):
    """Calendar event extracted from an email by the calendar plugin."""

    __tablename__ = "calendar_events"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    mail_subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    mail_from: Mapped[str | None] = mapped_column(String(320), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    caldav_synced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    caldav_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    caldav_uid: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="calendar_events")
    mail_account: Mapped["MailAccount"] = relationship(back_populates="calendar_events")

    __table_args__ = (
        Index("ix_calendar_events_user_id", "user_id"),
        Index("ix_calendar_events_mail_account_id", "mail_account_id"),
    )


class AutoReplyRecord(Base):
    """Record of an auto-reply draft generated by the auto-reply plugin."""

    __tablename__ = "auto_reply_records"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    mail_subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    mail_from: Mapped[str | None] = mapped_column(String(320), nullable=True)
    draft_body: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="auto_reply_records")
    mail_account: Mapped["MailAccount"] = relationship(back_populates="auto_reply_records")

    __table_args__ = (
        Index("ix_auto_reply_records_user_id", "user_id"),
        Index("ix_auto_reply_records_mail_account_id", "mail_account_id"),
    )


class ContactAssignment(Base):
    """AI-assigned contact link for an email.

    Created by the contacts pipeline plugin when the AI matches an
    incoming email to an existing contact — or suggests creating a new
    one.  Stores the assignment alongside a confidence score and the
    AI's reasoning so the user can review it via the approval queue.
    """

    __tablename__ = "contact_assignments"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    mail_subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    mail_from: Mapped[str | None] = mapped_column(String(320), nullable=True)
    contact_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    reasoning: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_new_contact_suggestion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="contact_assignments")
    mail_account: Mapped["MailAccount"] = relationship(back_populates="contact_assignments")
    contact: Mapped["Contact | None"] = relationship()

    __table_args__ = (
        Index("ix_contact_assignments_user_id", "user_id"),
        Index("ix_contact_assignments_mail_account_id", "mail_account_id"),
        Index("ix_contact_assignments_contact_id", "contact_id"),
        Index("ix_contact_assignments_mail_uid", "mail_account_id", "mail_uid"),
    )


class SpamDetectionResult(Base):
    """Persisted spam detection results (AI and blocklist)."""

    __tablename__ = "spam_detection_results"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    mail_subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    mail_from: Mapped[str | None] = mapped_column(String(320), nullable=True)
    is_spam: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="ai")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship()
    mail_account: Mapped["MailAccount"] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "mail_account_id", "mail_uid", name="uq_spam_result_user_account_mail"),
        Index("ix_spam_detection_results_user_id", "user_id"),
        Index("ix_spam_detection_results_mail_account_id", "mail_account_id"),
        Index("ix_spam_detection_results_is_spam", "is_spam"),
    )


class TrackedEmailStatus(str, enum.Enum):
    """Processing status for a tracked email.

    Only 4 statuses exist.  The former ``PENDING`` status has been removed;
    new mails start directly as ``QUEUED``.  The "waiting for healthy
    provider" state is handled via pause flags on accounts/providers,
    not via a separate mail status.
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TrackedEmail(Base):
    """Unified tracking for every discovered email.

    Replaces the former ``processed_emails`` and ``failed_mails`` tables.
    PostgreSQL is the single source of truth -- Valkey/Redis loss cannot
    drop a mail.

    Status transitions (4-status lifecycle):
        queued     -> processing   (scheduler dispatches ARQ job)
        processing -> completed    (pipeline finished, auto-actions executed)
        processing -> failed       (permanent mail error)
        processing -> queued       (provider error — mail waits for recovery)
        failed     -> queued       (user triggered retry)
        completed  -> queued       (reprocessing: re-run pipeline)

    Note: PROCESSING is only set when the job enters the AI plugin
    pipeline (Phase 3).  During IMAP fetch and email parsing (Phases 1-2),
    the status remains QUEUED.

    Error classification (``error_type``):
        provider_imap — IMAP server unreachable (affects all mails on account)
        provider_ai   — LLM API unreachable (affects all mails for user)
        mail          — permanent mail-specific error (corrupt MIME, etc.)
        None          — no error
    """

    __tablename__ = "tracked_emails"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[TrackedEmailStatus] = mapped_column(
        Enum(TrackedEmailStatus, values_callable=lambda x: [e.value for e in x]),
        default=TrackedEmailStatus.QUEUED, nullable=False
    )
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender: Mapped[str | None] = mapped_column(String(320), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[ErrorType | None] = mapped_column(
        Enum(ErrorType, values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )

    # Pipeline completion tracking -- records which plugins ran, which
    # failed, and why the pipeline ended (full run, spam short-circuit,
    # partial with errors, etc.).
    plugins_completed: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
    plugins_failed: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
    plugins_skipped: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
    completion_reason: Mapped[CompletionReason | None] = mapped_column(
        Enum(CompletionReason, values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )

    # IMAP folder where the mail currently resides.  Updated whenever
    # the pipeline or approval executor moves the message to a different
    # folder so that re-processing fetches from the correct location.
    current_folder: Mapped[str] = mapped_column(String(500), default="INBOX", nullable=False, server_default="INBOX")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship()
    mail_account: Mapped["MailAccount"] = relationship()

    __table_args__ = (
        UniqueConstraint("mail_account_id", "mail_uid", "current_folder", name="uq_tracked_email_account_uid"),
        Index("ix_tracked_emails_user_id", "user_id"),
        Index("ix_tracked_emails_mail_account_id", "mail_account_id"),
        Index("ix_tracked_emails_status", "status"),
        Index("ix_tracked_emails_status_mail_account", "status", "mail_account_id"),
        Index("ix_tracked_emails_created_at", "created_at"),
    )
