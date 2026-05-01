"""Tests for AI response parsing (test area 5).

Covers: valid JSON, invalid JSON with retry, partial JSON, empty response,
Pydantic validation errors, and token tracking.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from app.services.ai import _build_model_string, _track_tokens, call_llm


class SampleSchema(BaseModel):
    """Sample response schema for testing."""

    label: str
    confidence: float = Field(ge=0.0, le=1.0)


def _make_litellm_response(content: str, total_tokens: int = 50):
    """Build a mock litellm response object."""
    usage = MagicMock()
    usage.total_tokens = total_tokens

    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


class TestBuildModelString:
    """Test litellm model string construction."""

    def test_ollama_prefix(self):
        result = _build_model_string("ollama", "llama3.1")
        assert result == "ollama/llama3.1"

    def test_openai_no_prefix(self):
        result = _build_model_string("openai", "gpt-4o")
        assert result == "gpt-4o"

    def test_unknown_provider_no_prefix(self):
        result = _build_model_string("custom", "my-model")
        assert result == "my-model"


class TestCallLLMParsing:
    """Test area 5: AI response parsing via call_llm."""

    @pytest.mark.asyncio
    async def test_valid_json_response(self):
        """Valid JSON matching the schema is parsed and returned."""
        valid = json.dumps({"label": "work", "confidence": 0.9})
        mock_response = _make_litellm_response(valid, total_tokens=42)

        with (
            patch("app.services.ai.litellm.acompletion", new_callable=AsyncMock, return_value=mock_response),
            patch("app.services.ai._track_tokens", new_callable=AsyncMock),
        ):
            result, tokens = await call_llm(
                provider_type="openai",
                base_url="http://localhost",
                model_name="gpt-4o",
                api_key="test-key",
                system_prompt="Classify.",
                user_prompt="Test email body.",
                response_schema=SampleSchema,
                user_id="user-123",
            )

        assert isinstance(result, SampleSchema)
        assert result.label == "work"
        assert result.confidence == 0.9
        assert tokens == 42

    @pytest.mark.asyncio
    async def test_invalid_json_retries_once(self):
        """Invalid JSON on first attempt triggers a retry with corrective prompt."""
        invalid = "Not JSON at all"
        valid = json.dumps({"label": "spam", "confidence": 0.8})

        responses = [
            _make_litellm_response(invalid, total_tokens=10),
            _make_litellm_response(valid, total_tokens=30),
        ]
        call_count = 0

        async def mock_acompletion(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            return responses[idx]

        with (
            patch("app.services.ai.litellm.acompletion", side_effect=mock_acompletion),
            patch("app.services.ai._track_tokens", new_callable=AsyncMock),
        ):
            result, tokens = await call_llm(
                provider_type="openai",
                base_url="http://localhost",
                model_name="gpt-4o",
                api_key=None,
                system_prompt="Classify.",
                user_prompt="Body.",
                response_schema=SampleSchema,
            )

        assert result.label == "spam"
        # Both attempts' tokens are summed
        assert tokens == 40
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_invalid_json_both_attempts_raises(self):
        """If both attempts return invalid JSON, ValueError is raised."""
        invalid = "still not JSON"
        mock_resp = _make_litellm_response(invalid, total_tokens=5)

        with (
            patch("app.services.ai.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp),
            pytest.raises(ValueError, match="invalid output after retry"),
        ):
            await call_llm(
                provider_type="openai",
                base_url="",
                model_name="gpt-4o",
                api_key=None,
                system_prompt="X",
                user_prompt="Y",
                response_schema=SampleSchema,
            )

    @pytest.mark.asyncio
    async def test_partial_json_missing_field_retries(self):
        """JSON missing a required field triggers retry."""
        partial = json.dumps({"confidence": 0.5})  # missing 'label'
        valid = json.dumps({"label": "ok", "confidence": 0.6})

        responses = [
            _make_litellm_response(partial, total_tokens=8),
            _make_litellm_response(valid, total_tokens=12),
        ]
        call_count = 0

        async def mock_acompletion(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            return responses[idx]

        with (
            patch("app.services.ai.litellm.acompletion", side_effect=mock_acompletion),
            patch("app.services.ai._track_tokens", new_callable=AsyncMock),
        ):
            result, tokens = await call_llm(
                provider_type="openai",
                base_url="",
                model_name="gpt-4o",
                api_key=None,
                system_prompt="X",
                user_prompt="Y",
                response_schema=SampleSchema,
            )

        assert result.label == "ok"
        assert tokens == 20

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        """Empty string response from LLM raises ValueError after retry."""
        mock_resp = _make_litellm_response("", total_tokens=1)

        with (
            patch("app.services.ai.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp),
            pytest.raises(ValueError),
        ):
            await call_llm(
                provider_type="openai",
                base_url="",
                model_name="gpt-4o",
                api_key=None,
                system_prompt="X",
                user_prompt="Y",
                response_schema=SampleSchema,
            )

    @pytest.mark.asyncio
    async def test_validation_error_confidence_out_of_range(self):
        """Confidence > 1.0 fails Pydantic validation, triggers retry."""
        bad = json.dumps({"label": "x", "confidence": 5.0})
        good = json.dumps({"label": "x", "confidence": 0.7})

        responses = [
            _make_litellm_response(bad, total_tokens=5),
            _make_litellm_response(good, total_tokens=5),
        ]
        call_count = 0

        async def mock_acompletion(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            return responses[idx]

        with (
            patch("app.services.ai.litellm.acompletion", side_effect=mock_acompletion),
            patch("app.services.ai._track_tokens", new_callable=AsyncMock),
        ):
            result, _ = await call_llm(
                provider_type="openai",
                base_url="",
                model_name="gpt-4o",
                api_key=None,
                system_prompt="X",
                user_prompt="Y",
                response_schema=SampleSchema,
            )

        assert result.confidence == 0.7

    @pytest.mark.asyncio
    async def test_no_api_key_omits_param(self):
        """When api_key is None, it is not passed to litellm."""
        valid = json.dumps({"label": "test", "confidence": 0.5})
        mock_resp = _make_litellm_response(valid)

        with (
            patch("app.services.ai.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp) as mock_call,
            patch("app.services.ai._track_tokens", new_callable=AsyncMock),
        ):
            await call_llm(
                provider_type="ollama",
                base_url="http://localhost:11434",
                model_name="llama3.1",
                api_key=None,
                system_prompt="X",
                user_prompt="Y",
                response_schema=SampleSchema,
            )

        _, kwargs = mock_call.call_args
        assert "api_key" not in kwargs


class TestTokenTracking:
    """Token usage tracking in Valkey."""

    @pytest.mark.asyncio
    async def test_track_tokens_increments(self, mock_cache_client):
        """Token count is incremented in Valkey."""
        await _track_tokens("user-1", 100)

        # FakeValkey stores as strings
        keys = await mock_cache_client.keys()
        assert len(keys) == 1
        key = keys[0]
        assert key.startswith("token_usage:user-1:")
        value = await mock_cache_client.get(key)
        assert int(value) == 100

    @pytest.mark.asyncio
    async def test_track_tokens_zero_skips(self, mock_cache_client):
        """Zero tokens are not tracked (no Valkey write)."""
        await _track_tokens("user-1", 0)
        keys = await mock_cache_client.keys()
        assert len(keys) == 0

    @pytest.mark.asyncio
    async def test_track_tokens_negative_skips(self, mock_cache_client):
        """Negative tokens are not tracked."""
        await _track_tokens("user-1", -5)
        keys = await mock_cache_client.keys()
        assert len(keys) == 0
