#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
AI Assistant - System Tray + Hotkeys + HTTP Server
===================================================
Thin wrapper that imports from the assistant/ module.
Keep this file for backward compatibility with existing scripts.
"""

from assistant import main

if __name__ == "__main__":
    main()
