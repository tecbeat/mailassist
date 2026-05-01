"""Spam blocklist model for sender/domain/pattern blocking."""

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class BlocklistEntryType(str, enum.Enum):
    """Type of blocklist entry."""

    EMAIL = "email"
    DOMAIN = "domain"
    PATTERN = "pattern"


class BlocklistSource(str, enum.Enum):
    """How the blocklist entry was created."""

    MANUAL = "manual"
    REPORTED = "reported"


class SpamBlocklistEntry(Base):
    """A blocked sender, domain, or subject pattern for spam filtering."""

    __tablename__ = "spam_blocklist"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    entry_type: Mapped[BlocklistEntryType] = mapped_column(
        Enum(BlocklistEntryType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(998), nullable=False)
    source: Mapped[BlocklistSource] = mapped_column(
        Enum(BlocklistSource, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    source_mail_uid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="spam_blocklist_entries")

    __table_args__ = (
        UniqueConstraint("user_id", "entry_type", "value", name="uq_spam_blocklist_user_type_value"),
        Index("ix_spam_blocklist_user_id", "user_id"),
        Index("ix_spam_blocklist_entry_type", "entry_type"),
        Index("ix_spam_blocklist_value", "value"),
    )
