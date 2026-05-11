# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Response Parser - AI Response Cleaning and Extraction
======================================================

Utility functions for parsing and cleaning AI agent responses.
These are standalone functions with no dependencies on other ai_agent modules.

Functions:
- extract_json: Extract JSON from text (handles markdown code blocks)
- clean_tool_markers: Remove tool markers like [Tool: name | 0.0s]
"""

import json
import re
from typing import Optional

__all__ = ["extract_json", "clean_tool_markers"]


def extract_json(response: str) -> Optional[dict]:
    """
    Extract JSON from an agent response.

    Handles various formats:
    - Pure JSON
    - JSON wrapped in markdown code blocks (```json ... ```)
    - JSON surrounded by explanatory text

    Args:
        response: Raw response from agent

    Returns:
        Parsed JSON as dict or None on error

    Examples:
        >>> extract_json('{"key": "value"}')
        {'key': 'value'}

        >>> extract_json('Here is the result: ```json\\n{"key": "value"}\\n```')
        {'key': 'value'}

        >>> extract_json('Some text {"key": "value"} more text')
        {'key': 'value'}
    """
    if not response:
        return None

    text = response.strip()

    # Remove markdown code blocks
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1].strip()
            if text.startswith("json"):
                text = text[4:].strip()

    # Find JSON object if still surrounded by text
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def clean_tool_markers(text: str) -> str:
    """
    Remove tool markers from text for clean conversation history.

    Removes patterns like:
    - [Tool: name | 0.0s]
    - [Tool: name (hourglass)]
    - [Tool: name ...] `preview`
    - [Tool: name]

    This is used to clean responses before adding to conversation history,
    preventing tool markers from appearing in subsequent prompts.

    Args:
        text: Text to clean

    Returns:
        Text with tool markers removed

    Examples:
        >>> clean_tool_markers("Result [Tool: search | 0.5s] found")
        "Result found"

        >>> clean_tool_markers("[Tool: fetch] `preview` data here")
        "data here"
    """
    if not text:
        return text

    # Remove tool markers with various formats
    # [Tool: name | 0.0s] or [Tool: name hourglass] or [Tool: name ...] `preview` or [Tool: name]
    cleaned = re.sub(r'\[Tool:\s*[^\]]+\](?:\s*`[^`]*`)?', '', text)

    # Clean up resulting double newlines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    return cleaned.strip()
