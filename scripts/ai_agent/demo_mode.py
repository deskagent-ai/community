# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Demo Mode - Mock responses for demonstrations
=============================================

This module handles mock responses for demo mode, allowing agents
to run with pre-defined responses instead of actual tool calls.

Features:
- Load mock JSON files from workspace/mocks/ directory
- Match tool calls to mock responses
- Support multiple response formats (simple, weighted, argument-based)
- Cache with 60s TTL for live editing during demos

Mock File Formats:

1. Simple response:
   {"tool_name": {"response": "..."}}

2. With metadata (e.g., simulated delay):
   {"tool_name": {"response": "...", "metadata": {"delay_ms": 200}}}

3. Multiple weighted responses (random selection):
   {"tool_name": {"responses": [{"response": "...", "weight": 2}]}}

4. Argument matching (returns first matching variant):
   {"tool_name": {"variants": [{"match_args": {"key": "value"}, "response": "..."}], "fallback_response": "..."}}

5. JSON response (returns as JSON string):
   {"tool_name": {"response_json": {...}}}

Usage:
    from ai_agent.demo_mode import is_demo_mode_enabled, get_mock_response

    if is_demo_mode_enabled(config):
        response = get_mock_response("tool_name", {"arg1": "val1"})
        if response is not None:
            return response
