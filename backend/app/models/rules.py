"""Rule and approval models."""

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.mail import MailAccount
    from app.models.user import User


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    MANUAL_INPUT = "manual_input"


class Approval(Base):
    """Queue for AI actions requiring user confirmation."""

    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    function_type: Mapped[str] = mapped_column(String(50), nullable=False)
    mail_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    mail_subject: Mapped[str] = mapped_column(String(998), nullable=False)
    mail_from: Mapped[str] = mapped_column(String(320), nullable=False)
    proposed_action: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    edited_actions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ai_reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    ai_response_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    mail_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="approvals")
    mail_account: Mapped["MailAccount"] = relationship(back_populates="approvals")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "mail_account_id", "mail_uid", "function_type", name="uq_approval_user_account_mail_fn"
        ),
        Index("ix_approvals_user_id", "user_id"),
        Index("ix_approvals_status", "status"),
        Index("ix_approvals_mail_account_id", "mail_account_id"),
        Index("ix_approvals_expires_at", "expires_at"),
        Index("ix_approvals_function_type", "function_type"),
    )


class Rule(Base):
    """Structured mail processing rule."""

    __tablename__ = "rules"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    stop_processing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    match_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="rules")
    mail_account: Mapped["MailAccount | None"] = relationship(back_populates="rules")

    __table_args__ = (
        Index("ix_rules_user_id", "user_id"),
        Index("ix_rules_priority", "priority"),
        Index("ix_rules_mail_account_id", "mail_account_id"),
    )
