# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Microsoft Graph MCP - Email Actions Module
==========================================
Email move, flag, and batch action tools via Graph API.
"""

import json
from typing import Optional

try:
    import requests
except ImportError:
    requests = None

from msgraph.base import (
    mcp, require_auth,
    graph_request, get_access_token,
    mcp_log, GRAPH_BASE_URL
)


# =============================================================================
# Helper Functions
# =============================================================================

# Folder name to wellKnownName mapping
WELL_KNOWN_FOLDERS = {
    "inbox": "inbox",
    "drafts": "drafts",
    "sentitems": "sentitems",
    "deleteditems": "deleteditems",
    "junkemail": "junkemail",
    "archive": "archive",
}


def _get_folder_id(folder_name: str, mailbox: str = None) -> Optional[str]:
    """Get folder ID by name.

    Args:
        folder_name: Folder name (e.g., "ToDelete", "ToOffer", "inbox")
        mailbox: Optional mailbox

    Returns:
        Folder ID or None if not found
    """
    # Check if it's a well-known folder
    well_known = WELL_KNOWN_FOLDERS.get(folder_name.lower())

    if mailbox:
        base = f"/users/{mailbox}"
    else:
        base = "/me"

    if well_known:
        # Get well-known folder directly
        endpoint = f"{base}/mailFolders/{well_known}"
        response = graph_request(endpoint)
        if "id" in response:
            return response["id"]

    # Search by displayName
    endpoint = f"{base}/mailFolders"
    params = {"$filter": f"displayName eq '{folder_name}'"}
    response = graph_request(endpoint, params=params)

    folders = response.get("value", [])
    if folders:
        return folders[0].get("id")

    # Try searching in child folders of Inbox
    endpoint = f"{base}/mailFolders/inbox/childFolders"
    response = graph_request(endpoint, params=params)

    folders = response.get("value", [])
    if folders:
        return folders[0].get("id")

    return None


def _create_folder(folder_name: str, mailbox: str = None) -> Optional[str]:
    """Create a mail folder under Inbox.

    Args:
        folder_name: Name for the new folder
        mailbox: Optional mailbox

    Returns:
        New folder ID or None if creation failed
    """
    if mailbox:
        endpoint = f"/users/{mailbox}/mailFolders/inbox/childFolders"
    else:
        endpoint = "/me/mailFolders/inbox/childFolders"

    response = graph_request(endpoint, method="POST", json_body={"displayName": folder_name})

    if "id" in response:
        mcp_log(f"[MsGraph] Created folder: {folder_name}")
        return response["id"]

    return None


# =============================================================================
# MCP Tools - Email Actions
# =============================================================================

@mcp.tool()
@require_auth
def graph_move_email(message_id: str, folder: str, mailbox: str = None) -> str:
    """Move email to a folder via Microsoft Graph API.

    Args:
        message_id: Graph message ID (from graph_search_emails or graph_get_recent_emails)
        folder: Target folder name (e.g., "ToDelete", "ToOffer", "ToPay", "DoneInvoices", "Inbox")
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        Success message or error
    """
    try:
        # Get folder ID
        folder_id = _get_folder_id(folder, mailbox)

        if not folder_id:
            # Try to create the folder
            folder_id = _create_folder(folder, mailbox)
            if not folder_id:
                return f"ERROR: Folder '{folder}' not found and could not be created"

        # Build endpoint
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}/move"
        else:
            endpoint = f"/me/messages/{message_id}/move"

        # Move the message
        response = graph_request(endpoint, method="POST", json_body={"destinationId": folder_id})

        if "error" in response:
            error = response["error"]
            return f"ERROR: {error.get('message', 'Move failed')}"

        if "id" in response:
            mcp_log(f"[MsGraph] Moved message to {folder}")
            return f"SUCCESS: Email moved to {folder}"

        return "ERROR: Move operation returned unexpected response"

    except Exception as e:
        mcp_log(f"[MsGraph] Move error: {e}")
        return f"ERROR: {str(e)}"


@mcp.tool()
@require_auth
def graph_move_email_cross_mailbox(
    message_id: str,
    source_mailbox: str,
    dest_mailbox: str,
    dest_folder: str = "Inbox",
    delete_source: bool = True,
) -> str:
    """Move an email from one mailbox into a DIFFERENT mailbox (cross-mailbox).

    Microsoft Graph's /move action only works within a single mailbox's folder
    tree. To move between two separate mailboxes (e.g. info@ -> thomas@) the
    original message is copied via its full MIME content (all headers, sender,
    received time preserved) into dest_mailbox/dest_folder, and then deleted
    from source_mailbox (true move). Set delete_source=False to copy instead.

    Args:
        message_id: Graph message ID in the SOURCE mailbox
        source_mailbox: Mailbox the message currently lives in (e.g. "info@realvirtual.io")
        dest_mailbox: Mailbox to move it into (e.g. "thomas@realvirtual.io")
        dest_folder: Target folder in dest_mailbox (default "Inbox"; created under Inbox if missing)
        delete_source: True = true move (delete from source after copy); False = copy only

    Returns:
        SUCCESS with the new message ID in the destination, or ERROR
    """
    try:
        if not source_mailbox or not dest_mailbox:
            return "ERROR: source_mailbox and dest_mailbox are both required"

        token = get_access_token()
        if not token:
            return "ERROR: Not authenticated. Use graph_authenticate first."
        auth = {"Authorization": f"Bearer {token}"}

        # 1. Resolve destination folder ID in the destination mailbox
        dest_folder_id = _get_folder_id(dest_folder, dest_mailbox)
        if not dest_folder_id:
            dest_folder_id = _create_folder(dest_folder, dest_mailbox)
        if not dest_folder_id:
            return f"ERROR: Folder '{dest_folder}' not found/creatable in {dest_mailbox}"

        # 2. Fetch the full MIME of the source message (raw bytes, not JSON)
        mime_url = f"{GRAPH_BASE_URL}/users/{source_mailbox}/messages/{message_id}/$value"
        mime_resp = requests.get(mime_url, headers=auth, timeout=60)
        if mime_resp.status_code >= 400:
            return f"ERROR: Could not read source MIME ({mime_resp.status_code}): {mime_resp.text[:200]}"
        mime_bytes = mime_resp.content

        # 3. Create the message in the destination folder from MIME (Content-Type: text/plain, base64 body)
        import base64
        b64_mime = base64.b64encode(mime_bytes).decode("ascii")
        post_url = f"{GRAPH_BASE_URL}/users/{dest_mailbox}/mailFolders/{dest_folder_id}/messages"
        post_headers = {**auth, "Content-Type": "text/plain"}
        create_resp = requests.post(post_url, headers=post_headers, data=b64_mime, timeout=60)
        if create_resp.status_code >= 400:
            return f"ERROR: Could not create message in {dest_mailbox} ({create_resp.status_code}): {create_resp.text[:200]}"
        new_id = create_resp.json().get("id")
        if not new_id:
            return "ERROR: Destination create returned no message ID"

        # 4. Delete from source (true move). Goes to source Deleted Items (recoverable).
        if delete_source:
            del_url = f"{GRAPH_BASE_URL}/users/{source_mailbox}/messages/{message_id}"
            del_resp = requests.delete(del_url, headers=auth, timeout=30)
            if del_resp.status_code >= 400:
                return (f"WARNING: Copied to {dest_mailbox}/{dest_folder} (id {new_id}) but could "
                        f"not delete source ({del_resp.status_code}). Remove source manually.")

        action = "moved" if delete_source else "copied"
        mcp_log(f"[MsGraph] Cross-mailbox {action}: {source_mailbox} -> {dest_mailbox}/{dest_folder}")
        return f"SUCCESS: Email {action} to {dest_mailbox}/{dest_folder} (new id: {new_id})"

    except Exception as e:
        mcp_log(f"[MsGraph] Cross-mailbox move error: {e}")
        return f"ERROR: {str(e)}"


@mcp.tool()
@require_auth
def graph_flag_email(message_id: str, flag_type: str = "followup", mailbox: str = None) -> str:
    """Flag or unflag an email via Microsoft Graph API.

    Args:
        message_id: Graph message ID
        flag_type: Type of flag action:
                   - "followup" - Set follow-up flag
                   - "complete" - Mark as completed
                   - "clear" - Remove flag
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        Success message or error
    """
    try:
        # Map flag_type to Graph API flagStatus
        flag_status_map = {
            "followup": "flagged",
            "complete": "complete",
            "clear": "notFlagged"
        }

        flag_status = flag_status_map.get(flag_type.lower(), "flagged")

        # Build endpoint
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}"
        else:
            endpoint = f"/me/messages/{message_id}"

        # Update the flag
        response = graph_request(endpoint, method="PATCH", json_body={
            "flag": {
                "flagStatus": flag_status
            }
        })

        if "error" in response:
            error = response["error"]
            return f"ERROR: {error.get('message', 'Flag update failed')}"

        if "id" in response:
            mcp_log(f"[MsGraph] Flagged message: {flag_type}")
            return f"SUCCESS: Email flag set to {flag_type}"

        return "ERROR: Flag operation returned unexpected response"

    except Exception as e:
        mcp_log(f"[MsGraph] Flag error: {e}")
        return f"ERROR: {str(e)}"


@mcp.tool()
@require_auth
def graph_batch_email_actions(actions: str) -> str:
    """Execute multiple email actions (move/flag) in a single batch.

    Args:
        actions: JSON array of actions, e.g.:
                 [
                   {"action": "move", "message_id": "AAA...", "folder": "ToDelete"},
                   {"action": "move", "message_id": "BBB...", "folder": "ToOffer", "mailbox": "user@domain.com"},
                   {"action": "flag", "message_id": "CCC...", "flag_type": "followup"}
                 ]

    Returns:
        Summary of executed actions with success/failure counts
    """
    try:
        # Parse actions
        try:
            action_list = json.loads(actions)
        except json.JSONDecodeError as e:
            return f"ERROR: Invalid JSON: {e}"

        if not isinstance(action_list, list):
            return "ERROR: Actions must be a JSON array"

        results = {
            "success": 0,
            "failed": 0,
            "details": []
        }

        for idx, action in enumerate(action_list):
            action_type = action.get("action", "").lower()
            message_id = action.get("message_id", "")
            mailbox = action.get("mailbox")

            if not message_id:
                results["failed"] += 1
                results["details"].append(f"[{idx+1}] ERROR: Missing message_id")
                continue

            try:
                if action_type == "move":
                    folder = action.get("folder", "")
                    if not folder:
                        results["failed"] += 1
                        results["details"].append(f"[{idx+1}] ERROR: Missing folder for move action")
                        continue

                    result = graph_move_email(message_id, folder, mailbox)

                elif action_type == "flag":
                    flag_type = action.get("flag_type", "followup")
                    result = graph_flag_email(message_id, flag_type, mailbox)

                else:
                    results["failed"] += 1
                    results["details"].append(f"[{idx+1}] ERROR: Unknown action type '{action_type}'")
                    continue

                if result.startswith("SUCCESS"):
                    results["success"] += 1
                    results["details"].append(f"[{idx+1}] {result}")
                else:
                    results["failed"] += 1
                    results["details"].append(f"[{idx+1}] {result}")

            except Exception as e:
                results["failed"] += 1
                results["details"].append(f"[{idx+1}] ERROR: {str(e)}")

        # Build summary
        summary = f"Batch completed: {results['success']} success, {results['failed']} failed"
        if results["details"]:
            summary += "\n\nDetails:\n" + "\n".join(results["details"])

        return summary

    except Exception as e:
        mcp_log(f"[MsGraph] Batch error: {e}")
        return f"ERROR: {str(e)}"


# =============================================================================
# Category Tools
# =============================================================================

@mcp.tool()
@require_auth
def graph_list_categories(mailbox: str = None) -> str:
    """List all Outlook categories (master categories).

    Args:
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        JSON list of categories with name and color
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/outlook/masterCategories"
        else:
            endpoint = "/me/outlook/masterCategories"

        response = graph_request(endpoint)

        if "error" in response:
            error = response["error"]
            return f"ERROR: {error.get('message', 'Unknown error')}"

        categories = response.get("value", [])

        return json.dumps({
            "categories": [
                {
                    "name": cat.get("displayName", ""),
                    "color": cat.get("color", ""),
                    "id": cat.get("id", "")
                }
                for cat in categories
            ],
            "count": len(categories)
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        mcp_log(f"[MsGraph] List categories error: {e}")
        return f"ERROR: {str(e)}"


@mcp.tool()
@require_auth
def graph_get_emails_by_category(category: str, folder: str = "Inbox", mailboxes: str = None, limit: int = 50) -> str:
    """Get emails with a specific category via Microsoft Graph API.

    Use this to "select" emails for processing - assign them a category
    in any Outlook client (web, mobile, desktop), then retrieve them here.

    By default ONLY the Inbox folder is searched, so finding e.g. "ToReply"
    emails works with a single deterministic call without needing to build an
    "inbox intersection" yourself. Multiple mailboxes can be queried at once.

    Args:
        category: Category name (e.g., "DeskAgent", "ToReply")
        folder: Folder scope (default: "Inbox"). Use "Inbox" to search only the
                Inbox, a specific folder name like "Archive", or None/""/"all" to
                search the entire mailbox (all folders) like before.
        mailboxes: Comma-separated mailbox addresses to search, e.g.
                   "thomas@realvirtual.io,info@realvirtual.io". None/empty searches
                   the signed-in user (/me). Each returned email carries a "mailbox"
                   field indicating which mailbox it came from.
        limit: Maximum results per mailbox (default: 50, capped at 250)

    Returns:
        JSON with: category, count (total across mailboxes), mailboxes_searched,
        emails (each with mailbox field) and optionally errors (per-mailbox).

    Example (find ToReply across two inboxes):
        graph_get_emails_by_category(
            category="ToReply",
            folder="Inbox",
            mailboxes="thomas@realvirtual.io,info@realvirtual.io"
        )
    """
    try:
        limit = min(limit, 250)

        # Resolve folder scope into endpoint suffix
        if not folder or str(folder).strip().lower() == "all":
            folder_suffix = "/messages"
        else:
            folder_suffix = f"/mailFolders/{folder}/messages"

        # Resolve mailbox list (None/empty -> signed-in user via /me)
        if mailboxes and mailboxes.strip():
            mailbox_list = [m.strip() for m in mailboxes.split(",") if m.strip()]
        else:
            mailbox_list = [None]  # signed-in user

        # Filter for emails with the category
        # Categories is a collection, use 'any' lambda
        filter_query = f"categories/any(c:c eq '{category}')"

        params = {
            "$filter": filter_query,
            "$top": limit,
            "$select": "id,subject,from,receivedDateTime,categories,hasAttachments",
            "$orderby": "receivedDateTime desc"
        }

        all_emails = []
        mailboxes_searched = []
        errors = []

        for mb in mailbox_list:
            if mb:
                endpoint = f"/users/{mb}{folder_suffix}"
                mb_label = mb
            else:
                endpoint = f"/me{folder_suffix}"
                mb_label = ""  # signed-in user, no extra /me request just for the address

            mailboxes_searched.append(mb or "/me")

            try:
                result = graph_request(endpoint, params=params)
            except Exception as e:
                mcp_log(f"[MsGraph] Get emails by category error for mailbox '{mb or '/me'}': {e}")
                errors.append({"mailbox": mb or "/me", "error": str(e)})
                continue

            if "error" in result:
                error = result["error"]
                err_msg = error.get("message", "Unknown error")
                mcp_log(f"[MsGraph] Get emails by category error for mailbox '{mb or '/me'}': {err_msg}")
                errors.append({"mailbox": mb or "/me", "error": err_msg})
                continue

            messages = result.get("value", [])

            for msg in messages:
                sender_data = msg.get("from", {}).get("emailAddress", {})

                all_emails.append({
                    "id": msg.get("id", ""),
                    "entry_id": msg.get("id", ""),  # Alias for compatibility
                    "subject": msg.get("subject", "(No subject)"),
                    "sender_name": sender_data.get("name", "Unknown"),
                    "sender_email": sender_data.get("address", ""),
                    "received": msg.get("receivedDateTime", "")[:10],
                    "categories": msg.get("categories", []),
                    "has_attachments": msg.get("hasAttachments", False),
                    "mailbox": mb_label
                })

        response = {
            "category": category,
            "count": len(all_emails),
            "mailboxes_searched": mailboxes_searched,
            "emails": all_emails
        }
        if errors:
            response["errors"] = errors

        return json.dumps(response, ensure_ascii=False, indent=2)

    except Exception as e:
        mcp_log(f"[MsGraph] Get emails by category error: {e}")
        return json.dumps({"error": str(e), "emails": []}, indent=2)


@mcp.tool()
@require_auth
def graph_set_email_categories(message_id: str, categories: str, mailbox: str = None) -> str:
    """Set categories for an email via Microsoft Graph API.

    Args:
        message_id: Graph message ID
        categories: Comma-separated category names (e.g., "DeskAgent, Important")
                   Use empty string "" to clear all categories
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        Success message or error
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}"
        else:
            endpoint = f"/me/messages/{message_id}"

        # Parse categories
        if categories.strip():
            cat_list = [c.strip() for c in categories.split(",") if c.strip()]
        else:
            cat_list = []

        response = graph_request(endpoint, method="PATCH", json_body={
            "categories": cat_list
        })

        if "error" in response:
            error = response["error"]
            return f"ERROR: {error.get('message', 'Update failed')}"

        if "id" in response:
            if cat_list:
                mcp_log(f"[MsGraph] Set categories: {cat_list}")
                return f"SUCCESS: Categories set to: {', '.join(cat_list)}"
            else:
                mcp_log("[MsGraph] Cleared categories")
                return "SUCCESS: All categories cleared"

        return "ERROR: Update returned unexpected response"

    except Exception as e:
        mcp_log(f"[MsGraph] Set categories error: {e}")
        return f"ERROR: {str(e)}"


@mcp.tool()
@require_auth
def graph_add_email_category(message_id: str, category: str, mailbox: str = None) -> str:
    """Add a category to an email (preserving existing categories).

    Args:
        message_id: Graph message ID
        category: Category name to add (e.g., "DeskAgent")
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        Success message or error
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}"
        else:
            endpoint = f"/me/messages/{message_id}"

        # First get existing categories
        get_response = graph_request(endpoint, params={"$select": "categories"})

        if "error" in get_response:
            error = get_response["error"]
            return f"ERROR: {error.get('message', 'Get failed')}"

        existing = get_response.get("categories", [])

        # Add new category if not present
        if category not in existing:
            existing.append(category)

            response = graph_request(endpoint, method="PATCH", json_body={
                "categories": existing
            })

            if "error" in response:
                error = response["error"]
                return f"ERROR: {error.get('message', 'Update failed')}"

            mcp_log(f"[MsGraph] Added category: {category}")
            return f"SUCCESS: Category '{category}' added"
        else:
            return f"Category '{category}' already present"

    except Exception as e:
        mcp_log(f"[MsGraph] Add category error: {e}")
        return f"ERROR: {str(e)}"


@mcp.tool()
@require_auth
def graph_remove_email_category(message_id: str, category: str, mailbox: str = None) -> str:
    """Remove a category from an email.

    Args:
        message_id: Graph message ID
        category: Category name to remove (e.g., "DeskAgent")
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        Success message or error
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/messages/{message_id}"
        else:
            endpoint = f"/me/messages/{message_id}"

        # First get existing categories
        get_response = graph_request(endpoint, params={"$select": "categories"})

        if "error" in get_response:
            error = get_response["error"]
            return f"ERROR: {error.get('message', 'Get failed')}"

        existing = get_response.get("categories", [])

        # Remove category if present
        if category in existing:
            existing.remove(category)

            response = graph_request(endpoint, method="PATCH", json_body={
                "categories": existing
            })

            if "error" in response:
                error = response["error"]
                return f"ERROR: {error.get('message', 'Update failed')}"

            mcp_log(f"[MsGraph] Removed category: {category}")
            return f"SUCCESS: Category '{category}' removed"
        else:
            return f"Category '{category}' not present"

    except Exception as e:
        mcp_log(f"[MsGraph] Remove category error: {e}")
        return f"ERROR: {str(e)}"


# =============================================================================
# Folder Tools
# =============================================================================

@mcp.tool()
@require_auth
def graph_list_folders(mailbox: str = None) -> str:
    """List all mail folders via Microsoft Graph API.

    Args:
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        JSON list of folders with id, displayName, and item counts
    """
    try:
        if mailbox:
            endpoint = f"/users/{mailbox}/mailFolders"
        else:
            endpoint = "/me/mailFolders"

        params = {
            "$select": "id,displayName,totalItemCount,unreadItemCount,childFolderCount",
            "$top": 100
        }

        response = graph_request(endpoint, params=params)

        if "error" in response:
            error = response["error"]
            return f"ERROR: {error.get('message', 'Unknown error')}"

        folders = response.get("value", [])

        # Also get child folders of Inbox
        inbox_children_endpoint = f"{endpoint}/inbox/childFolders"
        child_response = graph_request(inbox_children_endpoint, params=params)
        child_folders = child_response.get("value", [])

        # Mark child folders
        for cf in child_folders:
            cf["parent"] = "Inbox"

        all_folders = folders + child_folders

        return json.dumps({
            "folders": all_folders,
            "count": len(all_folders)
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        mcp_log(f"[MsGraph] List folders error: {e}")
        return f"ERROR: {str(e)}"