"""

import json
import random
import time
from pathlib import Path
from typing import Optional

# Path is set up by ai_agent/__init__.py
from .base import system_log
from paths import get_workspace_dir, DESKAGENT_DIR

# Cache for loaded mocks with TTL
_mock_cache: dict = {}  # {mocks_dir_str: (data, timestamp)}
_CACHE_TTL_SECONDS = 60  # 60 second TTL for live editing


def is_demo_mode_enabled(config: dict) -> bool:
    """
    Check if demo mode is enabled in configuration.

    Demo mode can be enabled via:
    - config["demo_mode"]["enabled"] = true
    - Environment variable DESKAGENT_DEMO_MODE=1

    Args:
        config: Configuration dictionary

    Returns:
        True if demo mode is enabled, False otherwise
    """
    import os

    # Check environment variable first (override)
    env_demo = os.environ.get("DESKAGENT_DEMO_MODE", "").lower()
    if env_demo in ("1", "true", "yes"):
        return True
    if env_demo in ("0", "false", "no"):
        return False

    # Check config
    demo_config = config.get("demo_mode", {})
    return demo_config.get("enabled", False)


def get_mocks_dir(config: dict = None) -> Path:
    """
    Get the user mocks directory path.

    Uses workspace/mocks/ by default, can be overridden in config.

    Args:
        config: Optional configuration dictionary

    Returns:
        Path to user mocks directory
    """
    if config:
        demo_config = config.get("demo_mode", {})
        custom_dir = demo_config.get("mocks_dir")
        if custom_dir:
            return Path(custom_dir)

    return get_workspace_dir() / "mocks"


def get_product_mocks_dir() -> Path:
    """
    Get the product-bundled mocks directory path.

    This directory contains default demo data shipped with DeskAgent.
    Located at deskagent/mocks/

    Returns:
        Path to product mocks directory
    """
    return DESKAGENT_DIR / "mocks"


def _load_mocks_from_dir(mocks_dir: Path) -> dict:
    """
    Load all mock definitions from a single directory.

    Args:
        mocks_dir: Path to directory containing mock JSON files

    Returns:
        Dictionary mapping tool names to mock definitions
    """
    if not mocks_dir.exists():
        return {}

    all_mocks = {}

    # Load all JSON files in directory
    for json_file in sorted(mocks_dir.glob("*.json")):
        try:
            content = json_file.read_text(encoding="utf-8")
            file_mocks = json.loads(content)

            if isinstance(file_mocks, dict):
                # Merge into all_mocks
                all_mocks.update(file_mocks)
                system_log(f"[DemoMode] Loaded {len(file_mocks)} mock(s) from {json_file.name}")
            else:
                system_log(f"[DemoMode] Skipping {json_file.name}: not a dict")

        except json.JSONDecodeError as e:
            system_log(f"[DemoMode] JSON error in {json_file.name}: {e}")
        except Exception as e:
            system_log(f"[DemoMode] Error loading {json_file.name}: {e}")

    return all_mocks


def load_mocks(mocks_dir: Path) -> dict:
    """
    Load all mock definitions from user and product directories.

    Loads from:
    1. Product mocks (deskagent/mocks/) - base defaults
    2. User mocks (mocks_dir) - overrides product mocks

    Uses caching with 60s TTL for live editing during demos.

    Args:
        mocks_dir: Path to user mocks directory

    Returns:
        Dictionary mapping tool names to mock definitions
    """
    global _mock_cache

    # Include product mocks dir in cache key
    product_dir = get_product_mocks_dir()
    cache_key = f"{product_dir}|{mocks_dir}"

    # Check cache
    if cache_key in _mock_cache:
        cached_data, cached_time = _mock_cache[cache_key]
        age = time.time() - cached_time
        if age < _CACHE_TTL_SECONDS:
            system_log(f"[DemoMode] Cache hit for mocks ({age:.1f}s old)")
            return cached_data

    # Cache miss - load fresh
    all_mocks = {}

    # 1. Load product mocks first (base defaults)
    if product_dir.exists():
        system_log(f"[DemoMode] Loading product mocks from: {product_dir}")
        product_mocks = _load_mocks_from_dir(product_dir)
        all_mocks.update(product_mocks)
        if product_mocks:
            system_log(f"[DemoMode] Loaded {len(product_mocks)} product mock(s)")

    # 2. Load user mocks (override product)
    if mocks_dir.exists() and mocks_dir != product_dir:
        system_log(f"[DemoMode] Loading user mocks from: {mocks_dir}")
        user_mocks = _load_mocks_from_dir(mocks_dir)
        all_mocks.update(user_mocks)
        if user_mocks:
            system_log(f"[DemoMode] Loaded {len(user_mocks)} user mock(s) (overrides)")

    if not all_mocks:
        system_log(f"[DemoMode] No mocks found in product or user directories")

    # Update cache
    _mock_cache[cache_key] = (all_mocks, time.time())
    system_log(f"[DemoMode] Total {len(all_mocks)} mock(s) loaded")

    return all_mocks


def _select_weighted_response(responses: list) -> Optional[dict]:
    """
    Select a response from a weighted list.

    Args:
        responses: List of {"response": "...", "weight": N} dicts

    Returns:
        Selected response dict, or None if list is empty
    """
    if not responses:
        return None

    # Build weighted pool
    pool = []
    for item in responses:
        weight = item.get("weight", 1)
        pool.extend([item] * max(1, int(weight)))

    return random.choice(pool) if pool else None


def _match_args(match_spec: dict, actual_args: dict) -> bool:
    """
    Check if actual arguments match a match specification.

    Supports:
    - Exact match: {"key": "value"} matches if args["key"] == "value"
    - Regex match: {"key": {"$regex": "pattern"}} matches if pattern matches
    - Existence: {"key": {"$exists": true}} matches if key exists

    Args:
        match_spec: Specification of what to match
        actual_args: Actual tool arguments

    Returns:
        True if all match conditions are satisfied
    """
    import re

    for key, expected in match_spec.items():
        actual = actual_args.get(key)

        if isinstance(expected, dict):
            # Special matchers
            if "$regex" in expected:
                if actual is None:
                    return False
                if not re.search(expected["$regex"], str(actual)):
                    return False
            elif "$exists" in expected:
                exists = key in actual_args
                if expected["$exists"] != exists:
                    return False
            elif "$contains" in expected:
                if actual is None:
                    return False
                if expected["$contains"] not in str(actual):
                    return False
            else:
                # Nested dict - exact match
                if actual != expected:
                    return False
        else:
            # Simple equality
            if actual != expected:
                return False

    return True


def _replace_date_placeholders(text: str) -> str:
    """
    Replace date placeholders in text with actual dates.

    Supported placeholders:
    - {{TODAY}} / {{DATE}} - Today's date (YYYY-MM-DD)
    - {{TODAY_DE}} - Today's date (DD.MM.YYYY)
    - {{YESTERDAY}} - Yesterday's date
    - {{TOMORROW}} - Tomorrow's date
    - {{DAYS_AGO_N}} - N days ago (e.g., {{DAYS_AGO_3}})
    - {{DAYS_AHEAD_N}} - N days ahead (e.g., {{DAYS_AHEAD_2}})
    - {{TIME_NOW}} - Current time (HH:MM)

    Args:
        text: Text with placeholders

    Returns:
        Text with placeholders replaced
    """
    import re
    from datetime import datetime, timedelta

    now = datetime.now()

    # Simple replacements
    replacements = {
        "{{TODAY}}": now.strftime("%Y-%m-%d"),
        "{{DATE}}": now.strftime("%Y-%m-%d"),
        "{{TODAY_DE}}": now.strftime("%d.%m.%Y"),
        "{{DATE_DE}}": now.strftime("%d.%m.%Y"),
        "{{YESTERDAY}}": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        "{{TOMORROW}}": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
        "{{TIME_NOW}}": now.strftime("%H:%M"),
        "{{YEAR}}": now.strftime("%Y"),
    }

    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)

    # Dynamic replacements: {{DAYS_AGO_N}}
    def replace_days_ago(match):
        n = int(match.group(1))
        return (now - timedelta(days=n)).strftime("%Y-%m-%d")

    text = re.sub(r"\{\{DAYS_AGO_(\d+)\}\}", replace_days_ago, text)

    # Dynamic replacements: {{DAYS_AHEAD_N}}
    def replace_days_ahead(match):
        n = int(match.group(1))
        return (now + timedelta(days=n)).strftime("%Y-%m-%d")

    text = re.sub(r"\{\{DAYS_AHEAD_(\d+)\}\}", replace_days_ahead, text)

    # Dynamic replacements: {{HOURS_AGO_N}} for timestamps
    def replace_hours_ago(match):
        n = int(match.group(1))
        return (now - timedelta(hours=n)).strftime("%Y-%m-%dT%H:%M:%S")

    text = re.sub(r"\{\{HOURS_AGO_(\d+)\}\}", replace_hours_ago, text)

    return text


def _format_response(response_def: dict) -> str:
    """
    Format a response definition into a string.

    Handles:
    - response: Direct string response
    - response_json: JSON object to serialize
    - Date placeholders are automatically replaced

    Args:
        response_def: Response definition dict

    Returns:
        Response string with date placeholders replaced
    """
    if "response_json" in response_def:
        result = json.dumps(response_def["response_json"], ensure_ascii=False, indent=2)
    elif "response" in response_def:
        result = response_def["response"]
    else:
        result = ""

    # Replace date placeholders
    return _replace_date_placeholders(result)


def get_mock_response(
    tool_name: str,
    args: dict,
    mocks_dir: Path = None,
    config: dict = None,
    fallback: str = "error"
) -> Optional[str]:
    """
    Get a mock response for a tool call.

    Args:
        tool_name: Name of the tool being called
        args: Tool arguments
        mocks_dir: Directory containing mock files (defaults to workspace/mocks/)
        config: Optional configuration dictionary
        fallback: Behavior when no mock found:
            - "error": Return error string
            - "none": Return None (let real tool execute)
            - "empty": Return empty string

    Returns:
        Mock response string, or None if no mock and fallback="none"
    """
    if mocks_dir is None:
        mocks_dir = get_mocks_dir(config)

    mocks = load_mocks(mocks_dir)

    if tool_name not in mocks:
        system_log(f"[DemoMode] No mock for tool: {tool_name}")
        if fallback == "error":
            return f"[Demo Mode] No mock defined for tool: {tool_name}"
        elif fallback == "none":
            return None
        else:  # "empty"
            return ""

    mock_def = mocks[tool_name]
    system_log(f"[DemoMode] Found mock for: {tool_name}")

    # Handle different mock formats
    if "variants" in mock_def:
        # Argument-based matching
        for variant in mock_def["variants"]:
            match_args = variant.get("match_args", {})
            if _match_args(match_args, args):
                system_log(f"[DemoMode] Matched variant for: {tool_name}")
                return _format_response(variant)

        # No variant matched - use fallback
        if "fallback_response" in mock_def:
            system_log(f"[DemoMode] Using fallback for: {tool_name}")
            return mock_def["fallback_response"]
        elif "fallback_response_json" in mock_def:
            return json.dumps(mock_def["fallback_response_json"], ensure_ascii=False, indent=2)
        else:
            system_log(f"[DemoMode] No matching variant and no fallback for: {tool_name}")
            if fallback == "error":
                return f"[Demo Mode] No matching variant for tool: {tool_name}"
            elif fallback == "none":
                return None
            else:
                return ""

    elif "responses" in mock_def:
        # Weighted random selection
        selected = _select_weighted_response(mock_def["responses"])
        if selected:
            system_log(f"[DemoMode] Selected weighted response for: {tool_name}")
            return _format_response(selected)
        else:
            return ""

    else:
        # Simple response
        return _format_response(mock_def)


def load_scenario(agent_name: str, mocks_dir: Path = None, config: dict = None) -> dict:
    """
    Load a scenario file for a specific agent.

    Scenarios are agent-specific mock sets stored in:
    - workspace/mocks/scenarios/{agent_name}.json
    - Or configured via demo_mode.scenarios_dir

    Args:
        agent_name: Name of the agent (e.g., "reply_email")
        mocks_dir: Base mocks directory (defaults to workspace/mocks/)
        config: Optional configuration dictionary

    Returns:
        Scenario dict with mock definitions, or empty dict if not found
    """
    if mocks_dir is None:
        mocks_dir = get_mocks_dir(config)

    # Check for custom scenarios dir in config
    scenarios_dir = mocks_dir / "scenarios"
    if config:
        demo_config = config.get("demo_mode", {})
        custom_scenarios = demo_config.get("scenarios_dir")
        if custom_scenarios:
            scenarios_dir = Path(custom_scenarios)

    scenario_file = scenarios_dir / f"{agent_name}.json"

    if not scenario_file.exists():
        system_log(f"[DemoMode] No scenario file for agent: {agent_name}")
        return {}

    try:
        content = scenario_file.read_text(encoding="utf-8")
        scenario = json.loads(content)
        system_log(f"[DemoMode] Loaded scenario for agent: {agent_name}")
        return scenario if isinstance(scenario, dict) else {}
    except json.JSONDecodeError as e:
        system_log(f"[DemoMode] JSON error in scenario {agent_name}: {e}")
        return {}
    except Exception as e:
        system_log(f"[DemoMode] Error loading scenario {agent_name}: {e}")
        return {}


def clear_cache():
    """
    Clear the mock cache to force reload on next access.

    Use this when mock files have been edited and you want
    immediate reload without waiting for TTL expiry.
    """
    global _mock_cache
    _mock_cache.clear()
    system_log("[DemoMode] Cache cleared")


def get_mock_metadata(tool_name: str, mocks_dir: Path = None, config: dict = None) -> dict:
    """
    Get metadata for a mock (e.g., simulated delay).

    Args:
        tool_name: Name of the tool
        mocks_dir: Directory containing mock files
        config: Optional configuration dictionary

    Returns:
        Metadata dict (may be empty)
    """
    if mocks_dir is None:
        mocks_dir = get_mocks_dir(config)

    mocks = load_mocks(mocks_dir)

    if tool_name not in mocks:
        return {}

    return mocks[tool_name].get("metadata", {})


def apply_mock_delay(tool_name: str, mocks_dir: Path = None, config: dict = None):
    """
    Apply simulated delay for a mock tool call.

    Reads delay_ms from metadata and sleeps if present.

    Args:
        tool_name: Name of the tool
        mocks_dir: Directory containing mock files
        config: Optional configuration dictionary
    """
    metadata = get_mock_metadata(tool_name, mocks_dir, config)
    delay_ms = metadata.get("delay_ms", 0)

    if delay_ms > 0:
        delay_s = delay_ms / 1000.0
        system_log(f"[DemoMode] Simulating {delay_ms}ms delay for: {tool_name}")
        time.sleep(delay_s)


# Export public API
__all__ = [
    "is_demo_mode_enabled",
    "get_mocks_dir",
    "get_product_mocks_dir",
    "load_mocks",
    "get_mock_response",
    "load_scenario",
    "clear_cache",
    "get_mock_metadata",
    "apply_mock_delay",
]
