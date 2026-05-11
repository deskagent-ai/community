# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Parsing Utilities
=================
Shared parsing functions for frontmatter, markdown, etc.
"""

import json
import re


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse JSON frontmatter and return (metadata, clean_content).

    Frontmatter format:
    ---
    {"key": "value"}
    ---
    content...

    Returns:
        Tuple of (metadata dict, content without frontmatter)
    """
    pattern = r'^---\s*\n(.*?)\n---\s*\n?(.*)$'
    match = re.match(pattern, content, re.DOTALL)

    if match:
        try:
            metadata = json.loads(match.group(1))
            clean_content = match.group(2)
            return metadata, clean_content
        except json.JSONDecodeError:
            pass

    return {}, content
