# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Utils - Timestamp Utilities
===========================
Centralized timestamp formatting functions.

This is the SINGLE SOURCE OF TRUTH for timestamp formats.
"""

from datetime import datetime


def get_timestamp_iso() -> str:
    """Get current timestamp in ISO format.

    Returns:
        ISO format timestamp, e.g., "2025-01-18T14:30:45.123456"
    """
    return datetime.now().isoformat()


def get_timestamp_date() -> str:
    """Get current date in ISO format.

    Returns:
        Date string, e.g., "2025-01-18"
    """
    return datetime.now().strftime("%Y-%m-%d")


def get_timestamp_datetime() -> str:
    """Get current datetime in readable format.

    Returns:
        Datetime string, e.g., "2025-01-18 14:30:45"
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_timestamp_time() -> str:
    """Get current time only.

    Returns:
        Time string, e.g., "14:30:45"
    """
    return datetime.now().strftime("%H:%M:%S")


def get_timestamp_time_ms() -> str:
    """Get current time with milliseconds.

    Returns:
        Time string with ms, e.g., "14:30:45.123"
    """
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def get_timestamp_api() -> str:
    """Get current timestamp for API calls (UTC format).

    Returns:
        API timestamp, e.g., "2025-01-18T23:59:59Z"
    """
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def get_timestamp_file() -> str:
    """Get timestamp suitable for filenames.

    Returns:
        Filename-safe timestamp, e.g., "20250118_143045"
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S")
