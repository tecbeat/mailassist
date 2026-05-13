from __future__ import annotations

import pytest

from app.core.exceptions import (
    AppError,
    AppValidationError,
    BadRequestError,
    ConflictError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    UnauthorizedError,
)

# ---------------------------------------------------------------------------
# AppError base class
# ---------------------------------------------------------------------------


class TestAppError:
    def test_defaults(self) -> None:
        exc = AppError("boom")
        assert exc.message == "boom"
        assert exc.status_code == 500
        assert exc.detail is None
        assert exc.code == "app"  # derived from "AppError" -> "App" -> "app"
        assert str(exc) == "boom"

    def test_custom_fields(self) -> None:
        exc = AppError("oops", status_code=418, detail="teapot", code="teapot")
        assert exc.status_code == 418
        assert exc.detail == "teapot"
        assert exc.code == "teapot"

    def test_is_exception(self) -> None:
        assert issubclass(AppError, Exception)


# ---------------------------------------------------------------------------
# 4xx errors
# ---------------------------------------------------------------------------


class TestBadRequestError:
    def test_defaults(self) -> None:
        exc = BadRequestError()
        assert exc.status_code == 400
        assert exc.message == "Bad request"
        assert exc.code == "bad_request"

    def test_custom_message(self) -> None:
        exc = BadRequestError("invalid payload")
        assert exc.message == "invalid payload"
        assert exc.status_code == 400


class TestUnauthorizedError:
    def test_defaults(self) -> None:
        exc = UnauthorizedError()
        assert exc.status_code == 401
        assert exc.message == "Unauthorized"
        assert exc.code == "unauthorized"

    def test_custom_message(self) -> None:
        exc = UnauthorizedError("token expired")
        assert exc.message == "token expired"


class TestForbiddenError:
    def test_defaults(self) -> None:
        exc = ForbiddenError()
        assert exc.status_code == 403
        assert exc.message == "Access denied"
        assert exc.code == "forbidden"

    def test_custom_message(self) -> None:
        exc = ForbiddenError("no access")
        assert exc.message == "no access"


class TestNotFoundError:
    def test_without_id(self) -> None:
        exc = NotFoundError("User")
        assert exc.status_code == 404
        assert exc.message == "User not found"
        assert exc.code == "not_found"

    def test_with_id(self) -> None:
        exc = NotFoundError("User", "abc-123")
        assert exc.message == "User 'abc-123' not found"
        assert exc.status_code == 404


class TestConflictError:
    def test_basic(self) -> None:
        exc = ConflictError("duplicate entry")
        assert exc.status_code == 409
        assert exc.message == "duplicate entry"
        assert exc.code == "conflict"


class TestAppValidationError:
    def test_basic(self) -> None:
        exc = AppValidationError("field X is required")
        assert exc.status_code == 422
        assert exc.message == "field X is required"
        assert exc.detail == "field X is required"
        assert exc.code == "validation_error"


class TestRateLimitError:
    def test_defaults(self) -> None:
        exc = RateLimitError()
        assert exc.status_code == 429
        assert exc.message == "Rate limit exceeded"
        assert exc.code == "rate_limit_exceeded"

    def test_custom_message(self) -> None:
        exc = RateLimitError("slow down")
        assert exc.message == "slow down"


# ---------------------------------------------------------------------------
# 5xx errors
# ---------------------------------------------------------------------------


class TestExternalServiceError:
    def test_basic(self) -> None:
        exc = ExternalServiceError("IMAP", "connection refused")
        assert exc.status_code == 502
        assert exc.message == "IMAP error: connection refused"
        assert exc.code == "external_service_error"


class TestServiceUnavailableError:
    def test_defaults(self) -> None:
        exc = ServiceUnavailableError()
        assert exc.status_code == 503
        assert exc.message == "Service temporarily unavailable"
        assert exc.code == "service_unavailable"

    def test_custom_message(self) -> None:
        exc = ServiceUnavailableError("maintenance")
        assert exc.message == "maintenance"


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls",
    [
        BadRequestError,
        UnauthorizedError,
        ForbiddenError,
        NotFoundError,
        ConflictError,
        AppValidationError,
        RateLimitError,
        ExternalServiceError,
        ServiceUnavailableError,
    ],
)
def test_all_subclass_app_error(cls: type) -> None:
    assert issubclass(cls, AppError)


# ---------------------------------------------------------------------------
# _default_code derivation
# ---------------------------------------------------------------------------


def test_default_code_derivation() -> None:
    """When no explicit code is given, it is derived from the class name."""
    exc = AppError("test")
    # "AppError" -> remove "Error" suffix -> "App" -> "app"
    assert exc.code == "app"
