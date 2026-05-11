# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Gemini Retry Tests
==================

Tests for _call_with_retry() in gemini_adk.py.
Covers: success, retry logic, jitter, UI feedback, cancellation, error handling.

Run with: pytest tests/test_ai_agent/test_gemini_retry.py -v
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ai_agent.gemini_adk import (
    _call_with_retry,
    CancelledException,
    ThinkingRequiredError,
    MAX_RETRIES,
    RETRY_DELAY_BASE,
)


# =============================================================================
# Helpers
# =============================================================================

def _make_client(side_effects):
    """Create a mock Gemini client with given side_effects for generate_content."""
    client = MagicMock()
    client.models.generate_content.side_effect = side_effects
    return client


def _make_config():
    """Create a minimal mock generation config."""
    return MagicMock()


def _503_error(msg="503 The model is overloaded"):
    return Exception(msg)

def _400_error(msg="400 Bad Request: invalid argument"):
    return Exception(msg)

def _429_error(msg="429 Resource exhausted"):
    return Exception(msg)

def _500_error(msg="500 Internal Server Error"):
    return Exception(msg)


def _time_counter():
    """Return a function that returns increasing time values.

    Each call increments by 1000 so sleep loops always exit immediately.
    """
    counter = [0.0]
    def _time():
        counter[0] += 1000.0
        return counter[0]
    return _time


# Common patches for retry tests: mock time.time and time.sleep
# time.time returns increasing values so sleep loops exit immediately
# time.sleep is no-op
def _retry_patches():
    """Return decorator stack for common retry test patches."""
    return [
        patch("ai_agent.gemini_adk.time.sleep", return_value=None),
        patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter()),
    ]


# =============================================================================
# Test 1: Success on first attempt (on_chunk NOT called)
# =============================================================================

class TestRetrySuccess:
    """Tests for successful API calls."""

    def test_success_first_attempt(self):
        """on_chunk should NOT be called when first attempt succeeds."""
        expected_response = MagicMock()
        client = _make_client([expected_response])
        config = _make_config()
        on_chunk = MagicMock()

        result = _call_with_retry(client, "gemini-2.5-pro", "hello", config, on_chunk=on_chunk)

        assert result is expected_response
        client.models.generate_content.assert_called_once()
        on_chunk.assert_not_called()

    def test_success_returns_response(self):
        """Successful call returns the API response object."""
        expected_response = MagicMock()
        client = _make_client([expected_response])
        config = _make_config()

        result = _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        assert result is expected_response


# =============================================================================
# Test 2: 503 on 1st attempt, success on 2nd (retry works)
# =============================================================================

class TestRetryRecovery:
    """Tests for successful recovery after transient errors."""

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_503_then_success(self, mock_time, mock_sleep):
        """503 on first attempt, success on second -- retry should work."""
        expected_response = MagicMock()
        client = _make_client([_503_error(), expected_response])
        config = _make_config()

        result = _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        assert result is expected_response
        assert client.models.generate_content.call_count == 2

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_429_then_success(self, mock_time, mock_sleep):
        """429 rate limit on first attempt, success on second."""
        expected_response = MagicMock()
        client = _make_client([_429_error(), expected_response])
        config = _make_config()

        result = _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        assert result is expected_response
        assert client.models.generate_content.call_count == 2

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_500_then_success(self, mock_time, mock_sleep):
        """500 internal server error on first attempt, success on second."""
        expected_response = MagicMock()
        client = _make_client([_500_error(), expected_response])
        config = _make_config()

        result = _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        assert result is expected_response
        assert client.models.generate_content.call_count == 2


# =============================================================================
# Test 3: All retries exhausted -> user-friendly error message
# =============================================================================

class TestRetryExhausted:
    """Tests for exhausted retries."""

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_all_retries_exhausted_user_friendly_message(self, mock_time, mock_sleep):
        """When all retries are exhausted for 503, raise user-friendly error."""
        errors = [_503_error()] * (MAX_RETRIES + 1)
        client = _make_client(errors)
        config = _make_config()

        with pytest.raises(Exception, match="ueberlastet"):
            _call_with_retry(client, "gemini-3.1-pro-preview", "hello", config)

        assert client.models.generate_content.call_count == MAX_RETRIES + 1

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_exhausted_error_contains_model_name(self, mock_time, mock_sleep):
        """User-friendly error should contain model name and fallback hint."""
        errors = [_503_error()] * (MAX_RETRIES + 1)
        client = _make_client(errors)
        config = _make_config()

        with pytest.raises(Exception) as exc_info:
            _call_with_retry(client, "gemini-3.1-pro-preview", "hello", config)

        error_msg = str(exc_info.value)
        assert "gemini-3.1-pro-preview" in error_msg
        assert "gemini_flash" in error_msg
        assert str(MAX_RETRIES + 1) in error_msg

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_exhausted_non_503_raises_last_error(self, mock_time, mock_sleep):
        """When exhausted with 429 (no 503/UNAVAILABLE/overloaded match), raise last_error."""
        errors = [_429_error()] * (MAX_RETRIES + 1)
        client = _make_client(errors)
        config = _make_config()

        with pytest.raises(Exception) as exc_info:
            _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        # Should be the raw 429 error
        assert "429" in str(exc_info.value)
        assert client.models.generate_content.call_count == MAX_RETRIES + 1


