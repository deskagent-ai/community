# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""File and path utilities for DeskAgent.

Consolidates path constants and file cleanup functions that were duplicated
across server.py and routes/execution.py.
"""

import shutil
from pathlib import Path

# Path is set up by assistant/__init__.py
from paths import PROJECT_DIR, DESKAGENT_DIR

# Import logging
try:
    import ai_agent
    system_log = ai_agent.system_log
except ImportError:
    system_log = lambda msg: None

from ai_agent import log

# =============================================================================
# Path Constants
# =============================================================================

SCRIPTS_DIR = DESKAGENT_DIR / "scripts"
TEMP_UPLOADS_DIR = PROJECT_DIR / ".temp" / "uploads"
MCP_DIR = DESKAGENT_DIR / "mcp"


# =============================================================================
# File Cleanup
# =============================================================================

def cleanup_temp_uploads():
    """Clean up temporary uploaded files from .temp/uploads/

    Called after agent execution to remove uploaded files.
    Logs cleanup activity via system_log for debugging.
    """
    try:
        if TEMP_UPLOADS_DIR.exists():
            file_count = len(list(TEMP_UPLOADS_DIR.iterdir()))
            if file_count > 0:
                shutil.rmtree(TEMP_UPLOADS_DIR)
                TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
                log(f"[Cleanup] Deleted {file_count} temp files from .temp/uploads/")
                system_log(f"[files] Cleaned up {file_count} temp uploads")
    except Exception as e:
        log(f"[Cleanup] Error cleaning temp uploads: {e}")
        system_log(f"[files] ERROR cleaning temp uploads: {e}")
