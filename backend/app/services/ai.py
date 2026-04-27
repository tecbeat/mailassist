"""AI service for LLM calls via litellm.

Provides a unified interface for calling different LLM providers (OpenAI, Ollama).
Handles structured output, retry on invalid JSON, token tracking, timeout,
and provider health tracking with circuit breaker support.
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import litellm
import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_cache_client
from app.models.ai import AIProvider
from app.core.types import ConnectionTestResult

logger = structlog.get_logger()

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


# ---------------------------------------------------------------------------
# Custom exception for transient LLM errors (connection, timeout, rate limit)
# ---------------------------------------------------------------------------

class TransientLLMError(Exception):
    """Raised when an LLM call fails due to a transient provider issue.

    These errors are retry-worthy and should trigger health tracking
    (increment consecutive_errors, check circuit breaker).
    """

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error

    @property
    def user_message(self) -> str:
        """Human-readable error for storage in last_error / display in UI."""
        orig = self.original_error
        if orig is None:
            return str(self)
        # litellm exceptions often wrap the real message in a chain like
        # "litellm.RateLimitError: RateLimitError: OpenAIException - ..."
        # Try to extract the final meaningful part.
        msg = str(orig)
        if hasattr(orig, "message"):
            msg = orig.message  # type: ignore[union-attr]
        return f"{type(orig).__name__}: {msg}"


class PermanentLLMError(Exception):
    """Raised when an LLM call fails due to a permanent config issue.

    These errors (e.g. invalid API key, model not found) will NOT resolve
    on their own and should not trigger circuit-breaker backoff.
    """

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error

    @property
    def user_message(self) -> str:
        """Human-readable error for storage in last_error / display in UI."""
        orig = self.original_error
        if orig is None:
            return str(self)
        msg = str(orig)
        if hasattr(orig, "message"):
            msg = orig.message  # type: ignore[union-attr]
        return f"{type(orig).__name__}: {msg}"


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

# litellm exception types that indicate transient (network/overload) issues
_TRANSIENT_ERROR_TYPES = (
    "APIConnectionError",
    "Timeout",
    "ServiceUnavailableError",
    "RateLimitError",
    "InternalServerError",
)

# litellm exception types that indicate permanent config issues
_PERMANENT_ERROR_TYPES = (
    "AuthenticationError",
    "NotFoundError",
    "BadRequestError",
    "PermissionDeniedError",
)


def is_transient_llm_error(exc: Exception) -> bool:
    """Check if an exception is a transient LLM provider error.

    Transient errors include network failures, timeouts, rate limits,
    and server errors (5xx). These may resolve on retry.
    """
    exc_type = type(exc).__name__
    if exc_type in _TRANSIENT_ERROR_TYPES:
        return True
    # Also catch generic connection errors
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    # litellm wraps many errors — check the string representation
    err_str = str(exc).lower()
    if any(kw in err_str for kw in ("timeout", "connection", "rate limit", "503", "502", "429")):
        return True
    return False


def is_permanent_llm_error(exc: Exception) -> bool:
    """Check if an exception is a permanent LLM config error.

    Permanent errors include invalid API keys, unknown models, and
    permission issues. These will NOT resolve on retry.
    """
    exc_type = type(exc).__name__
    if exc_type in _PERMANENT_ERROR_TYPES:
        return True
    err_str = str(exc).lower()
    if any(kw in err_str for kw in ("401", "403", "404", "invalid api key", "model not found")):
        return True
    return False


# ---------------------------------------------------------------------------
# Provider health tracking
# ---------------------------------------------------------------------------

async def update_provider_health(
    db: AsyncSession,
    provider_id: UUID,
    error: str | None = None,
) -> None:
    """Update AI provider health status after an LLM call.

    On success (error=None): resets consecutive_errors and last_error.
    On failure: increments consecutive_errors and records the error.

    Uses ``flush()`` instead of ``commit()`` so this function is safe to call
    inside a savepoint (``begin_nested``).  The caller — or the session's
    context manager — is responsible for committing.
    """
    now = datetime.now(UTC)
    if error:
        stmt = (
            update(AIProvider)
            .where(AIProvider.id == provider_id)
            .values(
                last_error=error[:2000],  # Truncate to avoid bloating the DB
                last_error_at=now,
                consecutive_errors=AIProvider.consecutive_errors + 1,
                updated_at=now,
            )
        )
    else:
        stmt = (
            update(AIProvider)
            .where(AIProvider.id == provider_id)
            .values(
                last_success_at=now,
                last_error=None,
                last_error_at=None,
                consecutive_errors=0,
                updated_at=now,
            )
        )
    await db.execute(stmt)
    await db.flush()


async def check_ai_circuit_breaker(
    db: AsyncSession,
    provider_id: UUID,
    max_errors: int = 5,
) -> bool:
    """Check if an AI provider should be disabled due to repeated failures.

    Returns True if the provider was disabled (circuit breaker tripped).
    Uses a lower threshold than mail accounts (5 vs 10) because LLM errors
    are more likely to indicate a systemic issue.
    """
    stmt = select(AIProvider).where(AIProvider.id == provider_id)
    result = await db.execute(stmt)
    provider = result.scalar_one_or_none()

    if provider and provider.consecutive_errors >= max_errors and not provider.is_paused:
        provider.is_paused = True
        provider.paused_reason = "circuit_breaker"
        provider.paused_at = datetime.now(UTC)
        await db.flush()
        logger.warning(
            "ai_circuit_breaker_tripped",
            provider_id=str(provider_id),
            provider_name=provider.name,
            consecutive_errors=provider.consecutive_errors,
        )
        return True

    return False


async def call_llm(
    provider_type: str,
    base_url: str,
    model_name: str,
    api_key: str | None,
    system_prompt: str,
    user_prompt: str,
    response_schema: type[BaseModel],
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout: int | None = None,
    user_id: str | None = None,
) -> tuple[BaseModel, int]:
    """Call an LLM and validate the response against a Pydantic schema.

    Returns the validated response and total token usage.
    Retries once if the response is invalid JSON.

    Args:
        max_tokens: Max response tokens. Defaults to ``settings.ai_max_tokens``.
        temperature: Sampling temperature. Defaults to ``settings.ai_temperature``.
        timeout: HTTP timeout in seconds. Defaults to ``settings.ai_timeout_seconds``.

    Raises:
        ValueError: If the LLM returns invalid output after retry.
        TransientLLMError: On transient provider errors (timeout, connection, rate limit).
        PermanentLLMError: On permanent config errors (auth, not found).
    """
    from app.core.config import get_settings

    settings = get_settings()
    max_tokens = max_tokens if max_tokens is not None else settings.ai_max_tokens
    temperature = temperature if temperature is not None else settings.ai_temperature
    timeout = timeout if timeout is not None else settings.ai_timeout_seconds
    # Build litellm model identifier
    model = _build_model_string(provider_type, model_name)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    optional_params: dict[str, Any] = {}
    if api_key:
        optional_params["api_key"] = api_key
    if base_url:
        optional_params["api_base"] = base_url

    total_tokens = 0

    for attempt in range(2):
        try:
            completion_kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout": timeout,
                **optional_params,
            }
            # Only use response_format for providers that support it reliably
            if provider_type.lower() not in ("ollama",):
                completion_kwargs["response_format"] = {"type": "json_object"}

            response = await litellm.acompletion(**completion_kwargs)

            content = response.choices[0].message.content
            usage = response.usage
            total_tokens += (usage.total_tokens if usage else 0)

            # Parse and validate -- try to extract JSON from markdown code blocks
            parsed = _parse_json_response(content)
            validated = response_schema.model_validate(parsed)

            # Track token usage in Valkey
            if user_id:
                await _track_tokens(user_id, usage.total_tokens if usage else 0)

            logger.info(
                "llm_call_success",
                model=model,
                tokens=usage.total_tokens if usage else 0,
                attempt=attempt + 1,
            )
            return validated, total_tokens

        except (json.JSONDecodeError, ValidationError) as e:
            if attempt == 0:
                # Retry with explicit JSON instruction
                logger.warning(
                    "llm_invalid_output_retrying",
                    model=model,
                    error=str(e),
                )
                messages.append({"role": "assistant", "content": content if "content" in locals() else ""})
                messages.append({
                    "role": "user",
                    "content": "Your response was not valid JSON matching the required schema. "
                    "Please respond with valid JSON only, matching the exact schema requested.",
                })
                continue
            logger.error(
                "llm_invalid_output_final",
                model=model,
                error=str(e),
                attempt=attempt + 1,
            )
            raise ValueError(f"LLM returned invalid output after retry: {e}") from e

        except Exception as e:
            # Classify the error as transient or permanent
            if is_transient_llm_error(e):
                logger.warning(
                    "llm_transient_error",
                    model=model,
                    error_type=type(e).__name__,
                    error=str(e),
                )
                raise TransientLLMError(
                    f"Transient LLM error ({type(e).__name__}): {e}",
                    original_error=e,
                ) from e
            elif is_permanent_llm_error(e):
                logger.error(
                    "llm_permanent_error",
                    model=model,
                    error_type=type(e).__name__,
                    error=str(e),
                )
                raise PermanentLLMError(
                    f"Permanent LLM error ({type(e).__name__}): {e}",
                    original_error=e,
                ) from e
            else:
                # Unknown error type — treat as transient to be safe
                logger.error(
                    "llm_unknown_error",
                    model=model,
                    error_type=type(e).__name__,
                    error=str(e),
                )
                raise TransientLLMError(
                    f"Unknown LLM error ({type(e).__name__}): {e}",
                    original_error=e,
                ) from e

    raise ValueError("LLM call failed after retries")


async def test_llm_connection(
    provider_type: str,
    base_url: str,
    model_name: str,
    api_key: str | None,
) -> ConnectionTestResult:
    """Test connectivity to an LLM provider.

    Sends a minimal prompt to verify the connection works.
    """
    model = _build_model_string(provider_type, model_name)

    optional_params: dict[str, Any] = {}
    if api_key:
        optional_params["api_key"] = api_key
    if base_url:
        optional_params["api_base"] = base_url

    try:
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=10,
            timeout=15,
            **optional_params,
        )
        content = response.choices[0].message.content
        return ConnectionTestResult(
            success=True,
            message=f"Connection successful. Model responded: {content[:50]}",
            details={"model": model},
        )
    except Exception as e:
        return ConnectionTestResult(
            success=False,
            message=f"Connection failed: {e}",
            details={"model": model},
        )


def _build_model_string(provider_type: str, model_name: str) -> str:
    """Build the litellm model identifier from provider type and model name.

    litellm uses prefixed model strings for routing, e.g. 'ollama/llama3.1'.
    OpenAI models don't need a prefix.
    """
    if provider_type == "ollama":
        return f"ollama/{model_name}"
    # OpenAI and compatible APIs use model name directly
    return model_name


def _repair_json(text: str) -> str:
    """Attempt to repair common JSON errors produced by LLMs.

    Handles: trailing commas, single quotes, unterminated strings,
    missing closing braces/brackets, and control characters.
    """
    import re

    # Remove control characters except \n, \r, \t
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    # Replace single quotes used as JSON delimiters with double quotes
    # (only when they look like JSON keys/values, not inside strings)
    # This is a heuristic: single-quoted keys like {'key': 'value'}
    cleaned = re.sub(r"(?<=[\[{,])\s*'([^']*?)'\s*:", r' "\1":', cleaned)
    cleaned = re.sub(r":\s*'([^']*?)'\s*(?=[,\]}])", r': "\1"', cleaned)

    # Remove trailing commas before } or ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

    # Try to fix unterminated strings: if the last non-whitespace before EOF
    # or before a closing brace is an open quote without a matching close,
    # add the closing quote
    # Detect unterminated strings by counting unescaped double quotes
    unescaped_quotes = len(re.findall(r'(?<!\\)"', cleaned))
    if unescaped_quotes % 2 == 1:
        # Odd number of quotes means an unterminated string — close it
        cleaned = cleaned.rstrip() + '"'

    # Close unclosed braces/brackets using a stack to preserve nesting order.
    _CLOSERS = {"{": "}", "[": "]"}
    in_string = False
    escape = False
    stack: list[str] = []
    for ch in cleaned:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in _CLOSERS:
            stack.append(_CLOSERS[ch])
        elif ch in ("}", "]"):
            if stack and stack[-1] == ch:
                stack.pop()

    if stack:
        cleaned += "".join(reversed(stack))

    return cleaned


def _parse_json_response(content: str) -> Any:
    """Parse JSON from LLM response, handling markdown code blocks and malformed output.

    Some models (especially Ollama) return free-text, markdown-wrapped, or
    slightly malformed JSON. This applies multiple extraction strategies
    and a repair step before giving up.
    """
    import re

    if not content or not content.strip():
        raise json.JSONDecodeError("Empty response", content or "", 0)

    text = content.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code blocks
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        extracted = match.group(1).strip()
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            # Try repairing the extracted block
            try:
                result = json.loads(_repair_json(extracted))
                logger.warning("json_repaired", strategy="markdown_block_repair")
                return result
            except json.JSONDecodeError:
                pass

    # Try finding the first { ... } or [ ... ] block
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start != -1:
            end = text.rfind(end_char)
            if end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    # Try repairing the extracted block
                    try:
                        result = json.loads(_repair_json(text[start:end + 1]))
                        logger.warning("json_repaired", strategy="brace_extraction_repair")
                        return result
                    except json.JSONDecodeError:
                        pass

    # Last resort: try repairing the full text
    try:
        result = json.loads(_repair_json(text))
        logger.warning("json_repaired", strategy="full_text_repair")
        return result
    except json.JSONDecodeError:
        pass

    # Fall through to original error for a clean traceback
    return json.loads(text)


async def _track_tokens(user_id: str, tokens: int) -> None:
    """Increment token usage counter in Valkey for dashboard aggregation."""
    if tokens <= 0:
        return
    try:
        cache = get_cache_client()
        from datetime import UTC, datetime
        from app.core.config import get_settings
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"token_usage:{user_id}:{today}"
        await cache.incrby(key, tokens)
        ttl_seconds = get_settings().ai_token_usage_ttl_days * 86400
        # Only set TTL when the key is new (no existing expiry) to avoid
        # resetting the sliding window on every increment.
        await cache.expire(key, ttl_seconds, nx=True)
    except Exception:
        logger.warning("token_tracking_failed", user_id=user_id)
