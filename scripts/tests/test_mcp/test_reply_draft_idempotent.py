# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for outlook_create_reply_draft idempotency (Plan 055).

Tests that:
- First call creates a new draft (happy path)
- Second call for same mail updates existing draft (idempotency)
- Cache miss on deleted draft creates new draft
- Cache miss on sent draft creates new draft
- Different mails create different drafts
- outlook_create_reply_draft_with_attachment is also idempotent
"""

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# Add the mcp directory to sys.path so 'outlook' package can be found
MCP_DIR = Path(__file__).parent.parent.parent.parent / "mcp"
sys.path.insert(0, str(MCP_DIR))

# Mock Windows-only and MCP-internal modules before importing outlook.
# Only mock if not already present as real modules.
_mocked_modules = {}


def _ensure_mock(name, mock_obj=None):
    """Install a mock module only if no real module is loaded."""
    if name not in sys.modules:
        _mocked_modules[name] = mock_obj or MagicMock()
        sys.modules[name] = _mocked_modules[name]


# COM layer (Windows-only)
_ensure_mock("pythoncom")
_ensure_mock("win32com", MagicMock())
_ensure_mock("win32com.client", MagicMock())

# MCP internal API used by outlook package
_mock_mcp_api = MagicMock()
_mock_mcp_api.mcp_log = MagicMock()
_mock_mcp_api.load_config = MagicMock(return_value={})
_ensure_mock("_mcp_api", _mock_mcp_api)

# Email utilities
_mock_email_utils = MagicMock()
_mock_email_utils.render_email_footer = MagicMock(return_value="")
_mock_email_utils.append_footer_to_html = MagicMock(side_effect=lambda html, lang="de": html)
_ensure_mock("email_utils", _mock_email_utils)

# mcp_shared and its submodules
_mock_mcp_shared = ModuleType("mcp_shared")
_mock_mcp_shared_email = MagicMock()
_mock_mcp_shared_email.extract_latest_message = MagicMock(
    side_effect=lambda body, max_length=0: body[:max_length] if max_length else body
)
_mock_mcp_shared.email_utils = _mock_mcp_shared_email
_ensure_mock("mcp_shared", _mock_mcp_shared)
_ensure_mock("mcp_shared.email_utils", _mock_mcp_shared_email)
# Also mock mcp_shared.constants (used by scripts.ai_agent.mcp_discovery)
_mock_mcp_shared_constants = MagicMock()
_mock_mcp_shared_constants.WINDOWS_ONLY_MCP = set()
_ensure_mock("mcp_shared.constants", _mock_mcp_shared_constants)

# Now import the module under test
from outlook import email_write
from outlook.email_write import (
    _try_update_cached_draft,
    outlook_create_reply_draft,
    outlook_create_reply_draft_with_attachment,
    _reply_draft_cache,
)

# Clean up mocked modules from sys.modules so they don't pollute other test files.
# The outlook package already imported what it needs; removing from sys.modules is safe.
for _name in list(_mocked_modules.keys()):
    if _name in sys.modules and sys.modules[_name] is _mocked_modules[_name]:
        del sys.modules[_name]
del _mocked_modules


@pytest.fixture(autouse=True)
def clear_draft_cache():
    """Clear the reply draft cache before and after each test."""
    _reply_draft_cache.clear()
    yield
    _reply_draft_cache.clear()


@pytest.fixture
def mock_outlook_env(monkeypatch):
    """Set up a complete mock Outlook environment for email_write tests.

    Returns a dict with all mock objects for assertions.
    """
    mock_app = MagicMock(name="OutlookApp")
    mock_namespace = MagicMock(name="MAPI_Namespace")
    mock_explorer = MagicMock(name="Explorer")
    mock_selection = MagicMock(name="Selection")
    mock_mail = MagicMock(name="OriginalMail")
    mock_reply = MagicMock(name="ReplyDraft")

    # Setup chain: outlook -> explorer -> selection -> mail
    mock_app.ActiveExplorer.return_value = mock_explorer
    mock_explorer.Selection = mock_selection
    mock_selection.Count = 1
    mock_selection.Item.return_value = mock_mail

    # Original mail properties
    mock_mail.EntryID = "ORIGINAL_ENTRY_ID_ABC123"
    mock_mail.Subject = "Test Subject"
    mock_mail.SenderName = "Test Sender"

    # Reply draft properties
    mock_reply.HTMLBody = ""
    mock_reply.Sent = False
    mock_reply.EntryID = "DRAFT_ENTRY_ID_XYZ789"
    mock_reply.Subject = "RE: Test Subject"

    # mail.ReplyAll() / mail.Reply() returns the reply mock
    mock_mail.ReplyAll.return_value = mock_reply
    mock_mail.Reply.return_value = mock_reply

    # ActiveInlineResponse returns None (no inline response)
    mock_explorer.ActiveInlineResponse = None

    # Patch get_outlook and get_namespace in email_write module
    monkeypatch.setattr(email_write, "get_outlook", lambda: mock_app)
    monkeypatch.setattr(email_write, "get_namespace", lambda: mock_namespace)
    monkeypatch.setattr(email_write, "mcp_log", lambda msg: None)  # Suppress logging

    return {
        "app": mock_app,
        "namespace": mock_namespace,
        "explorer": mock_explorer,
        "selection": mock_selection,
        "mail": mock_mail,
        "reply": mock_reply,
    }


class TestReplyDraftIdempotency:
    """Tests for outlook_create_reply_draft idempotency."""

    def test_first_call_creates_draft(self, mock_outlook_env):
        """First call should create a new draft and cache the EntryID."""
        result = outlook_create_reply_draft("Hello, this is a reply.", reply_all=True)

        assert "erstellt" in result
        assert "Allen" in result
        assert "Test Subject" in result

        # Verify draft was created via ReplyAll
        mock_outlook_env["mail"].ReplyAll.assert_called_once()
        mock_outlook_env["reply"].Display.assert_called_once()
        mock_outlook_env["reply"].Save.assert_called_once()

        # Verify cache was populated
        assert "ORIGINAL_ENTRY_ID_ABC123" in _reply_draft_cache
        assert _reply_draft_cache["ORIGINAL_ENTRY_ID_ABC123"] == "DRAFT_ENTRY_ID_XYZ789"

    def test_second_call_updates_existing_draft(self, mock_outlook_env):
        """Second call for same mail should update existing draft, not create new one."""
        # Simulate existing cache entry from first call
        _reply_draft_cache["ORIGINAL_ENTRY_ID_ABC123"] = "DRAFT_ENTRY_ID_XYZ789"

        # Mock GetItemFromID to return the existing draft
        existing_draft = MagicMock(name="ExistingDraft")
        existing_draft.Sent = False
        existing_draft.Subject = "RE: Test Subject"
        mock_outlook_env["namespace"].GetItemFromID.return_value = existing_draft

        result = outlook_create_reply_draft("Updated reply text.", reply_all=True)

        assert "aktualisiert" in result
        assert "RE: Test Subject" in result

        # Verify NO new reply was created
        mock_outlook_env["mail"].ReplyAll.assert_not_called()
        mock_outlook_env["mail"].Reply.assert_not_called()

        # Verify existing draft was updated
        existing_draft.Save.assert_called_once()
        mock_outlook_env["namespace"].GetItemFromID.assert_called_once_with("DRAFT_ENTRY_ID_XYZ789")

    def test_cache_miss_deleted_draft_creates_new(self, mock_outlook_env):
        """If cached draft was deleted, should create a new one."""
        # Simulate cache entry pointing to a deleted draft
        _reply_draft_cache["ORIGINAL_ENTRY_ID_ABC123"] = "DELETED_DRAFT_ID"

        # GetItemFromID raises exception for deleted draft
        mock_outlook_env["namespace"].GetItemFromID.side_effect = Exception("Item not found")

        result = outlook_create_reply_draft("New reply after delete.", reply_all=True)

        assert "erstellt" in result
        assert "Allen" in result

        # Verify a new reply was created
        mock_outlook_env["mail"].ReplyAll.assert_called_once()
        mock_outlook_env["reply"].Display.assert_called_once()
        mock_outlook_env["reply"].Save.assert_called_once()

        # Verify cache was updated with new draft ID
        assert _reply_draft_cache["ORIGINAL_ENTRY_ID_ABC123"] == "DRAFT_ENTRY_ID_XYZ789"

    def test_cache_miss_sent_draft_creates_new(self, mock_outlook_env):
        """If cached draft was already sent, should create a new one."""
        # Simulate cache entry pointing to a sent draft
        _reply_draft_cache["ORIGINAL_ENTRY_ID_ABC123"] = "SENT_DRAFT_ID"

        # GetItemFromID returns the draft but it's already sent
        sent_draft = MagicMock(name="SentDraft")
        sent_draft.Sent = True
        mock_outlook_env["namespace"].GetItemFromID.return_value = sent_draft

        result = outlook_create_reply_draft("New reply after send.", reply_all=True)

        assert "erstellt" in result

        # Verify a new reply was created
        mock_outlook_env["mail"].ReplyAll.assert_called_once()

        # Verify cache was updated with new draft ID
        assert _reply_draft_cache["ORIGINAL_ENTRY_ID_ABC123"] == "DRAFT_ENTRY_ID_XYZ789"

    def test_different_mails_create_different_drafts(self, mock_outlook_env):
        """Different original mails should create separate drafts."""
        # First call - mail A
        mock_outlook_env["mail"].EntryID = "MAIL_A_ID"
        mock_outlook_env["reply"].EntryID = "DRAFT_A_ID"
        result_a = outlook_create_reply_draft("Reply to A", reply_all=True)
        assert "erstellt" in result_a

        # Reset mocks for second call
        mock_outlook_env["mail"].ReplyAll.reset_mock()
        mock_outlook_env["reply"].Display.reset_mock()
        mock_outlook_env["reply"].Save.reset_mock()

        # Second call - mail B (different EntryID)
        mock_outlook_env["mail"].EntryID = "MAIL_B_ID"
        mock_outlook_env["reply"].EntryID = "DRAFT_B_ID"
        result_b = outlook_create_reply_draft("Reply to B", reply_all=False)
        assert "erstellt" in result_b
        assert "Absender" in result_b

        # Verify both drafts are cached separately
        assert _reply_draft_cache["MAIL_A_ID"] == "DRAFT_A_ID"
        assert _reply_draft_cache["MAIL_B_ID"] == "DRAFT_B_ID"

        # Verify second call created a new reply (not updated A)
        mock_outlook_env["mail"].Reply.assert_called_once()

    def test_null_entry_id_skips_cache(self, mock_outlook_env):
        """If original mail has no EntryID, cache should be skipped."""
        mock_outlook_env["mail"].EntryID = None

        result = outlook_create_reply_draft("Reply without ID.", reply_all=True)

        assert "erstellt" in result
        # Cache should be empty (no entry for None key)
        assert len(_reply_draft_cache) == 0


class TestReplyDraftWithAttachmentIdempotency:
    """Tests for outlook_create_reply_draft_with_attachment idempotency."""

    def test_first_call_creates_draft_with_attachment(self, mock_outlook_env, tmp_path):
        """First call should create draft with attachment and cache EntryID."""
        # Create a temp file to use as attachment
        attachment = tmp_path / "test.pdf"
        attachment.write_text("dummy pdf content")

        result = outlook_create_reply_draft_with_attachment(
            body="Please find attached.",
            attachment_path=str(attachment),
            reply_all=True
        )

        assert "erstellt" in result
        assert "test.pdf" in result

        # Verify attachment was added
        mock_outlook_env["reply"].Attachments.Add.assert_called_once_with(str(attachment))

        # Verify cache was populated
        assert "ORIGINAL_ENTRY_ID_ABC123" in _reply_draft_cache

    def test_second_call_updates_existing_draft_with_attachment(self, mock_outlook_env, tmp_path):
        """Second call should update body of existing draft (attachment stays)."""
        attachment = tmp_path / "test.pdf"
        attachment.write_text("dummy pdf content")

        # Simulate existing cache entry
        _reply_draft_cache["ORIGINAL_ENTRY_ID_ABC123"] = "DRAFT_ENTRY_ID_XYZ789"

        # Mock GetItemFromID
        existing_draft = MagicMock(name="ExistingDraftWithAttachment")
        existing_draft.Sent = False
        existing_draft.Subject = "RE: Test Subject"
        mock_outlook_env["namespace"].GetItemFromID.return_value = existing_draft

        result = outlook_create_reply_draft_with_attachment(
            body="Updated text with attachment.",
            attachment_path=str(attachment),
            reply_all=True
        )

        assert "aktualisiert" in result

        # Verify NO new reply was created
        mock_outlook_env["mail"].ReplyAll.assert_not_called()

        # Verify existing draft body was updated
        existing_draft.Save.assert_called_once()


class TestTryUpdateCachedDraft:
    """Tests for the _try_update_cached_draft helper function."""

    def test_empty_original_id_returns_none(self):
        """Empty or None original_id should return None immediately."""
        assert _try_update_cached_draft("", "<html>body</html>") is None
        assert _try_update_cached_draft(None, "<html>body</html>") is None

    def test_unknown_id_returns_none(self):
        """ID not in cache should return None."""
        assert _try_update_cached_draft("UNKNOWN_ID", "<html>body</html>") is None
