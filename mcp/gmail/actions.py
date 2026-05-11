# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Gmail MCP - Actions Module
==========================
Label management, batch operations, and message actions.
"""

import json

from gmail.base import (
    mcp, gmail_tool, require_auth,
    get_gmail_service
)
from _mcp_api import mcp_log


@mcp.tool()
@gmail_tool
@require_auth
def gmail_list_labels() -> str:
    """List all Gmail labels (similar to folders in Outlook).

    Returns:
        JSON list of labels with ID, name, and type
    """
    service = get_gmail_service()

    results = service.users().labels().list(userId='me').execute()
    labels = results.get('labels', [])

    # Group by type
    system_labels = []
    user_labels = []

    for label in labels:
        label_info = {
            "id": label.get("id"),
            "name": label.get("name"),
            "type": label.get("type"),
            "message_count": label.get("messagesTotal", 0),
            "unread_count": label.get("messagesUnread", 0)
        }
        if label.get("type") == "system":
            system_labels.append(label_info)
        else:
            user_labels.append(label_info)

    return json.dumps({
        "system_labels": sorted(system_labels, key=lambda x: x["name"]),
        "user_labels": sorted(user_labels, key=lambda x: x["name"])
    }, ensure_ascii=False, indent=2)


@mcp.tool()
@gmail_tool
@require_auth
def gmail_create_label(
    name: str,
    background_color: str = "#999999",
    text_color: str = "#ffffff"
) -> str:
    """Create a new Gmail label.

    Args:
        name: Label name (can use "/" for nested labels, e.g., "Work/Projects")
        background_color: Hex color for label background (default: gray)
        text_color: Hex color for label text (default: white)

    Returns:
        Created label details
    """
    service = get_gmail_service()

    label_body = {
        "name": name,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
        "color": {
            "backgroundColor": background_color,
            "textColor": text_color
        }
    }

    label = service.users().labels().create(
        userId='me',
        body=label_body
    ).execute()

    return f"""Label created successfully!

ID: {label.get('id')}
Name: {label.get('name')}
Type: {label.get('type')}

