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
def graph_get_emails_by_category(category: str, limit: int = 50, mailbox: str = None) -> str:
    """Get emails with a specific category via Microsoft Graph API.

    Use this to "select" emails for processing - assign them a category
    in any Outlook client (web, mobile, desktop), then retrieve them here.

    Args:
        category: Category name (e.g., "DeskAgent", "To Reply")
        limit: Maximum results (default: 50)
        mailbox: Optional mailbox (default: signed-in user)

    Returns:
        JSON with emails that have the specified category
    """
    try:
        limit = min(limit, 250)

        if mailbox:
            endpoint = f"/users/{mailbox}/messages"
        else:
            endpoint = "/me/messages"

        # Filter for emails with the category
        # Categories is a collection, use 'any' lambda
        filter_query = f"categories/any(c:c eq '{category}')"

        params = {
            "$filter": filter_query,
            "$top": limit,
            "$select": "id,subject,from,receivedDateTime,categories,hasAttachments",
            "$orderby": "receivedDateTime desc"
        }

        result = graph_request(endpoint, params=params)

        if "error" in result:
            error = result["error"]
            return json.dumps({"error": error.get("message", "Unknown error"), "emails": []}, indent=2)

        messages = result.get("value", [])

        emails = []
        for msg in messages:
            sender_data = msg.get("from", {}).get("emailAddress", {})

            emails.append({
                "id": msg.get("id", ""),
                "entry_id": msg.get("id", ""),  # Alias for compatibility
                "subject": msg.get("subject", "(No subject)"),
                "sender_name": sender_data.get("name", "Unknown"),
                "sender_email": sender_data.get("address", ""),
                "received": msg.get("receivedDateTime", "")[:10],
                "categories": msg.get("categories", []),
                "has_attachments": msg.get("hasAttachments", False)
            })

        return json.dumps({
            "category": category,
            "count": len(emails),
            "emails": emails
        }, ensure_ascii=False, indent=2)

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
