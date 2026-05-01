"""Custom exception classes and FastAPI exception handlers.

Provides a hierarchy of application errors that map to HTTP status codes,
plus catch-all handlers to prevent stack-trace leakage in production.
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class AppError(Exception):
    """Base exception for application-level errors.

    Args:
        message: Human-readable error description.
        status_code: HTTP status code to return.
        detail: Optional extra detail for the response body.
        code: Machine-readable error code (e.g. ``"not_found"``).
    """

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        detail: str | None = None,
        code: str | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        self.code = code or self._default_code()
        super().__init__(message)

    def _default_code(self) -> str:
        """Derive a machine-readable code from the class name."""
        # e.g. NotFoundError -> not_found
        name = type(self).__name__.removesuffix("Error")
        return "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_")


# ---------------------------------------------------------------------------
# 4xx Errors
# ---------------------------------------------------------------------------


class BadRequestError(AppError):
    """Malformed or invalid request (400)."""

    def __init__(self, message: str = "Bad request"):
        super().__init__(message=message, status_code=400, code="bad_request")


class UnauthorizedError(AppError):
    """Authentication required or credentials invalid (401)."""

    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message=message, status_code=401, code="unauthorized")


class ForbiddenError(AppError):
    """Access denied to resource (403)."""

    def __init__(self, message: str = "Access denied"):
        super().__init__(message=message, status_code=403, code="forbidden")


class NotFoundError(AppError):
    """Resource not found (404)."""

    def __init__(self, resource: str, resource_id: str | None = None):
        msg = f"{resource} not found"
        if resource_id:
            msg = f"{resource} '{resource_id}' not found"
        super().__init__(message=msg, status_code=404, code="not_found")


class ConflictError(AppError):
    """Resource conflict, e.g. duplicate (409)."""

    def __init__(self, message: str):
        super().__init__(message=message, status_code=409, code="conflict")


class AppValidationError(AppError):
    """Business-logic validation failure (422).

    Named ``AppValidationError`` to avoid shadowing
    ``pydantic.ValidationError``.
    """

    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=422,
            detail=message,
            code="validation_error",
        )


class RateLimitError(AppError):
    """Rate limit exceeded (429)."""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message=message, status_code=429, code="rate_limit_exceeded")


# ---------------------------------------------------------------------------
# 5xx Errors
# ---------------------------------------------------------------------------


class ExternalServiceError(AppError):
    """External service (IMAP, CardDAV, LLM, etc.) unavailable or errored (502)."""

    def __init__(self, service: str, message: str):
        super().__init__(
            message=f"{service} error: {message}",
            status_code=502,
            code="external_service_error",
        )


class ServiceUnavailableError(AppError):
    """Service temporarily unavailable (503)."""

    def __init__(self, message: str = "Service temporarily unavailable"):
        super().__init__(
            message=message,
            status_code=503,
            code="service_unavailable",
        )


# ---------------------------------------------------------------------------
# Exception Handlers
# ---------------------------------------------------------------------------


def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers on the FastAPI app."""

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        # Log server errors at error level, client errors at warning
        if exc.status_code >= 500:
            logger.error(
                "app_error",
                status_code=exc.status_code,
                code=exc.code,
                message=exc.message,
            )
        else:
            logger.warning(
                "app_error",
                status_code=exc.status_code,
                code=exc.code,
                message=exc.message,
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.message,
                "detail": exc.detail,
                "code": exc.code,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """Catch-all for unexpected exceptions.

        Logs the full traceback but returns a generic message to the client
        to prevent stack-trace leakage in production.
        """
        logger.exception("unhandled_exception", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": None,
                "code": "internal_error",
            },
        )
