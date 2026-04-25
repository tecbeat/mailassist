"""Contact and DAV configuration models."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Contact(Base):
    """Cached contact from Nextcloud CardDAV."""

    __tablename__ = "contacts"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    carddav_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    emails: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    phones: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_vcard: Mapped[str] = mapped_column(Text, nullable=False)
    etag: Mapped[str] = mapped_column(String(255), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="contacts")

    __table_args__ = (
        UniqueConstraint("user_id", "carddav_uid", name="uq_user_carddav_uid"),
        Index("ix_contacts_user_id", "user_id"),
    )


class CardDAVConfig(Base):
    """CardDAV connection configuration for contact sync."""

    __tablename__ = "carddav_configs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    carddav_url: Mapped[str] = mapped_column(String(500), nullable=False)
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    address_book: Mapped[str] = mapped_column(String(255), nullable=False)
    sync_interval: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class CalDAVConfig(Base):
    """CalDAV connection configuration for calendar integration."""

    __tablename__ = "caldav_configs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    caldav_url: Mapped[str] = mapped_column(String(500), nullable=False)
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    default_calendar: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
