# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP Path Setup for Nuitka Builds
=================================
Adds embedded Python's Lib and site-packages to sys.path.
Import this module FIRST in any MCP that needs msal, email.mime, xml.dom, etc.

Usage:
    import _path_setup  # Must be first import!
    import msal  # Now this works
"""
import sys
from pathlib import Path

def setup_embedded_python_paths():
    """Add embedded Python paths for Nuitka builds."""
    # Find the mcp directory (where this file lives)
    mcp_dir = Path(__file__).parent
    # Go up to deskagent directory
    deskagent_dir = mcp_dir.parent
    # Python embedded is at deskagent/python/
    python_lib = deskagent_dir / 'python' / 'Lib'
    python_site_packages = python_lib / 'site-packages'

    paths_added = []

    # Use position 1 to not break pywin32 DLL loading
    # Position 0 is reserved for the current working directory
    if python_site_packages.is_dir() and str(python_site_packages) not in sys.path:
        sys.path.insert(1, str(python_site_packages))
        paths_added.append('site-packages')

    if python_lib.is_dir() and str(python_lib) not in sys.path:
        sys.path.insert(1, str(python_lib))
        paths_added.append('Lib')

    return paths_added

# Auto-run on import
_paths_added = setup_embedded_python_paths()
