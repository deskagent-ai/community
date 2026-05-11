# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
IMAP MCP - Management Module
=============================
Email management operations: move, delete, copy, batch actions.
"""

import json
from imap.base import mcp, requires_imap, get_imap_connection
from _mcp_api import mcp_log


@mcp.tool()
@requires_imap
def imap_move_email(uid: str, source_folder: str, target_folder: str) -> str:
    """Move an email from one folder to another.

    Args:
        uid: Message UID
        source_folder: Source IMAP folder name
        target_folder: Target IMAP folder name

    Returns:
        Success message or error

    Example:
        imap_move_email("123", "INBOX", "Archive")
    """
    imap = get_imap_connection()

    try:
        # Select source folder
        status, _ = imap.select(source_folder)
        if status != 'OK':
            return f"Error: Source folder '{source_folder}' not found"

        # Copy to target folder
        status, _ = imap.copy(uid, target_folder)
        if status != 'OK':
            return f"Error: Failed to copy to '{target_folder}'. Folder may not exist."

        # Mark for deletion in source
        status, _ = imap.store(uid, '+FLAGS', '\\Deleted')
        if status != 'OK':
            return f"Error: Failed to mark email for deletion"

        # Expunge to actually delete
        imap.expunge()

        mcp_log(f"[IMAP] Moved email UID {uid} from {source_folder} to {target_folder}")
        return f"Success: Email moved from '{source_folder}' to '{target_folder}'"

    except Exception as e:
        mcp_log(f"[IMAP] Move email error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_copy_email(uid: str, source_folder: str, target_folder: str) -> str:
    """Copy an email to another folder (keeps original).

    Args:
        uid: Message UID
        source_folder: Source IMAP folder name
        target_folder: Target IMAP folder name

    Returns:
        Success message or error

    Example:
        imap_copy_email("123", "INBOX", "Backup")
    """
    imap = get_imap_connection()

    try:
        # Select source folder
        status, _ = imap.select(source_folder)
        if status != 'OK':
            return f"Error: Source folder '{source_folder}' not found"

        # Copy to target folder
        status, _ = imap.copy(uid, target_folder)
        if status != 'OK':
            return f"Error: Failed to copy to '{target_folder}'. Folder may not exist."

        mcp_log(f"[IMAP] Copied email UID {uid} from {source_folder} to {target_folder}")
        return f"Success: Email copied to '{target_folder}'"

    except Exception as e:
        mcp_log(f"[IMAP] Copy email error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_delete_email(uid: str, folder: str = "INBOX", expunge: bool = True) -> str:
    """Delete an email (mark as deleted and optionally expunge).

    Args:
        uid: Message UID
        folder: IMAP folder name (default: INBOX)
        expunge: Permanently delete immediately (default: True)
                If False, email is only marked for deletion

    Returns:
        Success message or error

    Note:
        Some IMAP servers move to Trash folder instead of deleting.
        Use imap_move_email() for explicit Trash folder control.
    """
    imap = get_imap_connection()

    try:
        # Select folder
        status, _ = imap.select(folder)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Mark for deletion
        status, _ = imap.store(uid, '+FLAGS', '\\Deleted')
        if status != 'OK':
            return f"Error: Failed to mark email UID {uid} for deletion"

        if expunge:
            # Permanently delete
            imap.expunge()
            mcp_log(f"[IMAP] Deleted and expunged email UID {uid} from {folder}")
            return f"Success: Email UID {uid} permanently deleted"
        else:
            mcp_log(f"[IMAP] Marked email UID {uid} for deletion in {folder}")
            return f"Success: Email UID {uid} marked for deletion (not expunged)"

    except Exception as e:
        mcp_log(f"[IMAP] Delete email error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_create_folder(folder_name: str) -> str:
    """Create a new IMAP folder/mailbox.

    Args:
        folder_name: Name of folder to create

    Returns:
        Success message or error

    Example:
        imap_create_folder("Projects/2025")
    """
    imap = get_imap_connection()

    try:
        status, _ = imap.create(folder_name)

        if status != 'OK':
            return f"Error: Failed to create folder '{folder_name}'. May already exist."

        mcp_log(f"[IMAP] Created folder: {folder_name}")
        return f"Success: Folder '{folder_name}' created"

    except Exception as e:
        mcp_log(f"[IMAP] Create folder error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_delete_folder(folder_name: str) -> str:
    """Delete an IMAP folder/mailbox.

    Args:
        folder_name: Name of folder to delete

    Returns:
        Success message or error

    Note:
        Folder must be empty. Move or delete all emails first.
    """
    imap = get_imap_connection()

    try:
        status, _ = imap.delete(folder_name)

        if status != 'OK':
            return f"Error: Failed to delete folder '{folder_name}'. Folder may not be empty or may not exist."

        mcp_log(f"[IMAP] Deleted folder: {folder_name}")
        return f"Success: Folder '{folder_name}' deleted"

    except Exception as e:
        mcp_log(f"[IMAP] Delete folder error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_rename_folder(old_name: str, new_name: str) -> str:
    """Rename an IMAP folder/mailbox.

    Args:
        old_name: Current folder name
        new_name: New folder name

    Returns:
        Success message or error

    Example:
        imap_rename_folder("OldProjects", "Archive/Projects")
    """
    imap = get_imap_connection()

    try:
        status, _ = imap.rename(old_name, new_name)

        if status != 'OK':
            return f"Error: Failed to rename folder '{old_name}' to '{new_name}'"

        mcp_log(f"[IMAP] Renamed folder: {old_name} → {new_name}")
        return f"Success: Folder renamed from '{old_name}' to '{new_name}'"

    except Exception as e:
        mcp_log(f"[IMAP] Rename folder error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_batch_actions(actions: str) -> str:
    """Execute multiple email actions in one call.

    Supports: mark_read, mark_unread, flag, unflag, move, delete, set_keyword, remove_keyword.

    Args:
        actions: JSON array of action objects. Each object has:
                 - "action": Action type (see below)
                 - "uid": Message UID
                 - "folder": IMAP folder (default: INBOX)
                 - Additional fields per action type

                 Action types:
                 - {"action": "mark_read", "uid": "123", "folder": "INBOX"}
                 - {"action": "mark_unread", "uid": "123", "folder": "INBOX"}
                 - {"action": "flag", "uid": "123", "folder": "INBOX"}
                 - {"action": "unflag", "uid": "123", "folder": "INBOX"}
                 - {"action": "move", "uid": "123", "folder": "INBOX", "target": "Archive"}
                 - {"action": "delete", "uid": "123", "folder": "INBOX"}
                 - {"action": "set_keyword", "uid": "123", "folder": "INBOX", "keyword": "IsDone"}
                 - {"action": "remove_keyword", "uid": "123", "folder": "INBOX", "keyword": "IsDone"}

    Returns:
        JSON summary with success/error counts and details

    Example:
        imap_batch_actions('[{"action": "mark_read", "uid": "10"}, {"action": "set_keyword", "uid": "10", "keyword": "IsDone"}]')
    """
    imap = get_imap_connection()

    try:
        action_list = json.loads(actions) if isinstance(actions, str) else actions
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON: {e}"

    if not isinstance(action_list, list):
        return "Error: actions must be a JSON array"

    results = []
    success_count = 0
    error_count = 0

    # Group actions by folder for efficiency (reduce SELECT calls)
    current_folder = None

    for i, act in enumerate(action_list):
        action_type = act.get("action", "")
        uid = str(act.get("uid", ""))
        folder = act.get("folder", "INBOX")

        if not action_type or not uid:
            results.append({"index": i, "status": "error", "message": "Missing 'action' or 'uid'"})
            error_count += 1
            continue

        try:
            # Select folder if changed (writable mode for modifications)
            readonly = False
            if current_folder != folder:
                status, _ = imap.select(folder, readonly=readonly)
                if status != 'OK':
                    results.append({"index": i, "status": "error", "message": f"Folder '{folder}' not found"})
                    error_count += 1
                    continue
                current_folder = folder

            if action_type == "mark_read":
                status, _ = imap.store(uid, '+FLAGS', '\\Seen')
            elif action_type == "mark_unread":
                status, _ = imap.store(uid, '-FLAGS', '\\Seen')
            elif action_type == "flag":
                status, _ = imap.store(uid, '+FLAGS', '\\Flagged')
            elif action_type == "unflag":
                status, _ = imap.store(uid, '-FLAGS', '\\Flagged')
            elif action_type == "set_keyword":
                keyword = act.get("keyword", "")
                if not keyword:
                    results.append({"index": i, "status": "error", "message": "Missing 'keyword'"})
                    error_count += 1
                    continue
                status, _ = imap.store(uid, '+FLAGS', keyword)
            elif action_type == "remove_keyword":
                keyword = act.get("keyword", "")
                if not keyword:
                    results.append({"index": i, "status": "error", "message": "Missing 'keyword'"})
                    error_count += 1
                    continue
                status, _ = imap.store(uid, '-FLAGS', keyword)
            elif action_type == "move":
                target = act.get("target", "")
                if not target:
                    results.append({"index": i, "status": "error", "message": "Missing 'target' folder"})
                    error_count += 1
                    continue
                status, _ = imap.copy(uid, target)
                if status == 'OK':
                    imap.store(uid, '+FLAGS', '\\Deleted')
                    imap.expunge()
                    current_folder = None  # Folder state changed after expunge
            elif action_type == "delete":
                status, _ = imap.store(uid, '+FLAGS', '\\Deleted')
                if status == 'OK':
                    imap.expunge()
                    current_folder = None  # Folder state changed after expunge
            else:
                results.append({"index": i, "status": "error", "message": f"Unknown action: {action_type}"})
                error_count += 1
                continue

            if status == 'OK':
                results.append({"index": i, "status": "ok", "action": action_type, "uid": uid})
                success_count += 1
            else:
                results.append({"index": i, "status": "error", "message": f"IMAP error for {action_type}"})
                error_count += 1

        except Exception as e:
            results.append({"index": i, "status": "error", "message": str(e)})
            error_count += 1

    mcp_log(f"[IMAP] Batch actions: {success_count} ok, {error_count} errors")

    return json.dumps({
        "total": len(action_list),
        "success": success_count,
        "errors": error_count,
        "results": results
    }, indent=2, ensure_ascii=False)