You can now use gmail_add_label(message_id, '{name}') to apply this label."""


@mcp.tool()
@gmail_tool
@require_auth
def gmail_delete_label(label_id: str) -> str:
    """Delete a Gmail label.

    Args:
        label_id: Label ID (from gmail_list_labels)
                  Note: Cannot delete system labels.

    Returns:
        Confirmation
    """
    service = get_gmail_service()

    # Check if system label
    try:
        label = service.users().labels().get(userId='me', id=label_id).execute()
        if label.get("type") == "system":
            return f"ERROR: Cannot delete system label '{label.get('name')}'"
    except Exception:
        pass

    service.users().labels().delete(userId='me', id=label_id).execute()

    return f"Label {label_id} deleted successfully."


@mcp.tool()
@gmail_tool
@require_auth
def gmail_add_label(
    message_id: str,
    label: str,
    auto_create: bool = True
) -> str:
    """Add a label to an email (similar to moving to folder in Outlook).

    Auto-creates the label if it doesn't exist (default behavior).

    Args:
        message_id: Message ID
        label: Label name or ID
        auto_create: Create label if it doesn't exist (default: True)

    Returns:
        Confirmation
    """
    service = get_gmail_service()

    # Get or create label ID
    label_id = _get_or_create_label_id(service, label, auto_create=auto_create)
    if not label_id:
        return f"ERROR: Label '{label}' not found and auto_create is disabled."

    service.users().messages().modify(
        userId='me',
        id=message_id,
        body={'addLabelIds': [label_id]}
    ).execute()

    return f"Added label '{label}' to message {message_id}."


@mcp.tool()
@gmail_tool
@require_auth
def gmail_remove_label(
    message_id: str,
    label: str
) -> str:
    """Remove a label from an email.

    Args:
        message_id: Message ID
        label: Label name or ID

    Returns:
        Confirmation
    """
    service = get_gmail_service()

    # Get label ID if name provided
    label_id = _get_label_id(service, label)
    if not label_id:
        return f"ERROR: Label '{label}' not found."

    service.users().messages().modify(
        userId='me',
        id=message_id,
        body={'removeLabelIds': [label_id]}
    ).execute()

    return f"Removed label '{label}' from message {message_id}."


@mcp.tool()
@gmail_tool
@require_auth
def gmail_star_email(
    message_id: str,
    starred: bool = True
) -> str:
    """Star or unstar an email (similar to flagging in Outlook).

    Args:
        message_id: Message ID
        starred: True to star, False to unstar (default: True)

    Returns:
        Confirmation
    """
    service = get_gmail_service()

    if starred:
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'addLabelIds': ['STARRED']}
        ).execute()
        return f"Starred message {message_id}."
    else:
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['STARRED']}
        ).execute()
        return f"Unstarred message {message_id}."


@mcp.tool()
@gmail_tool
@require_auth
def gmail_archive_email(message_id: str) -> str:
    """Archive an email (remove from Inbox, keep in All Mail).

    Args:
        message_id: Message ID

    Returns:
        Confirmation
    """
    service = get_gmail_service()

    service.users().messages().modify(
        userId='me',
        id=message_id,
        body={'removeLabelIds': ['INBOX']}
    ).execute()

    return f"Archived message {message_id}. (Removed from Inbox, still in All Mail)"


@mcp.tool()
@gmail_tool
@require_auth
def gmail_trash_email(message_id: str) -> str:
    """Move an email to Trash (similar to delete in Outlook).

    Args:
        message_id: Message ID

    Returns:
        Confirmation
    """
    service = get_gmail_service()

    service.users().messages().trash(
        userId='me',
        id=message_id
    ).execute()

    return f"Moved message {message_id} to Trash."


@mcp.tool()
@gmail_tool
@require_auth
def gmail_untrash_email(message_id: str) -> str:
    """Restore an email from Trash.

    Args:
        message_id: Message ID

    Returns:
        Confirmation
    """
    service = get_gmail_service()

    service.users().messages().untrash(
        userId='me',
        id=message_id
    ).execute()

    return f"Restored message {message_id} from Trash."


@mcp.tool()
@gmail_tool
@require_auth
def gmail_delete_email(message_id: str) -> str:
    """Permanently delete an email (cannot be recovered!).

    Warning: This permanently deletes the email. Use gmail_trash_email()
    to move to trash instead (can be recovered for 30 days).

    Args:
        message_id: Message ID

    Returns:
        Confirmation
    """
    service = get_gmail_service()

    service.users().messages().delete(
        userId='me',
        id=message_id
    ).execute()

    return f"PERMANENTLY deleted message {message_id}. This cannot be undone."


@mcp.tool()
@gmail_tool
@require_auth
def gmail_batch_actions(actions: str) -> str:
    """Execute multiple email actions in one call.

    More efficient than individual calls for bulk operations.

    Args:
        actions: JSON array of actions. Each action has:
                 - action: "add_label", "remove_label", "star", "unstar",
                          "archive", "trash", "untrash", "mark_read", "mark_unread"
                 - message_id: Message ID
                 - label: Label name (for add_label/remove_label)

    Example:
        [
            {"action": "add_label", "message_id": "...", "label": "Work"},
            {"action": "star", "message_id": "..."},
            {"action": "archive", "message_id": "..."},
            {"action": "mark_read", "message_id": "..."}
        ]

    Returns:
        Summary of executed actions
    """
    service = get_gmail_service()

    try:
        action_list = json.loads(actions)
    except json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON: {e}"

    results = {
        "success": 0,
        "failed": 0,
        "details": []
    }

    for action_data in action_list:
        action = action_data.get("action", "")
        message_id = action_data.get("message_id", "")

        if not message_id:
            results["failed"] += 1
            results["details"].append({"error": "Missing message_id"})
            continue

        try:
            if action == "add_label":
                label = action_data.get("label", "")
                label_id = _get_label_id(service, label)
                if label_id:
                    service.users().messages().modify(
                        userId='me',
                        id=message_id,
                        body={'addLabelIds': [label_id]}
                    ).execute()
                    results["success"] += 1
                    results["details"].append({"message_id": message_id, "action": f"added label {label}"})
                else:
                    results["failed"] += 1
                    results["details"].append({"message_id": message_id, "error": f"Label '{label}' not found"})

            elif action == "remove_label":
                label = action_data.get("label", "")
                label_id = _get_label_id(service, label)
                if label_id:
                    service.users().messages().modify(
                        userId='me',
                        id=message_id,
                        body={'removeLabelIds': [label_id]}
                    ).execute()
                    results["success"] += 1
                    results["details"].append({"message_id": message_id, "action": f"removed label {label}"})
                else:
                    results["failed"] += 1
                    results["details"].append({"message_id": message_id, "error": f"Label '{label}' not found"})

            elif action == "star":
                service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={'addLabelIds': ['STARRED']}
                ).execute()
                results["success"] += 1
                results["details"].append({"message_id": message_id, "action": "starred"})

            elif action == "unstar":
                service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={'removeLabelIds': ['STARRED']}
                ).execute()
                results["success"] += 1
                results["details"].append({"message_id": message_id, "action": "unstarred"})

            elif action == "archive":
                service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={'removeLabelIds': ['INBOX']}
                ).execute()
                results["success"] += 1
                results["details"].append({"message_id": message_id, "action": "archived"})

            elif action == "trash":
                service.users().messages().trash(userId='me', id=message_id).execute()
                results["success"] += 1
                results["details"].append({"message_id": message_id, "action": "trashed"})

            elif action == "untrash":
                service.users().messages().untrash(userId='me', id=message_id).execute()
                results["success"] += 1
                results["details"].append({"message_id": message_id, "action": "untrashed"})

            elif action == "mark_read":
                service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={'removeLabelIds': ['UNREAD']}
                ).execute()
                results["success"] += 1
                results["details"].append({"message_id": message_id, "action": "marked read"})

            elif action == "mark_unread":
                service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={'addLabelIds': ['UNREAD']}
                ).execute()
                results["success"] += 1
                results["details"].append({"message_id": message_id, "action": "marked unread"})

            else:
                results["failed"] += 1
                results["details"].append({"message_id": message_id, "error": f"Unknown action: {action}"})

        except Exception as e:
            results["failed"] += 1
            results["details"].append({"message_id": message_id, "error": str(e)})

    return json.dumps(results, ensure_ascii=False, indent=2)


# =============================================================================
# Helper Functions
# =============================================================================

def _get_label_id(service, label: str) -> str:
    """Get label ID from name. Returns the input if it's already an ID."""
    # Check if it's already a system label or ID
    system_labels = ["INBOX", "SENT", "DRAFT", "TRASH", "SPAM", "STARRED", "UNREAD", "IMPORTANT", "CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS"]
    if label.upper() in system_labels:
        return label.upper()

    if label.startswith("Label_"):
        return label

    # Look up by name
    try:
        labels_result = service.users().labels().list(userId='me').execute()
        for lbl in labels_result.get('labels', []):
            if lbl['name'].lower() == label.lower():
                return lbl['id']
    except Exception as e:
        mcp_log(f"[Gmail] Error looking up label: {e}")

    return None


