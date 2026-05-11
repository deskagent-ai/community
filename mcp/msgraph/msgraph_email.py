# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Microsoft Graph MCP - Email Module
===================================
Email search, read, and management tools.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

from msgraph.base import (
    mcp, require_auth,
    graph_request, MessageFormatter, html_to_text,
    mcp_log
)

# Import link utilities for link_ref generation
import sys
mcp_root = str(Path(__file__).parent.parent)
if mcp_root not in sys.path:
    sys.path.insert(0, mcp_root)
from _link_utils import make_link_ref, LINK_TYPE_EMAIL
from _mcp_api import register_link

# Import shared email utilities
try:
    import sys
    scripts_path = str(Path(__file__).parent.parent.parent / "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    from email_utils import strip_markdown_fences
except ImportError:
    def strip_markdown_fences(text):
        return text


# =============================================================================
# Helper Functions
# =============================================================================


def _sanitize_search_query(query: str) -> tuple[str, dict]:
    """Clean up search query and extract filter parameters.

    Graph API $search only supports simple keyword searches.
    Complex operators must be converted or moved to $filter.

    Returns:
        (cleaned_query, filter_options)
    """
    filter_opts = {}
    cleaned = query

    # Remove unsupported operators and extract filter info
    # has:attachment -> filter
    if re.search(r'\bhas:attachment\b', cleaned, re.IGNORECASE):
        filter_opts['hasAttachments'] = True
        cleaned = re.sub(r'\bhas:attachment\b', '', cleaned, flags=re.IGNORECASE)

    # received:YYYY-MM-DD..YYYY-MM-DD -> filter (date range)
    date_range = re.search(r'received:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})', cleaned)
    if date_range:
        filter_opts['dateFrom'] = date_range.group(1)
        filter_opts['dateTo'] = date_range.group(2)
        cleaned = re.sub(r'received:\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}', '', cleaned)

    # Single date: received:YYYY-MM-DD
    single_date = re.search(r'received:(\d{4}-\d{2}-\d{2})', cleaned)
    if single_date:
        filter_opts['dateFrom'] = single_date.group(1)
        filter_opts['dateTo'] = single_date.group(1)
        cleaned = re.sub(r'received:\d{4}-\d{2}-\d{2}', '', cleaned)

    # Remove unsupported operators (AND, OR, subject:, from:, etc.)
    # These don't work in $search, convert to simple keywords
    cleaned = re.sub(r'\bAND\b', ' ', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bOR\b', ' ', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'subject:', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'from:', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'to:', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'body:', '', cleaned, flags=re.IGNORECASE)

    # Remove parentheses (not supported)
    cleaned = re.sub(r'[()]', ' ', cleaned)

    # Remove ALL quotes - Graph API $search wraps the entire query in quotes,
    # so internal quotes cause syntax errors (400 Bad Request)
    # e.g. '"newsletter" OR "spam"' -> 'newsletter spam' -> $search="newsletter spam"
    cleaned = cleaned.replace('"', '')

    # Clean up whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return cleaned, filter_opts


# =============================================================================
# MCP Tools - Email Search
# =============================================================================

@mcp.tool()
@require_auth
def graph_search_emails(query: str, limit: int = 50, mailbox: str = None,
                        has_attachments: bool = None, date_from: str = None, date_to: str = None) -> str:
    """Search emails using Microsoft Graph API (server-side search).

    This searches ALL emails on Exchange server, not just locally cached ones.

    IMPORTANT: Use simple keyword searches only! Complex operators don't work.

    Args:
        query: Simple keyword search (words, email addresses, phrases)
               GOOD: "EnBW Rechnung", "invoice adobe", "john@example.com"
               BAD: "subject:invoice AND from:adobe" (operators don't work!)
        limit: Maximum results (default: 50, max: 250)
        mailbox: Optional mailbox to search (default: signed-in user)
        has_attachments: Filter to emails with attachments only (optional)
        date_from: Filter emails from this date, format YYYY-MM-DD (optional)
        date_to: Filter emails until this date, format YYYY-MM-DD (optional)

    Returns:
        List of matching emails with date, sender, and subject
    """
    try:
        limit = min(limit, 250)

        # Build search endpoint
        if mailbox:
            endpoint = f"/users/{mailbox}/messages"
        else:
            endpoint = "/me/messages"

        # Sanitize query - remove unsupported operators
        cleaned_query, extracted_filters = _sanitize_search_query(query)
        if cleaned_query != query:
            mcp_log(f"[MsGraph] Query sanitized: '{query}' -> '{cleaned_query}'")

        # Merge extracted filters with explicit parameters (explicit wins)
        if has_attachments is None and 'hasAttachments' in extracted_filters:
            has_attachments = extracted_filters['hasAttachments']
        if date_from is None and 'dateFrom' in extracted_filters:
            date_from = extracted_filters['dateFrom']
        if date_to is None and 'dateTo' in extracted_filters:
            date_to = extracted_filters['dateTo']

        # Build filter conditions
        filter_parts = []
        if has_attachments:
            filter_parts.append("hasAttachments eq true")
        if date_from:
            filter_parts.append(f"receivedDateTime ge {date_from}T00:00:00Z")
        if date_to:
            filter_parts.append(f"receivedDateTime le {date_to}T23:59:59Z")

        # Use $search for keyword query (server-side search)
        # NOTE: $search CANNOT be combined with $orderby (Graph API limitation)
        # NOTE: $search CAN be combined with $filter
        params = {
            "$top": limit,
            "$select": "id,subject,from,receivedDateTime,isRead,hasAttachments,parentFolderId,conversationId"
        }

        # Only add $search if we have keywords
        if cleaned_query:
            params["$search"] = f'"{cleaned_query}"'

        # Add $filter if we have filter conditions
        if filter_parts:
            params["$filter"] = " and ".join(filter_parts)
            # When using $filter without $search, we can use $orderby
            if not cleaned_query:
                params["$orderby"] = "receivedDateTime desc"

        search_desc = cleaned_query or "(filter only)"
        if filter_parts:
            search_desc += f" [filter: {', '.join(filter_parts)}]"
        mcp_log(f"[MsGraph] Searching: {search_desc}")

        result = graph_request(endpoint, params=params)

        messages = result.get("value", [])

        # Sort by date (newest first) - must be done client-side since $orderby doesn't work with $search
        messages.sort(key=lambda m: m.get("receivedDateTime", ""), reverse=True)

        if not messages:
            return f"No emails found for '{query}'"

        # Format results using MessageFormatter
        formatted = []
        for msg in messages:
            try:
                formatted.append(MessageFormatter.format_email_list_item(msg, show_id=True))
            except Exception as e:
                mcp_log(f"[MsGraph] Format error: {e}")
                continue

        return f"Search results for '{query}' ({len(messages)} emails, via Microsoft Graph):\n" + "\n".join(formatted)

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def graph_get_recent_emails(days: int = 7, limit: int = 50, mailbox: str = None, inbox_only: bool = True, exclude_categories: str = None) -> str:
    """Get recent emails from the last N days via Microsoft Graph.

    Args:
        days: Number of days to look back (default: 7)
        limit: Maximum results (default: 50)
        mailbox: Optional mailbox (default: signed-in user)
        inbox_only: If True (default), only query Inbox folder. If False, query all folders.
        exclude_categories: Comma-separated category names to exclude (e.g., "IsDone,Processed")

    Returns:
        List of recent emails with date, sender, subject
    """
    try:
        limit = min(limit, 250)
        since_date = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"

        if mailbox:
            if inbox_only:
                endpoint = f"/users/{mailbox}/mailFolders/Inbox/messages"
            else:
                endpoint = f"/users/{mailbox}/messages"
        else:
            if inbox_only:
                endpoint = "/me/mailFolders/Inbox/messages"
            else:
                endpoint = "/me/messages"

        # Build filter with optional category exclusion
        filter_parts = [f"receivedDateTime ge {since_date}"]

        if exclude_categories:
            # Exclude emails with any of the specified categories
            for cat in exclude_categories.split(","):
                cat = cat.strip()
                if cat:
                    filter_parts.append(f"NOT categories/any(c:c eq '{cat}')")

        params = {
            "$filter": " and ".join(filter_parts),
            "$top": limit,
            "$select": "id,subject,from,receivedDateTime,isRead,hasAttachments,conversationId,categories",
            "$orderby": "receivedDateTime desc"
        }

        result = graph_request(endpoint, params=params)
        messages = result.get("value", [])

        if not messages:
            folder_info = "Inbox" if inbox_only else "all folders"
            return f"No emails in the last {days} days ({folder_info})"

        # Format results using MessageFormatter
        formatted = [MessageFormatter.format_email_list_item(msg, show_id=True) for msg in messages]

        folder_info = "Inbox only" if inbox_only else "all folders"
        return f"Recent emails (last {days} days, {len(messages)} found, {folder_info}):\n" + "\n".join(formatted)

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def graph_get_email(message_id: str, mailbox: str = None) -> str:
    """Get full email content by message ID.

    Args:
        message_id: The email message ID (from search results)
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        Full email content including body
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}"
        else:
            endpoint = f"/me/messages/{message_id}"

        params = {
            "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments,attachments"
        }

        msg = graph_request(endpoint, params=params)

        # Format email using MessageFormatter
        from_str = MessageFormatter.format_email_address(msg.get("from", {}))
        to_list = [r.get("emailAddress", {}).get("address", "") for r in msg.get("toRecipients", [])]
        cc_list = [r.get("emailAddress", {}).get("address", "") for r in msg.get("ccRecipients", [])]

        body = msg.get("body", {})
        body_content = body.get("content", "")

        # Convert HTML to readable text
        if body.get("contentType") == "html":
            body_content = html_to_text(body_content, mode="full")

        output = f"""From: {from_str}
To: {', '.join(to_list)}
Cc: {', '.join(cc_list) if cc_list else '-'}
Date: {msg.get('receivedDateTime', '')}
Subject: {msg.get('subject', '')}
Attachments: {'Yes' if msg.get('hasAttachments') else 'No'}

{body_content[:5000]}"""

        return output

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def graph_get_attachments(message_id: str, mailbox: str = None) -> str:
    """List attachments of an email.

    Args:
        message_id: The email message ID (from search results)
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        List of attachments with index, name, and size
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}/attachments"
        else:
            endpoint = f"/me/messages/{message_id}/attachments"

        result = graph_request(endpoint)
        attachments = result.get("value", [])

        if not attachments:
            return "No attachments"

        formatted = []
        for i, att in enumerate(attachments):
            name = att.get("name", "Unknown")
            size = att.get("size", 0)
            content_type = att.get("contentType", "")
            att_id = att.get("id", "")

            size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
            # IMPORTANT: Do NOT truncate attachment IDs - they are needed for download!
            formatted.append(f"[{i}] {name} ({size_str})\n    attachment_id: {att_id}")

        return f"Attachments ({len(attachments)}):\n" + "\n".join(formatted)

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def graph_download_attachment(message_id: str, attachment_id: str, save_path: str = None, mailbox: str = None) -> str:
    """Download an email attachment.

    Args:
        message_id: The email message ID
        attachment_id: The attachment ID (from graph_get_attachments - use FULL ID!)
        save_path: Directory to save the file (default: current directory)
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        SUCCESS: file path and size if download verified
        ERROR: detailed error message if failed
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}/attachments/{attachment_id}"
        else:
            endpoint = f"/me/messages/{message_id}/attachments/{attachment_id}"

        mcp_log(f"[MsGraph] Downloading attachment: {attachment_id[:50]}...")
        result = graph_request(endpoint)

        name = result.get("name", "attachment")
        content_bytes = result.get("contentBytes", "")

        if not content_bytes:
            return "ERROR: No content in attachment (empty response from API)"

        # Decode base64 content
        import base64
        try:
            file_content = base64.b64decode(content_bytes)
        except Exception as e:
            return f"ERROR: Failed to decode attachment content: {e}"

        if len(file_content) == 0:
            return "ERROR: Decoded content is empty"

        # Determine save path
        if save_path:
            save_dir = Path(save_path)
        else:
            save_dir = Path.cwd()

        save_dir.mkdir(parents=True, exist_ok=True)
        file_path = save_dir / name

        # Write file
        with open(file_path, "wb") as f:
            f.write(file_content)

        # VERIFY file was actually saved
        if not file_path.exists():
            return f"ERROR: File write failed - {file_path} does not exist after write"

        actual_size = file_path.stat().st_size
        if actual_size != len(file_content):
            return f"ERROR: File size mismatch - expected {len(file_content)}, got {actual_size}"

        mcp_log(f"[MsGraph] Downloaded: {file_path} ({actual_size} bytes)")
        return f"SUCCESS: Downloaded and verified: {file_path} ({actual_size} bytes)"

    except requests.exceptions.HTTPError as e:
        return f"ERROR: HTTP {e.response.status_code} - {e.response.reason}. Check message_id and attachment_id are correct and complete."
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
@require_auth
def graph_list_mailboxes() -> str:
    """List available mailboxes/shared mailboxes the user has access to."""
    try:
        # Get user's own mailbox
        user = graph_request("/me")
        mailboxes = [f"- {user.get('mail', user.get('userPrincipalName', 'Primary'))} (primary)"]

        # Note: Listing shared mailboxes requires additional permissions
        # For now, just show the primary mailbox

        return "Available mailboxes:\n" + "\n".join(mailboxes) + "\n\nNote: Use the email address as 'mailbox' parameter to search other mailboxes you have access to."

    except Exception as e:
        return f"ERROR: {e}"


# NOTE: graph_list_folders is now defined in actions.py
# This function remains for internal use if needed, but is not exposed as MCP tool
@require_auth
def _graph_list_folders_internal(mailbox: str = None) -> str:
    """List mail folders (internal use).

    Args:
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        List of folders with IDs and names
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/mailFolders"
        else:
            endpoint = "/me/mailFolders"

        params = {"$top": 100}
        result = graph_request(endpoint, params=params)
        folders = result.get("value", [])

        if not folders:
            return "No folders found"

        formatted = []
        for f in folders:
            folder_id = f.get("id", "")
            name = f.get("displayName", "Unknown")
            total = f.get("totalItemCount", 0)
            unread = f.get("unreadItemCount", 0)

            formatted.append(f"- {name} ({total} items, {unread} unread) - ID: {folder_id[:15]}...")

        return f"Mail Folders ({len(folders)}):\n" + "\n".join(formatted)

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def graph_get_folder_emails(folder_name: str, limit: int = 50, mailbox: str = None) -> str:
    """Get emails from a specific folder.

    Use this for work queues like ToOffer, ToPay, DoneInvoices.
    Returns JSON with entry_id for graph_batch_email_actions().

    Args:
        folder_name: Folder name (e.g., "ToOffer", "ToPay", "Inbox")
        limit: Maximum results (default: 50)
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        JSON array of emails with id, subject, sender, received, has_attachments
    """
    import json

    try:
        # First, find the folder by name
        if mailbox:
            folders_endpoint = f"/users/{mailbox}/mailFolders"
        else:
            folders_endpoint = "/me/mailFolders"

        # Get all folders (including child folders)
        params = {"$top": 200}
        folders_result = graph_request(folders_endpoint, params=params)
        folders = folders_result.get("value", [])

        # Also check child folders (one level deep)
        for parent in folders[:]:
            child_endpoint = f"{folders_endpoint}/{parent['id']}/childFolders"
            try:
                child_result = graph_request(child_endpoint, params={"$top": 50})
                folders.extend(child_result.get("value", []))
            except (requests.RequestException, KeyError, ValueError):
                pass  # No child folders or no access

        # Find matching folder (case-insensitive)
        folder_id = None
        folder_display_name = None
        for f in folders:
            if f.get("displayName", "").lower() == folder_name.lower():
                folder_id = f.get("id")
                folder_display_name = f.get("displayName")
                break

        if not folder_id:
            # List available folders for help
            available = [f.get("displayName") for f in folders if f.get("displayName")]
            return json.dumps({
                "error": f"Folder '{folder_name}' not found",
                "available_folders": available[:20],
                "emails": []
            }, indent=2)

        # Get emails from the folder
        if mailbox:
            messages_endpoint = f"/users/{mailbox}/mailFolders/{folder_id}/messages"
        else:
            messages_endpoint = f"/me/mailFolders/{folder_id}/messages"

        params = {
            "$top": min(limit, 250),
            "$select": "id,subject,from,receivedDateTime,isRead,hasAttachments,conversationId,flag,webLink",
            "$orderby": "receivedDateTime desc"
        }

        result = graph_request(messages_endpoint, params=params)
        messages = result.get("value", [])

        if not messages:
            return json.dumps({
                "folder": folder_display_name,
                "count": 0,
                "emails": []
            }, indent=2)

        emails = []
        for msg in messages:
            sender_data = msg.get("from", {}).get("emailAddress", {})
            flag_status = msg.get("flag", {}).get("flagStatus", "notFlagged")
            msg_id = msg.get("id", "")

            # V2 Link System: Register URL, only expose link_ref to AI
            link_ref = make_link_ref(msg_id, LINK_TYPE_EMAIL)
            web_link = msg.get("webLink", "")
            if web_link:
                register_link(link_ref, web_link)

            emails.append({
                "id": msg_id,
                "link_ref": link_ref,
                "entry_id": msg_id,  # Alias for compatibility with batch_email_actions
                "conversation_id": msg.get("conversationId", ""),  # For thread deduplication
                "subject": msg.get("subject", "(No subject)"),
                "sender_name": sender_data.get("name", "Unknown"),
                "sender_email": sender_data.get("address", ""),
                "received": msg.get("receivedDateTime", "")[:10],  # YYYY-MM-DD
                "is_read": msg.get("isRead", False),
                "has_attachments": msg.get("hasAttachments", False),
                "flag_status": flag_status,  # "notFlagged", "flagged", or "complete"
            })

        return json.dumps({
            "folder": folder_display_name,
            "count": len(emails),
            "emails": emails
        }, indent=2)

    except Exception as e:
        import json
        return json.dumps({"error": str(e), "emails": []}, indent=2)


# NOTE: graph_move_email is now defined in actions.py with better error handling
# This function remains for internal use if needed, but is not exposed as MCP tool
@require_auth
def _graph_move_email_internal(message_id: str, destination_folder: str, mailbox: str = None) -> str:
    """Move an email to a different folder (internal use).

    Args:
        message_id: The email message ID
        destination_folder: Folder ID or well-known name (inbox, drafts, sentitems, deleteditems, archive)
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        Confirmation or error
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}/move"
        else:
            endpoint = f"/me/messages/{message_id}/move"

        body = {"destinationId": destination_folder}
        result = graph_request(endpoint, method="POST", json_body=body)

        return f"Email moved to {destination_folder}"

    except Exception as e:
        return f"ERROR: {e}"


# NOTE: graph_flag_email is now defined in actions.py with better error handling
# This function remains for internal use if needed, but is not exposed as MCP tool
@require_auth
def _graph_flag_email_internal(message_id: str, flag_status: str = "flagged", mailbox: str = None) -> str:
    """Flag or unflag an email (internal use).

    Args:
        message_id: The email message ID
        flag_status: "flagged", "complete", or "notFlagged"
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        Confirmation or error
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}"
        else:
            endpoint = f"/me/messages/{message_id}"

        # Map flag status
        status_map = {
            "flagged": "flagged",
            "complete": "complete",
            "notflagged": "notFlagged",
            "clear": "notFlagged"
        }
        flag_value = status_map.get(flag_status.lower(), "flagged")

        body = {
            "flag": {
                "flagStatus": flag_value
            }
        }

        result = graph_request(endpoint, method="PATCH", json_body=body)
        return f"Email flag set to: {flag_value}"

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def graph_delete_email(message_id: str, mailbox: str = None) -> str:
    """Delete an email (moves to Deleted Items).

    Args:
        message_id: The email message ID
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        Confirmation or error
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}"
        else:
            endpoint = f"/me/messages/{message_id}"

        graph_request(endpoint, method="DELETE")
        return "Email deleted"

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def graph_create_draft(to: str, subject: str, body: str, cc: str = None) -> str:
    """Create an email draft (does NOT send).

    Args:
        to: Recipient email address(es), comma-separated
        subject: Email subject
        body: Email body (plain text)
        cc: Optional CC recipients, comma-separated

    Returns:
        Draft ID or error
    """
    try:
        to_recipients = [{"emailAddress": {"address": addr.strip()}} for addr in to.split(",")]
        cc_recipients = [{"emailAddress": {"address": addr.strip()}} for addr in cc.split(",")] if cc else []

        message = {
            "subject": subject,
            "body": {
                "contentType": "text",
                "content": body
            },
            "toRecipients": to_recipients,
            "ccRecipients": cc_recipients,
            "isDraft": True
        }

        result = graph_request("/me/messages", method="POST", json_body=message)
        draft_id = result.get("id", "")

        return f"Draft created in Drafts folder. ID: {draft_id}"

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def graph_create_reply_draft(message_id: str, body: str, reply_all: bool = True, mailbox: str = None) -> str:
    """Create a reply draft (does NOT send).

    Automatically cleans up markdown code fences from LLM output.

    Args:
        message_id: The email message ID to reply to
        body: Reply body text
        reply_all: If True, reply to all recipients (default: True)
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        Draft ID or error
    """
    # Clean markdown fences from agent output
    body = strip_markdown_fences(body)

    try:
        if mailbox:
            base = f"/users/{mailbox}/messages/{message_id}"
        else:
            base = f"/me/messages/{message_id}"

        # Create reply draft (not send)
        endpoint = f"{base}/createReplyAll" if reply_all else f"{base}/createReply"

        result = graph_request(endpoint, method="POST", json_body={})
        draft_id = result.get("id", "")

        # Update the draft: prepend reply text BEFORE existing body (signature + thread)
        if draft_id and body:
            # Read existing draft body (contains signature + quoted original)
            draft_endpoint = f"/me/messages/{draft_id}"
            draft = graph_request(draft_endpoint, method="GET")
            existing_body = draft.get("body", {})
            existing_content = existing_body.get("content", "")
            content_type = existing_body.get("contentType", "html")

            # Convert reply text to HTML paragraphs
            reply_paragraphs = body.replace("\n\n", "</p><p>").replace("\n", "<br>")
            reply_html = f"<p>{reply_paragraphs}</p><br>"

            if content_type.lower() == "html" and existing_content:
                # Insert reply before existing content (signature + thread)
                # Find <body> tag or start of content
                body_match = re.search(r'(<body[^>]*>)', existing_content, re.IGNORECASE)
                if body_match:
                    insert_pos = body_match.end()
                    new_content = existing_content[:insert_pos] + reply_html + existing_content[insert_pos:]
                else:
                    new_content = reply_html + existing_content
            else:
                new_content = reply_html + existing_content

            update_body = {
                "body": {
                    "contentType": "html",
                    "content": new_content
                }
            }
            graph_request(draft_endpoint, method="PATCH", json_body=update_body)

        return f"Reply draft created in Drafts folder. ID: {draft_id}"

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def graph_mark_read(message_id: str, is_read: bool = True, mailbox: str = None) -> str:
    """Mark an email as read or unread.

    Args:
        message_id: The email message ID
        is_read: True to mark as read, False for unread
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        Confirmation or error
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}"
        else:
            endpoint = f"/me/messages/{message_id}"

        body = {"isRead": is_read}
        graph_request(endpoint, method="PATCH", json_body=body)

        return f"Email marked as {'read' if is_read else 'unread'}"

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def graph_get_flagged_emails(limit: int = 50, include_completed: bool = False,
                              mailbox: str = None, exclude_folders: list = None) -> str:
    """Get flagged emails via Microsoft Graph API.

    Use this to "select" emails for processing - flag them in any Outlook client
    (web, mobile, desktop), then retrieve them here.

    Args:
        limit: Maximum results (default: 50)
        include_completed: Include completed flags (default: False, only active flags)
        mailbox: Optional mailbox (default: signed-in user)
        exclude_folders: List of folder names to exclude (default: ["Done"] - emails in
                        these folders are filtered out). Pass empty list [] to include all.

    Returns:
        JSON with flagged emails: {"flagged": [...], "completed": [...]}
        Each email has: id, subject, sender, received, flag_status, has_attachments
    """
    # Default: exclude Done folder (already processed emails)
    if exclude_folders is None:
        exclude_folders = ["Done"]
    import json

    try:
        limit = min(limit, 250)

        if mailbox:
            endpoint = f"/users/{mailbox}/messages"
        else:
            endpoint = "/me/messages"

        # Filter for flagged emails
        if include_completed:
            filter_query = "flag/flagStatus ne 'notFlagged'"
        else:
            filter_query = "flag/flagStatus eq 'flagged'"

        params = {
            "$filter": filter_query,
            "$top": limit,
            "$select": "id,subject,from,receivedDateTime,flag,hasAttachments,conversationId,parentFolderId,webLink"
            # Note: $orderby not supported with flag/flagStatus filter - sort in Python
        }

        result = graph_request(endpoint, params=params)
        messages = result.get("value", [])

        # Sort by receivedDateTime desc (newest first)
        messages.sort(key=lambda m: m.get("receivedDateTime", ""), reverse=True)

        # Build folder ID to name lookup
        folder_lookup = {}
        try:
            folder_endpoint = f"/users/{mailbox}/mailFolders" if mailbox else "/me/mailFolders"
            folder_result = graph_request(folder_endpoint, params={"$top": 100})
            for f in folder_result.get("value", []):
                folder_lookup[f.get("id", "")] = f.get("displayName", "Unknown")
        except Exception:
            pass  # Folder lookup is optional

        # Separate flagged and completed
        flagged = []
        completed = []
        skipped_folders = 0

        for msg in messages:
            flag_status = msg.get("flag", {}).get("flagStatus", "notFlagged")
            parent_folder_id = msg.get("parentFolderId", "")
            folder_name = folder_lookup.get(parent_folder_id, "")

            # Skip emails in excluded folders
            if exclude_folders and folder_name in exclude_folders:
                skipped_folders += 1
                continue

            msg_id = msg.get("id", "")

            # V2 Link System: Register URL, only expose link_ref to AI
            link_ref = make_link_ref(msg_id, LINK_TYPE_EMAIL)
            web_link = msg.get("webLink", "")
            if web_link:
                register_link(link_ref, web_link)

            email_data = {
                "id": msg_id,
                "link_ref": link_ref,
                "conversation_id": msg.get("conversationId", ""),  # For thread deduplication
                "subject": msg.get("subject", ""),
                "sender": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                "sender_name": msg.get("from", {}).get("emailAddress", {}).get("name", ""),
                "received": msg.get("receivedDateTime", ""),
                "flag_status": flag_status,
                "has_attachments": msg.get("hasAttachments", False),
                "folder": folder_name,
            }

            if flag_status == "complete":
                completed.append(email_data)
            else:
                flagged.append(email_data)

        output = {
            "flagged": flagged,
            "completed": completed,
            "total": len(flagged) + len(completed),
            "skipped_excluded_folders": skipped_folders
        }

        return json.dumps(output, indent=2, ensure_ascii=False)

    except Exception as e:
        return f"ERROR: {e}"
