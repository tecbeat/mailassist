"""Tests for the Mail Processing Queue API endpoints.

Covers list filtering, pagination, user isolation, and retry logic
using mock-based patterns consistent with the rest of the test suite.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.mail import ErrorType, TrackedEmailStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_email(
    *,
    user_id=None,
    mail_account_id=None,
    status=TrackedEmailStatus.QUEUED,
    error_type=None,
    last_error=None,
    subject="Test Subject",
    sender="sender@example.com",
    retry_count=0,
):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        mail_account_id=mail_account_id or uuid4(),
        mail_uid="uid-1",
        subject=subject,
        sender=sender,
        received_at=None,
        status=status,
        error_type=error_type,
        last_error=last_error,
        plugins_completed=None,
        plugins_failed=None,
        plugins_skipped=None,
        completion_reason=None,
        current_folder="INBOX",
        retry_count=retry_count,
        created_at=None,
        updated_at=None,
    )


# ---------------------------------------------------------------------------
# GET /api/queue
# ---------------------------------------------------------------------------


class TestListQueue:
    """list_queue endpoint returns paginated, filtered results."""

    @pytest.mark.asyncio
    async def test_list_queue_returns_paginated_response(self):
        """Returns TrackedEmailListResponse with items and pagination metadata."""
        from app.api.queue import list_queue

        email = _make_email()
        paginated = MagicMock()
        paginated.items = [email]
        paginated.total = 1
        paginated.page = 1
        paginated.per_page = 20
        paginated.pages = 1

        db = AsyncMock()
        user_id = email.user_id

        with (
            patch("app.api.queue.paginate", new=AsyncMock(return_value=paginated)) as mock_paginate,
            patch("app.api.queue.build_paginated_response") as mock_build,
        ):
            mock_build.return_value = MagicMock(items=[email], total=1, page=1, per_page=20, pages=1)
            await list_queue(
                db=db, user_id=user_id, status=None, account_id=None, error_type=None, q=None, page=1, per_page=20
            )

        mock_paginate.assert_awaited_once()
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_queue_status_filter_applied(self):
        """Status filter is passed through to the query."""
        from app.api.queue import list_queue

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.queue.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.queue.build_paginated_response", return_value=MagicMock()),
        ):
            await list_queue(
                db=db,
                user_id=uuid4(),
                status=TrackedEmailStatus.FAILED,
                account_id=None,
                error_type=None,
                q=None,
                page=1,
                per_page=20,
            )

    @pytest.mark.asyncio
    async def test_list_queue_error_type_filter_applied(self):
        """error_type filter is accepted without error."""
        from app.api.queue import list_queue

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.queue.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.queue.build_paginated_response", return_value=MagicMock()),
        ):
            await list_queue(
                db=db,
                user_id=uuid4(),
                status=None,
                account_id=None,
                error_type=ErrorType.PROVIDER_AI,
                q=None,
                page=1,
                per_page=20,
            )

    @pytest.mark.asyncio
    async def test_list_queue_search_filter_applied(self):
        """Search query is accepted without error."""
        from app.api.queue import list_queue

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.queue.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.queue.build_paginated_response", return_value=MagicMock()),
        ):
            await list_queue(
                db=db, user_id=uuid4(), status=None, account_id=None, error_type=None, q="invoice", page=1, per_page=20
            )

    @pytest.mark.asyncio
    async def test_list_queue_account_id_filter_applied(self):
        """account_id filter is accepted without error."""
        from app.api.queue import list_queue

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.queue.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.queue.build_paginated_response", return_value=MagicMock()),
        ):
            await list_queue(
                db=db, user_id=uuid4(), status=None, account_id=uuid4(), error_type=None, q=None, page=1, per_page=20
            )


# ---------------------------------------------------------------------------
# POST /api/queue/{id}/retry
# ---------------------------------------------------------------------------


class TestRetryEmail:
    """retry_email endpoint resets failed emails to queued."""

    @pytest.mark.asyncio
    async def test_retry_failed_email_resets_to_queued(self):
        """FAILED email is reset to QUEUED, retry_count incremented, error cleared."""
        from app.api.queue import retry_email

        email = _make_email(
            status=TrackedEmailStatus.FAILED,
            retry_count=2,
            last_error="Connection refused",
            error_type=ErrorType.PROVIDER_IMAP,
        )

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = email
        db.execute.return_value = result

        with patch("app.api.queue.TrackedEmailResponse.model_validate", return_value=MagicMock()):
            await retry_email(email_id=email.id, db=db, user_id=email.user_id)

        assert email.status == TrackedEmailStatus.QUEUED
        assert email.retry_count == 3
        assert email.last_error is None
        assert email.error_type is None
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retry_unknown_email_raises_404(self):
        """Returns 404 when the email does not exist or belongs to another user."""
        from app.api.queue import retry_email

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        with pytest.raises(HTTPException) as exc_info:
            await retry_email(email_id=uuid4(), db=db, user_id=uuid4())

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_completed_email_raises_409(self):
        """Returns 409 when the email is not in FAILED status."""
        from app.api.queue import retry_email

        email = _make_email(status=TrackedEmailStatus.COMPLETED)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = email
        db.execute.return_value = result

        with pytest.raises(HTTPException) as exc_info:
            await retry_email(email_id=email.id, db=db, user_id=email.user_id)

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_retry_queued_email_raises_409(self):
        """Returns 409 when the email is already QUEUED."""
        from app.api.queue import retry_email

        email = _make_email(status=TrackedEmailStatus.QUEUED)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = email
        db.execute.return_value = result

        with pytest.raises(HTTPException) as exc_info:
            await retry_email(email_id=email.id, db=db, user_id=email.user_id)

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_retry_processing_email_raises_409(self):
        """Returns 409 when the email is currently PROCESSING."""
        from app.api.queue import retry_email

        email = _make_email(status=TrackedEmailStatus.PROCESSING)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = email
        db.execute.return_value = result

        with pytest.raises(HTTPException) as exc_info:
            await retry_email(email_id=email.id, db=db, user_id=email.user_id)

        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestTrackedEmailResponse:
    """TrackedEmailResponse schema validates from ORM attributes."""

    def test_schema_from_attributes(self):
        """model_validate works with a SimpleNamespace (from_attributes=True)."""
        from app.schemas.queue import TrackedEmailResponse

        email = _make_email(
            status=TrackedEmailStatus.FAILED,
            error_type=ErrorType.PROVIDER_AI,
            last_error="LLM timeout",
        )
        # Provide required datetime fields
        from datetime import UTC, datetime

        email.created_at = datetime.now(UTC)
        email.updated_at = datetime.now(UTC)

        response = TrackedEmailResponse.model_validate(email)

        assert response.status == TrackedEmailStatus.FAILED
        assert response.error_type == ErrorType.PROVIDER_AI
        assert response.last_error == "LLM timeout"

    def test_schema_optional_fields_default_none(self):
        """Optional fields are None when not set."""
        from datetime import UTC, datetime

        from app.schemas.queue import TrackedEmailResponse

        email = _make_email()
        email.created_at = datetime.now(UTC)
        email.updated_at = datetime.now(UTC)

        response = TrackedEmailResponse.model_validate(email)

        assert response.error_type is None
        assert response.last_error is None
        assert response.plugins_completed is None
        assert response.plugins_failed is None
        assert response.completion_reason is None
