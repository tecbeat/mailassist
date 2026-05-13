"""Tests for AI service utilities.

Covers: error classification (is_transient_llm_error, is_permanent_llm_error),
TransientLLMError / PermanentLLMError properties, _repair_json,
_parse_json_response, and _track_tokens.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai import (
    PermanentLLMError,
    TransientLLMError,
    _parse_json_response,
    _repair_json,
    _track_tokens,
    is_permanent_llm_error,
    is_transient_llm_error,
)

# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


class TestIsTransientLLMError:
    """Test transient error detection."""

    def test_timeout_class_name(self):
        exc = type("Timeout", (Exception,), {})()
        assert is_transient_llm_error(exc) is True

    def test_rate_limit_class_name(self):
        exc = type("RateLimitError", (Exception,), {})()
        assert is_transient_llm_error(exc) is True

    def test_api_connection_error(self):
        exc = type("APIConnectionError", (Exception,), {})()
        assert is_transient_llm_error(exc) is True

    def test_service_unavailable(self):
        exc = type("ServiceUnavailableError", (Exception,), {})()
        assert is_transient_llm_error(exc) is True

    def test_internal_server_error(self):
        exc = type("InternalServerError", (Exception,), {})()
        assert is_transient_llm_error(exc) is True

    def test_connection_error_builtin(self):
        assert is_transient_llm_error(ConnectionError("conn refused")) is True

    def test_timeout_error_builtin(self):
        assert is_transient_llm_error(TimeoutError("timed out")) is True

    def test_os_error_builtin(self):
        assert is_transient_llm_error(OSError("network unreachable")) is True

    def test_string_match_503(self):
        assert is_transient_llm_error(Exception("HTTP 503 service down")) is True

    def test_string_match_429(self):
        assert is_transient_llm_error(Exception("HTTP 429 too many requests")) is True

    def test_unrelated_error(self):
        assert is_transient_llm_error(ValueError("bad value")) is False


class TestIsPermanentLLMError:
    """Test permanent error detection."""

    def test_auth_error_class_name(self):
        exc = type("AuthenticationError", (Exception,), {})()
        assert is_permanent_llm_error(exc) is True

    def test_not_found_class_name(self):
        exc = type("NotFoundError", (Exception,), {})()
        assert is_permanent_llm_error(exc) is True

    def test_bad_request_class_name(self):
        exc = type("BadRequestError", (Exception,), {})()
        assert is_permanent_llm_error(exc) is True

    def test_permission_denied(self):
        exc = type("PermissionDeniedError", (Exception,), {})()
        assert is_permanent_llm_error(exc) is True

    def test_string_match_401(self):
        assert is_permanent_llm_error(Exception("HTTP 401 unauthorized")) is True

    def test_string_match_invalid_api_key(self):
        assert is_permanent_llm_error(Exception("invalid api key provided")) is True

    def test_string_match_model_not_found(self):
        assert is_permanent_llm_error(Exception("model not found: gpt-5")) is True

    def test_unrelated_error(self):
        assert is_permanent_llm_error(ValueError("bad value")) is False


# ---------------------------------------------------------------------------
# Custom exception properties
# ---------------------------------------------------------------------------


class TestTransientLLMError:
    """Test TransientLLMError.user_message property."""

    def test_user_message_no_original(self):
        err = TransientLLMError("something broke")
        assert err.user_message == "something broke"

    def test_user_message_with_original(self):
        orig = ConnectionError("conn refused")
        err = TransientLLMError("transient", original_error=orig)
        assert "ConnectionError" in err.user_message

    def test_user_message_with_message_attr(self):
        orig = MagicMock()
        orig.message = "rate limit exceeded"
        type(orig).__name__ = "RateLimitError"
        err = TransientLLMError("transient", original_error=orig)
        assert "rate limit exceeded" in err.user_message


class TestPermanentLLMError:
    """Test PermanentLLMError.user_message property."""

    def test_user_message_no_original(self):
        err = PermanentLLMError("auth failed")
        assert err.user_message == "auth failed"

    def test_user_message_with_original(self):
        orig = ValueError("invalid api key")
        err = PermanentLLMError("permanent", original_error=orig)
        assert "ValueError" in err.user_message


# ---------------------------------------------------------------------------
# _repair_json
# ---------------------------------------------------------------------------


class TestRepairJson:
    """Test JSON repair heuristics."""

    def test_trailing_comma(self):
        result = _repair_json('{"a": 1, "b": 2,}')
        assert '"a"' in result
        assert result.endswith("}")

    def test_single_quotes(self):
        result = _repair_json("{'key': 'value'}")
        assert '"key"' in result

    def test_unclosed_brace(self):
        result = _repair_json('{"a": 1')
        assert result.endswith("}")

    def test_unclosed_bracket(self):
        result = _repair_json("[1, 2")
        assert result.endswith("]")

    def test_unterminated_string(self):
        result = _repair_json('{"key": "value')
        # Should close the string
        assert result.count('"') % 2 == 0

    def test_valid_json_unchanged(self):
        import json

        original = '{"key": "value"}'
        result = _repair_json(original)
        assert json.loads(result) == {"key": "value"}

    def test_control_characters_removed(self):
        result = _repair_json('{"a": "b\x00c"}')
        assert "\x00" not in result


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    """Test LLM response JSON extraction."""

    def test_valid_json(self):
        result = _parse_json_response('{"label": "spam"}')
        assert result == {"label": "spam"}

    def test_markdown_code_block(self):
        text = '```json\n{"label": "spam"}\n```'
        result = _parse_json_response(text)
        assert result == {"label": "spam"}

    def test_embedded_json_in_text(self):
        text = 'Here is the result: {"label": "spam"} end'
        result = _parse_json_response(text)
        assert result == {"label": "spam"}

    def test_empty_response_raises(self):
        import json

        with pytest.raises(json.JSONDecodeError):
            _parse_json_response("")

    def test_whitespace_only_raises(self):
        import json

        with pytest.raises(json.JSONDecodeError):
            _parse_json_response("   ")

    def test_array_response(self):
        result = _parse_json_response("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_trailing_comma_repaired(self):
        text = '{"label": "spam",}'
        result = _parse_json_response(text)
        assert result == {"label": "spam"}


# ---------------------------------------------------------------------------
# _track_tokens
# ---------------------------------------------------------------------------


class TestTrackTokens:
    """Test token usage tracking in Valkey."""

    @pytest.mark.asyncio
    @patch("app.core.config.get_settings")
    @patch("app.services.ai.get_cache_client")
    async def test_increments_token_counter(self, mock_cache, mock_settings):
        settings = MagicMock()
        settings.ai_token_usage_ttl_days = 30
        mock_settings.return_value = settings

        cache = AsyncMock()
        cache.ttl = AsyncMock(return_value=-1)
        mock_cache.return_value = cache

        await _track_tokens("user-1", 100)

        cache.incrby.assert_called_once()
        assert cache.incrby.call_args[0][1] == 100

    @pytest.mark.asyncio
    async def test_zero_tokens_skipped(self):
        """Zero or negative tokens should not hit cache."""
        # Should return immediately without any cache calls
        await _track_tokens("user-1", 0)
        await _track_tokens("user-1", -5)