def _get_or_create_label_id(service, label: str, auto_create: bool = True) -> str:
    """Get label ID, creating it if it doesn't exist.

    Args:
        service: Gmail API service
        label: Label name
        auto_create: If True, create label if not found (default: True)

    Returns:
        Label ID or None if not found and auto_create is False
    """
    # First try to get existing label
    label_id = _get_label_id(service, label)
    if label_id:
        return label_id

    # Auto-create if enabled
    if auto_create:
        try:
            # Define colors for common labels
            label_colors = {
                "isdone": {"bg": "#16a766", "text": "#ffffff"},  # Green
                "ask": {"bg": "#4a86e8", "text": "#ffffff"},     # Blue
                "spam": {"bg": "#cc3a21", "text": "#ffffff"},    # Red
            }

            colors = label_colors.get(label.lower(), {"bg": "#cccccc", "text": "#000000"})

            label_body = {
                "name": label,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
                "color": {
                    "backgroundColor": colors["bg"],
                    "textColor": colors["text"]
                }
            }

            created = service.users().labels().create(
                userId='me',
                body=label_body
            ).execute()

            mcp_log(f"[Gmail] Auto-created label: {label} (ID: {created.get('id')})")
            return created.get('id')

        except Exception as e:
            mcp_log(f"[Gmail] Error creating label '{label}': {e}")
            return None

    return None