# =============================================================================
# Test 4: on_chunk called from 2nd attempt onwards (not 1st)
# =============================================================================

class TestRetryUIFeedback:
    """Tests for UI feedback via on_chunk during retries."""

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_on_chunk_not_called_on_first_retry(self, mock_time, mock_sleep):
        """on_chunk should NOT be called on the first retry (attempt=0)."""
        expected_response = MagicMock()
        client = _make_client([_503_error(), expected_response])
        config = _make_config()
        on_chunk = MagicMock()

        _call_with_retry(client, "gemini-2.5-pro", "hello", config, on_chunk=on_chunk)

        # attempt=0 failed -> retry, but on_chunk only fires for attempt > 0
        on_chunk.assert_not_called()

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_on_chunk_called_on_second_retry(self, mock_time, mock_sleep):
        """on_chunk SHOULD be called starting from the second retry (attempt=1)."""
        expected_response = MagicMock()
        client = _make_client([_503_error(), _503_error(), expected_response])
        config = _make_config()
        on_chunk = MagicMock()

        _call_with_retry(client, "gemini-2.5-pro", "hello", config, on_chunk=on_chunk)

        assert on_chunk.call_count == 1
        call_args = on_chunk.call_args[0]
        assert "Retry" in call_args[0]
        assert call_args[1] is False  # is_thinking
        assert call_args[3] is None   # anon_stats

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_on_chunk_message_contains_predefined_text(self, mock_time, mock_sleep):
        """on_chunk message should contain predefined text, never raw error details."""
        expected_response = MagicMock()
        client = _make_client([
            _503_error("SECRET_ERROR_DETAILS_503"),
            _503_error("SECRET_ERROR_DETAILS_503"),
            expected_response
        ])
        config = _make_config()
        on_chunk = MagicMock()

        _call_with_retry(client, "gemini-2.5-pro", "hello", config, on_chunk=on_chunk)

        call_args = on_chunk.call_args[0]
        assert "Gemini API ueberlastet" in call_args[0]
        assert "SECRET_ERROR_DETAILS" not in call_args[0]


# =============================================================================
# Test 5: on_chunk=None causes no error
# =============================================================================

class TestRetryOnChunkNone:
    """Tests that on_chunk=None is handled gracefully."""

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_on_chunk_none_no_error(self, mock_time, mock_sleep):
        """When on_chunk is None, retries should still work without error."""
        expected_response = MagicMock()
        client = _make_client([_503_error(), _503_error(), expected_response])
        config = _make_config()

        result = _call_with_retry(client, "gemini-2.5-pro", "hello", config, on_chunk=None)

        assert result is expected_response
        assert client.models.generate_content.call_count == 3

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_on_chunk_default_parameter(self, mock_time, mock_sleep):
        """When on_chunk is not passed at all, retries should work."""
        expected_response = MagicMock()
        client = _make_client([_503_error(), expected_response])
        config = _make_config()

        result = _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        assert result is expected_response


# =============================================================================
# Test 6: Non-retryable error (400) is raised immediately
# =============================================================================

class TestNonRetryableErrors:
    """Tests that non-retryable errors are raised immediately."""

    def test_400_raises_immediately(self):
        """400 Bad Request should be raised immediately, no retry."""
        client = _make_client([_400_error()])
        config = _make_config()

        with pytest.raises(Exception, match="400 Bad Request"):
            _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        client.models.generate_content.assert_called_once()

    def test_thinking_required_raises_immediately(self):
        """ThinkingRequiredError should be raised immediately."""
        client = _make_client([Exception("Budget 0 is invalid")])
        config = _make_config()

        with pytest.raises(ThinkingRequiredError):
            _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        client.models.generate_content.assert_called_once()

    def test_generic_error_raises_immediately(self):
        """Generic errors should be raised immediately without retry."""
        client = _make_client([Exception("Something completely different")])
        config = _make_config()

        with pytest.raises(Exception, match="Something completely different"):
            _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        client.models.generate_content.assert_called_once()


# =============================================================================
# Test 7: Cancellation during retry sleep
# =============================================================================

