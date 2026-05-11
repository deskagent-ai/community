# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Utils Module
============
Centralized utility functions shared across the DeskAgent codebase.

This module eliminates code duplication by providing common functions
for timestamps, JSON operations, and file I/O.

Usage (absolute imports from PYTHONPATH):
    from utils.timestamp import get_timestamp_iso, get_timestamp_date
    from utils.json_utils import load_json_file, save_json_file

    # Or import all:
    from utils import get_timestamp_iso, load_json_file
"""

from .timestamp import (
    get_timestamp_iso,
    get_timestamp_date,
    get_timestamp_datetime,
    get_timestamp_time,
    get_timestamp_time_ms,
    get_timestamp_api,
    get_timestamp_file,
)

from .json_utils import (
    load_json_file,
    save_json_file,
    parse_json_string,
    to_json_string,
)

from .parsing import (
    parse_frontmatter,
)

__all__ = [
    # Timestamp utilities
    "get_timestamp_iso",
    "get_timestamp_date",
    "get_timestamp_datetime",
    "get_timestamp_time",
    "get_timestamp_time_ms",
    "get_timestamp_api",
    "get_timestamp_file",
    # JSON utilities
    "load_json_file",
    "save_json_file",
    "parse_json_string",
    "to_json_string",
    # Parsing utilities
    "parse_frontmatter",
]
