# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Utils - JSON Utilities
======================
Centralized JSON file operations with consistent error handling.
"""

import json
from pathlib import Path
from typing import Any


def load_json_file(path: Path | str) -> dict | list | None:
    """Load JSON from a file with error handling.

    Args:
        path: Path to the JSON file

    Returns:
        Parsed JSON data, or None if file doesn't exist or is invalid
    """
    try:
        path = Path(path)
        if not path.exists():
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_json_file(path: Path | str, data: Any, indent: int = 2) -> bool:
    """Save data to a JSON file.

    Args:
        path: Target file path
        data: Data to serialize
        indent: Indentation level (default: 2)

    Returns:
        True if successful, False otherwise
    """
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        return True
    except (IOError, TypeError):
        return False


def parse_json_string(text: str) -> dict | list | None:
    """Parse a JSON string with error handling.

    Args:
        text: JSON string to parse

    Returns:
        Parsed data, or None if invalid JSON
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def to_json_string(data: Any, indent: int | None = None) -> str:
    """Convert data to JSON string.

    Args:
        data: Data to serialize
        indent: Optional indentation (None for compact)

    Returns:
        JSON string, or empty string on error
    """
    try:
        return json.dumps(data, indent=indent, ensure_ascii=False)
    except TypeError:
        return ""
