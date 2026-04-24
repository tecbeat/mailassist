"""Initial schema baseline.

Revision ID: 20260424_initial_schema
Revises: None
Create Date: 2026-04-24

Bootstraps the full database schema from the current SQLAlchemy model
metadata. This is the single baseline migration for mailassist; all future
schema changes should be added as incremental migrations on top of this one
via ``alembic revision --autogenerate``.
"""

from alembic import op

from app.models import Base

revision = "20260424_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create every table defined on ``Base.metadata``."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop every table defined on ``Base.metadata``."""
    Base.metadata.drop_all(bind=op.get_bind())
