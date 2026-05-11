# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Path setup utility for DeskAgent modules.

Import this module at the top of any file that needs to import from `paths`.
It ensures the scripts directory is on sys.path.

Usage:
    import _setup_path  # noqa: F401
    from paths import get_logs_dir, PROJECT_DIR

This replaces the repetitive try/except pattern:
    try:
        from paths import X
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from paths import X
"""

import sys
from pathlib import Path

# Determine the scripts directory (where paths.py lives)
_SCRIPTS_DIR = Path(__file__).parent.resolve()

# Add to sys.path if not already present
_scripts_str = str(_SCRIPTS_DIR)
if _scripts_str not in sys.path:
    sys.path.insert(0, _scripts_str)

# Verify paths module is importable
try:
    import paths as _paths_check  # noqa: F401
except ImportError as e:
    raise ImportError(
        f"Failed to import paths module from {_SCRIPTS_DIR}. "
        f"Ensure paths.py exists in {_SCRIPTS_DIR}"
    ) from e
