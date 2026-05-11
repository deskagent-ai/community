# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
AI Assistant Scripts
====================
Modulsammlung für den AI-Assistenten.
"""
import sys

from .ai_agent import call_agent, AgentResponse, extract_json
from .config import PROJECT_DIR, TEMP_DIR, CURRENT_EMAIL, DRAFT_RESPONSE

# Windows-only: Outlook integration
if sys.platform == 'win32':
    from .outlook_legacy import export_selected_email, create_outlook_draft, get_unread_emails
else:
    # Stubs for non-Windows platforms
    def export_selected_email(*args, **kwargs):
        raise NotImplementedError("Outlook integration requires Windows")
    def create_outlook_draft(*args, **kwargs):
        raise NotImplementedError("Outlook integration requires Windows")
    def get_unread_emails(*args, **kwargs):
        raise NotImplementedError("Outlook integration requires Windows")
