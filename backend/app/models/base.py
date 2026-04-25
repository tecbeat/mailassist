"""SQLAlchemy declarative base and shared utilities for all models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass
