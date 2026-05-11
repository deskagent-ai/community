# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Mock LLM Backend - For testing without API costs
================================================

This module provides a mock LLM backend that simulates AI responses for testing.
It allows testing the complete agent workflow without making real API calls.

Features:
- Mock LLM responses (static, pattern-matching, scenario-based)
- Track all calls for assertions
- Simulate tool calls
- Simulate streaming (on_chunk callbacks)
- Zero cost tracking

Usage:
    from ai_agent.mock_llm import MockLLMBackend, MockTracker

    backend = MockLLMBackend()
    response = backend.call(prompt="Hello", agent_name="test")

    # Assertions
    backend.assert_prompt_contains("Hello")
    tracker.assert_tool_called("outlook_get_email")

NOT FOR END USERS - This is a developer/testing tool only.
"""

import json
import re
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

from .agent_logging import AgentResponse
from .logging import log


__all__ = [
    "MockLLMBackend",
    "MockTracker",
    "MockResponse",
    "is_mock_mode_enabled",
    "get_mock_llm_dir",
]


# =============================================================================
# Mock Mode Configuration
# =============================================================================

def is_mock_mode_enabled(config: dict) -> bool:
    """
    Check if mock mode is enabled in configuration.

    Mock mode can be enabled via:
    - config["mock_mode"]["enabled"] = true
    - Environment variable DESKAGENT_MOCK_MODE=1

    Args:
        config: Configuration dictionary

    Returns:
        True if mock mode is enabled, False otherwise
    """
    import os

    # Check environment variable first (override)
    env_mock = os.environ.get("DESKAGENT_MOCK_MODE", "").lower()
    if env_mock in ("1", "true", "yes"):
        return True
    if env_mock in ("0", "false", "no"):
        return False

    # Check config
    mock_config = config.get("mock_mode", {})
    return mock_config.get("enabled", False)


def get_mock_llm_dir(config: dict = None) -> Path:
    """
    Get the mock LLM responses directory path.

    Uses workspace/mocks/llm/ by default, can be overridden in config.

    Args:
        config: Optional configuration dictionary

    Returns:
        Path to mock LLM directory
    """
    from paths import get_workspace_dir

    if config:
        mock_config = config.get("mock_mode", {})
        custom_dir = mock_config.get("mocks_dir")
        if custom_dir:
            return Path(custom_dir) / "llm"

    return get_workspace_dir() / "mocks" / "llm"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class MockResponse:
    """
    A mock response definition.

    Attributes:
        id: Unique identifier for this mock response
        content: The response text
        tool_calls: List of tool calls to simulate
        model: Fake model name to report
        input_tokens: Fake input token count
        output_tokens: Fake output token count
        match_prompt: Pattern to match (contains or regex)
        match_agent: Agent name to match (optional)
        is_default: True if this is the fallback response
    """
    id: str = "default"
    content: str = "[Mock] Response generated."
    tool_calls: list = field(default_factory=list)
    model: str = "mock-llm"
    input_tokens: int = 10
    output_tokens: int = 20
    match_prompt: Optional[dict] = None
    match_agent: Optional[str] = None
    is_default: bool = False


# =============================================================================
# Mock Tracker
# =============================================================================

class MockTracker:
    """
    Tracks mock LLM calls for assertions in tests.

    Thread-safe via threading.Lock for parallel test execution.

    Usage:
        tracker = MockTracker()
        backend = MockLLMBackend(tracker=tracker)

        # After running agent...
        tracker.assert_tool_called("outlook_get_email")
        tracker.assert_prompt_contains("Hello")
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._calls: list[dict] = []
        self._mock_response: Optional[str] = None
        self._tool_responses: dict[str, str] = {}
        self._available_tools: list[str] = []

    def reset(self):
        """Reset all tracking data."""
        with self._lock:
            self._calls.clear()
            self._mock_response = None
            self._tool_responses.clear()
            self._available_tools.clear()

    def record_call(
        self,
        prompt: str,
        agent_name: str = None,
        tools: list = None,
        response: str = None,
        tool_calls: list = None
    ):
        """Record an LLM call for later assertions."""
        with self._lock:
            self._calls.append({
                "prompt": prompt,
                "agent_name": agent_name,
                "tools": tools or [],
                "response": response,
                "tool_calls": tool_calls or [],
                "timestamp": time.time()
            })
            if tools:
                self._available_tools = [
                    t.get("name", str(t)) if isinstance(t, dict) else str(t)
                    for t in tools
                ]

    def set_mock_response(self, response: str):
        """Set a specific mock response for the next call."""
        with self._lock:
            self._mock_response = response

    def get_mock_response(self) -> Optional[str]:
        """Get and consume the set mock response."""
        with self._lock:
            resp = self._mock_response
            self._mock_response = None
            return resp

    def set_tool_response(self, tool_name: str, response: str | dict):
        """Set a mock response for a specific tool."""
        with self._lock:
            if isinstance(response, dict):
                response = json.dumps(response, ensure_ascii=False)
            self._tool_responses[tool_name] = response

    def get_tool_response(self, tool_name: str) -> Optional[str]:
        """Get the mock response for a tool."""
        with self._lock:
            return self._tool_responses.get(tool_name)

    def get_call_log(self) -> list[dict]:
        """Get all recorded calls."""
        with self._lock:
            return list(self._calls)

    def get_sent_prompt(self) -> str:
        """Get the prompt from the last call."""
        with self._lock:
            if self._calls:
                return self._calls[-1].get("prompt", "")
            return ""

    def get_llm_context(self) -> str:
        """Get full context sent to LLM (all prompts concatenated)."""
        with self._lock:
            return "\n".join(c.get("prompt", "") for c in self._calls)

    def get_available_tools(self) -> list[str]:
        """Get list of tools that were available in the last call."""
        with self._lock:
            return list(self._available_tools)

    def tool_was_called(self, tool_name: str) -> bool:
        """Check if a specific tool was called."""
        with self._lock:
            for call in self._calls:
                for tc in call.get("tool_calls", []):
                    if tc.get("name") == tool_name:
                        return True
            return False

    def get_tool_call_count(self, tool_name: str = None) -> int:
        """Get count of tool calls (optionally filtered by name)."""
        with self._lock:
            count = 0
            for call in self._calls:
                for tc in call.get("tool_calls", []):
                    if tool_name is None or tc.get("name") == tool_name:
                        count += 1
            return count

    # === Assertion Helpers ===

    def assert_tool_called(self, tool_name: str, times: int = None):
        """Assert that a tool was called (optionally exact times)."""
        if not self.tool_was_called(tool_name):
            raise AssertionError(f"Tool '{tool_name}' was not called")
        if times is not None:
            actual = self.get_tool_call_count(tool_name)
            if actual != times:
                raise AssertionError(
                    f"Tool '{tool_name}' called {actual} times, expected {times}"
                )

    def assert_tool_not_called(self, tool_name: str):
        """Assert that a tool was NOT called."""
        if self.tool_was_called(tool_name):
            raise AssertionError(f"Tool '{tool_name}' should not have been called")

    def assert_prompt_contains(self, text: str):
        """Assert that the sent prompt contains specific text."""
        prompt = self.get_sent_prompt()
        if text not in prompt:
            raise AssertionError(f"Prompt does not contain '{text}'")

    def assert_prompt_not_contains(self, text: str):
        """Assert that the sent prompt does NOT contain specific text."""
        prompt = self.get_sent_prompt()
        if text in prompt:
            raise AssertionError(f"Prompt should not contain '{text}'")

    def assert_call_count(self, expected: int):
        """Assert the number of LLM calls made."""
        with self._lock:
            actual = len(self._calls)
        if actual != expected:
            raise AssertionError(f"Expected {expected} calls, got {actual}")


# =============================================================================
# Mock LLM Backend
# =============================================================================

class MockLLMBackend:
    """
    Mock backend that simulates LLM responses without API calls.

    Features:
    - Load mock responses from JSON files
    - Pattern-based prompt matching
    - Tool call simulation
    - Streaming simulation
    - Zero cost reporting

    Usage:
        backend = MockLLMBackend()
        response = backend.call(prompt="Hello", agent_name="test")
    """

    def __init__(
        self,
        config: dict = None,
        mocks_dir: Path = None,
        tracker: MockTracker = None
    ):
        """
        Initialize the mock backend.

        Args:
            config: Configuration dictionary
            mocks_dir: Directory containing mock JSON files
            tracker: Optional MockTracker for assertions
        """
        self.config = config or {}
        self.mocks_dir = mocks_dir or get_mock_llm_dir(config)
        self.tracker = tracker or MockTracker()
        self._responses: list[MockResponse] = []
        self._loaded = False

    def _load_responses(self):
        """Load mock responses from JSON files."""
        if self._loaded:
            return

        self._responses = []

        # Default fallback response
        default_response = MockResponse(
            id="default-fallback",
            content="[Mock] I processed your request.",
            is_default=True
        )

        if self.mocks_dir.exists():
            for json_file in sorted(self.mocks_dir.glob("*.json")):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    responses = data.get("responses", [])

                    for r in responses:
                        match_spec = r.get("match", {})
                        resp_spec = r.get("response", {})

                        mock_resp = MockResponse(
                            id=r.get("id", "unknown"),
                            content=resp_spec.get("content", "[Mock] Default response"),
                            tool_calls=resp_spec.get("tool_calls", []),
                            model=resp_spec.get("model", "mock-llm"),
                            input_tokens=resp_spec.get("input_tokens", 10),
                            output_tokens=resp_spec.get("output_tokens", 20),
                            match_prompt=match_spec.get("prompt"),
                            match_agent=match_spec.get("agent"),
                            is_default=match_spec.get("$default", False)
                        )
                        self._responses.append(mock_resp)

                    log(f"[MockLLM] Loaded {len(responses)} responses from {json_file.name}")

                except json.JSONDecodeError as e:
                    log(f"[MockLLM] JSON error in {json_file.name}: {e}")
                except Exception as e:
                    log(f"[MockLLM] Error loading {json_file.name}: {e}")

        # Add default fallback if no default found
        if not any(r.is_default for r in self._responses):
            self._responses.append(default_response)

        self._loaded = True
        log(f"[MockLLM] Total {len(self._responses)} mock responses loaded")

    def _match_prompt(self, pattern: dict, prompt: str) -> bool:
        """Check if prompt matches a pattern specification."""
        if not pattern:
            return False

        if "$contains" in pattern:
            return pattern["$contains"].lower() in prompt.lower()

        if "$regex" in pattern:
            return bool(re.search(pattern["$regex"], prompt, re.IGNORECASE))

        # Exact string match
        if isinstance(pattern, str):
            return pattern.lower() in prompt.lower()

        return False

    def _find_response(self, prompt: str, agent_name: str = None) -> MockResponse:
        """Find the best matching mock response."""
        self._load_responses()

        # Check tracker for set response first
        tracker_resp = self.tracker.get_mock_response()
        if tracker_resp:
            return MockResponse(
                id="tracker-override",
                content=tracker_resp,
                model="mock-llm"
            )

        # Find matching response
        default = None
        for resp in self._responses:
            if resp.is_default:
                default = resp
                continue

            # Check agent match first
            if resp.match_agent:
                if resp.match_agent != agent_name:
                    continue
                # Agent matches - check if prompt also needs to match
                if resp.match_prompt:
                    if self._match_prompt(resp.match_prompt, prompt):
                        log(f"[MockLLM] Matched response (agent+prompt): {resp.id}")
                        return resp
                else:
                    # Agent-only match (no prompt requirement)
                    log(f"[MockLLM] Matched response (agent): {resp.id}")
                    return resp
            elif resp.match_prompt:
                # Prompt-only match
                if self._match_prompt(resp.match_prompt, prompt):
                    log(f"[MockLLM] Matched response (prompt): {resp.id}")
                    return resp

        # Return default
        log(f"[MockLLM] Using default response")
        return default or MockResponse()

    def call(
        self,
        prompt: str,
        system_prompt: str = None,
        agent_name: str = None,
        tools: list = None,
        on_chunk: Callable = None,
        **kwargs
    ) -> AgentResponse:
        """
        Execute a mock LLM call.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt (ignored for matching)
            agent_name: Agent/backend name for matching
            tools: Available tools (for tracking)
            on_chunk: Optional streaming callback
            **kwargs: Additional arguments (ignored)

        Returns:
            AgentResponse with mock data
        """
        start_time = time.time()

        # Find matching response
        mock_resp = self._find_response(prompt, agent_name)

        # Simulate streaming if callback provided
        if on_chunk and mock_resp.content:
            # Split into tokens (words)
            tokens = mock_resp.content.split()
            full_response = ""
            for token in tokens:
                full_response += token + " "
                on_chunk(
                    token=token + " ",
                    is_thinking=False,
                    full_response=full_response.strip()
                )
                # Small delay to simulate streaming
                time.sleep(0.01)

        # Record call for tracking
        self.tracker.record_call(
            prompt=prompt,
            agent_name=agent_name,
            tools=tools,
            response=mock_resp.content,
            tool_calls=mock_resp.tool_calls
        )

        duration = time.time() - start_time

        return AgentResponse(
            success=True,
            content=mock_resp.content,
            model=mock_resp.model,
            input_tokens=mock_resp.input_tokens,
            output_tokens=mock_resp.output_tokens,
            cost_usd=0.0,  # Mock = no cost
            duration_seconds=duration
        )

    def get_call_log(self) -> list[dict]:
        """Get all recorded calls from tracker."""
        return self.tracker.get_call_log()

    def assert_tool_called(self, tool_name: str, times: int = None):
        """Assert a tool was called (delegated to tracker)."""
        self.tracker.assert_tool_called(tool_name, times)

    def reset(self):
        """Reset the backend and tracker state."""
        self.tracker.reset()
        self._loaded = False
        self._responses.clear()


# =============================================================================
# Factory Function
# =============================================================================

def create_mock_backend(
    config: dict = None,
    tracker: MockTracker = None
) -> MockLLMBackend:
    """
    Create a configured MockLLMBackend instance.

    Args:
        config: Configuration dictionary
        tracker: Optional shared MockTracker

    Returns:
        Configured MockLLMBackend
    """
    return MockLLMBackend(
        config=config,
        tracker=tracker or MockTracker()
    )