class TestRetryCancellation:
    """Tests for cancellation during retry."""

    @patch("ai_agent.gemini_adk.time.sleep")
    def test_cancellation_during_retry_sleep(self, mock_sleep):
        """Cancellation during retry sleep should raise CancelledException."""
        client = _make_client([_503_error()])
        config = _make_config()

        call_count = 0
        def is_cancelled():
            nonlocal call_count
            call_count += 1
            # Let first checks pass (before API call, during futures wait)
            # then cancel during the retry sleep loop
            return call_count > 3

        with pytest.raises(CancelledException):
            _call_with_retry(client, "gemini-2.5-pro", "hello", config, is_cancelled=is_cancelled)

    def test_cancellation_before_api_call(self):
        """Cancellation before API call should raise CancelledException."""
        client = _make_client([MagicMock()])
        config = _make_config()

        is_cancelled = MagicMock(return_value=True)

        with pytest.raises(CancelledException):
            _call_with_retry(client, "gemini-2.5-pro", "hello", config, is_cancelled=is_cancelled)

        client.models.generate_content.assert_not_called()


# =============================================================================
# Test 8: Jitter delay is always between 1.0 and cap
# =============================================================================

class TestJitterDelay:
    """Tests for full-jitter backoff delay calculation."""

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    @patch("ai_agent.gemini_adk.random.uniform")
    def test_jitter_delay_minimum_1s(self, mock_uniform, mock_time, mock_sleep):
        """Delay should be at least 1.0s even if random returns 0."""
        mock_uniform.return_value = 0.0

        expected_response = MagicMock()
        client = _make_client([_503_error(), expected_response])
        config = _make_config()

        _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        mock_uniform.assert_called_once()
        # Cap for attempt=0: min(60.0, 2 * 2^0) = 2.0
        mock_uniform.assert_called_with(0, 2.0)

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    @patch("ai_agent.gemini_adk.random.uniform")
    def test_jitter_cap_at_60s(self, mock_uniform, mock_time, mock_sleep):
        """Delay cap should not exceed 60s."""
        mock_uniform.return_value = 30.0

        expected_response = MagicMock()
        errors = [_503_error()] * MAX_RETRIES + [expected_response]
        client = _make_client(errors)
        config = _make_config()

        _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        for c in mock_uniform.call_args_list:
            low, high = c[0]
            assert low == 0
            assert high <= 60.0

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    @patch("ai_agent.gemini_adk.random.uniform")
    def test_jitter_delay_within_bounds(self, mock_uniform, mock_time, mock_sleep):
        """Delay should always be between 1.0 and cap."""
        mock_uniform.return_value = 1.5

        expected_response = MagicMock()
        client = _make_client([_503_error(), expected_response])
        config = _make_config()

        _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        mock_uniform.assert_called_with(0, 2.0)

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    @patch("ai_agent.gemini_adk.random.uniform")
    def test_jitter_exponential_growth(self, mock_uniform, mock_time, mock_sleep):
        """Cap should grow exponentially: 2, 4, 8, ... up to 60."""
        mock_uniform.return_value = 1.0

        expected_response = MagicMock()
        errors = [_503_error()] * MAX_RETRIES + [expected_response]
        client = _make_client(errors)
        config = _make_config()

        _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        expected_caps = [min(60.0, RETRY_DELAY_BASE * (2 ** i)) for i in range(MAX_RETRIES)]
        actual_caps = [c[0][1] for c in mock_uniform.call_args_list]
        assert actual_caps == expected_caps


# =============================================================================
# Test: Retryable pattern matching
# =============================================================================

class TestRetryablePatterns:
    """Tests for retryable error pattern matching."""

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_unavailable_is_retryable(self, mock_time, mock_sleep):
        """UNAVAILABLE error string should trigger retry."""
        expected_response = MagicMock()
        client = _make_client([Exception("UNAVAILABLE: Service temporarily unavailable"), expected_response])
        config = _make_config()

        result = _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        assert result is expected_response
        assert client.models.generate_content.call_count == 2

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_overloaded_is_retryable(self, mock_time, mock_sleep):
        """'overloaded' in error message should trigger retry."""
        expected_response = MagicMock()
        client = _make_client([Exception("The model is currently Overloaded"), expected_response])
        config = _make_config()

        result = _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        assert result is expected_response

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_502_is_retryable(self, mock_time, mock_sleep):
        """502 Bad Gateway should trigger retry."""
        expected_response = MagicMock()
        client = _make_client([Exception("502 Bad Gateway"), expected_response])
        config = _make_config()

        result = _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        assert result is expected_response

    @patch("ai_agent.gemini_adk.time.sleep")
    @patch("ai_agent.gemini_adk.time.time", side_effect=_time_counter())
    def test_504_is_retryable(self, mock_time, mock_sleep):
        """504 Gateway Timeout should trigger retry."""
        expected_response = MagicMock()
        client = _make_client([Exception("504 Gateway Timeout"), expected_response])
        config = _make_config()

        result = _call_with_retry(client, "gemini-2.5-pro", "hello", config)

        assert result is expected_response


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
