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
    """Build a mock litellm response object with plain text (no tool calls)."""
    usage = MagicMock()
    usage.total_tokens = total_tokens

    message = MagicMock()
    message.content = content
    message.tool_calls = None

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _make_tool_call_response(func_args: dict, total_tokens: int = 50):
    """Build a mock litellm response with a submit_result tool call."""
    usage = MagicMock()
    usage.total_tokens = total_tokens

    tool_call = MagicMock()
    tool_call.function.name = "submit_result"
    tool_call.function.arguments = json.dumps(func_args)
    tool_call.id = "call_test123"

    message = MagicMock()
    message.content = None
    message.tool_calls = [tool_call]
    message.model_dump = lambda: {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_test123",
                "type": "function",
                "function": {"name": "submit_result", "arguments": json.dumps(func_args)},
            }
        ],
    }

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

    def test_anthropic_prefix(self):
        result = _build_model_string("anthropic", "claude-sonnet-4-20250514")
        assert result == "anthropic/claude-sonnet-4-20250514"


class TestCallLLMParsing:
    """Test area 5: AI response parsing via call_llm."""

    @pytest.mark.asyncio
    async def test_anthropic_no_response_format(self):
        """Anthropic calls must not include response_format."""
        mock_response = _make_tool_call_response({"label": "work", "confidence": 0.9}, total_tokens=10)

        with (
            patch(
                "app.services.ai.litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
            ) as mock_call,
            patch("app.services.ai._track_tokens", new_callable=AsyncMock),
        ):
            await call_llm(
                provider_type="anthropic",
                base_url="https://api.anthropic.com",
                model_name="claude-sonnet-4-20250514",
                api_key="sk-ant-test",
                system_prompt="Classify.",
                user_prompt="Test email body.",
                response_schema=SampleSchema,
                user_id="user-123",
            )

        kwargs = mock_call.call_args[1]
        assert "response_format" not in kwargs

    @pytest.mark.asyncio
    async def test_valid_json_response(self):
        """Valid tool call matching the schema is parsed and returned."""
        mock_response = _make_tool_call_response({"label": "work", "confidence": 0.9}, total_tokens=42)

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
        """Plain text on first attempt triggers retry; tool call on second succeeds."""
        responses = [
            _make_litellm_response("Not a tool call", total_tokens=10),
            _make_tool_call_response({"label": "spam", "confidence": 0.8}, total_tokens=30),
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
        """If all iterations return plain text, ValueError is raised."""
        mock_resp = _make_litellm_response("still not a tool call", total_tokens=5)

        with (
            patch("app.services.ai.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp),
            pytest.raises(ValueError, match="LLM failed to produce a valid result"),
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
        """Tool call with missing required field triggers retry."""
        responses = [
            _make_tool_call_response({"confidence": 0.5}, total_tokens=8),  # missing 'label'
            _make_tool_call_response({"label": "ok", "confidence": 0.6}, total_tokens=12),
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
        responses = [
            _make_tool_call_response({"label": "x", "confidence": 5.0}, total_tokens=5),
            _make_tool_call_response({"label": "x", "confidence": 0.7}, total_tokens=5),
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
        """When api_key is None, it is not passed to litellm. Ollama gets think=False and streaming."""
        mock_resp = _make_tool_call_response({"label": "test", "confidence": 0.5})

        async def _fake_stream(*args, **kwargs):
            yield MagicMock()

        with (
            patch("app.services.ai.litellm.acompletion", new_callable=AsyncMock, side_effect=_fake_stream) as mock_call,
            patch("app.services.ai.litellm.stream_chunk_builder", return_value=mock_resp),
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
        assert kwargs.get("think") is False
        assert kwargs.get("stream") is True


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
