"""Change log models for label and folder tracking."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class LabelChangeLog(Base):
    """Tracks new labels created by AI for re-processing triggers."""

    __tablename__ = "label_change_logs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    mail_account: Mapped["MailAccount"] = relationship(back_populates="label_change_logs")

    __table_args__ = (
        Index("ix_label_change_logs_processed_at", "processed_at"),
        Index("ix_label_change_logs_user_id", "user_id"),
    )


class FolderChangeLog(Base):
    """Tracks new folders created by AI for re-processing triggers."""

    __tablename__ = "folder_change_logs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    mail_account_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("mail_accounts.id"), nullable=False)
    folder: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    mail_account: Mapped["MailAccount"] = relationship(back_populates="folder_change_logs")

    __table_args__ = (
        Index("ix_folder_change_logs_processed_at", "processed_at"),
        Index("ix_folder_change_logs_user_id", "user_id"),
    )
