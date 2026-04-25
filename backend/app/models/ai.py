"""AI provider and prompt template models."""

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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ProviderType(str, enum.Enum):
    OPENAI = "openai"
    OLLAMA = "ollama"


class AIProvider(Base):
    """AI/LLM provider configuration per user.

    Health model
    ------------
    ``is_paused`` — provider is not available for processing.
    ``paused_reason`` — why it was paused:
        * ``"manually_paused"`` — user clicked Pause in the UI.
        * ``"circuit_breaker"`` — too many consecutive errors.
        * ``"transient_error:<plugin>"`` — transient LLM error during plugin.
    ``manually_paused`` — set when the user explicitly pauses via the UI;
                          skipped by auto-recovery so only the user can unpause.
    """

    __tablename__ = "ai_providers"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_type: Mapped[ProviderType] = mapped_column(Enum(ProviderType), nullable=False)
    api_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.3, nullable=False)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Health tracking
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Pause state (unified: manual pause, circuit breaker, transient errors)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manually_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    paused_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Legacy column kept for DB compat — always True, not used in code.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="ai_providers")


class Prompt(Base):
    """User-customizable Jinja2 prompt templates for AI functions."""

    __tablename__ = "prompts"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    function_type: Mapped[str] = mapped_column(String(50), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="prompts")

    __table_args__ = (
        UniqueConstraint("user_id", "function_type", name="uq_user_function_type"),
        Index("ix_prompts_user_id", "user_id"),
    )
