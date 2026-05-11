# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
IMAP MCP - Flags Module
========================
Standard and custom IMAP flag operations.

IMAP supports both standard flags (\\Seen, \\Flagged, etc.) and
custom flags (keywords) for workflow automation.
"""

import json
from imap.base import mcp, requires_imap, get_imap_connection
from _mcp_api import mcp_log


@mcp.tool()
@requires_imap
def imap_get_flags(uid: str, folder: str = "INBOX") -> str:
    """Get all flags (standard and custom) for an email.

    Args:
        uid: Message UID
        folder: IMAP folder name (default: INBOX)

    Returns:
        JSON object with standard and custom flags
    """
    imap = get_imap_connection()

    try:
        # Select folder (readonly)
        status, _ = imap.select(folder, readonly=True)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Fetch flags
        status, msg_data = imap.fetch(uid, '(FLAGS)')
        if status != 'OK':
            return f"Error: Failed to fetch flags for UID {uid}"

        # Parse flags from response
        # Format: b'1 (FLAGS (\\Seen \\Flagged MyCustomFlag))'
        flags_str = msg_data[0].decode()

        # Extract flags from parentheses
        start = flags_str.find('(FLAGS (')
        if start == -1:
            return json.dumps({"standard": [], "custom": []}, indent=2)

        start += len('(FLAGS (')
        end = flags_str.find('))', start)
        flags_section = flags_str[start:end]

        # Parse flags
        all_flags = flags_section.split()

        # Separate standard and custom flags
        standard_flags = []
        custom_flags = []

        for flag in all_flags:
            if flag.startswith('\\'):
                # Standard flag (e.g., \\Seen, \\Flagged)
                standard_flags.append(flag)
            else:
                # Custom flag (keyword)
                custom_flags.append(flag)

        result = {
            "uid": uid,
            "folder": folder,
            "standard_flags": standard_flags,
            "custom_flags": custom_flags
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        mcp_log(f"[IMAP] Get flags error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_set_flag(uid: str, flag: str, folder: str = "INBOX") -> str:
    """Set a standard IMAP flag on an email.

    Args:
        uid: Message UID
        flag: Standard flag to set. Options:
              - "\\Seen" - Mark as read
              - "\\Flagged" - Flag/star message
              - "\\Answered" - Mark as answered
              - "\\Draft" - Mark as draft
              - "\\Deleted" - Mark for deletion (expunge to delete)
        folder: IMAP folder name (default: INBOX)

    Returns:
        Success message or error
    """
    imap = get_imap_connection()

    try:
        # Select folder (writable)
        status, _ = imap.select(folder)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Validate standard flag
        valid_flags = ['\\Seen', '\\Flagged', '\\Answered', '\\Draft', '\\Deleted']
        if flag not in valid_flags:
            return f"Error: Invalid flag '{flag}'. Valid flags: {', '.join(valid_flags)}"

        # Set flag
        status, _ = imap.store(uid, '+FLAGS', flag)
        if status != 'OK':
            return f"Error: Failed to set flag '{flag}' on UID {uid}"

        mcp_log(f"[IMAP] Set flag {flag} on UID {uid} in {folder}")
        return f"Success: Flag '{flag}' set on email UID {uid}"

    except Exception as e:
        mcp_log(f"[IMAP] Set flag error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_remove_flag(uid: str, flag: str, folder: str = "INBOX") -> str:
    """Remove a standard IMAP flag from an email.

    Args:
        uid: Message UID
        flag: Standard flag to remove (e.g., "\\Seen", "\\Flagged")
        folder: IMAP folder name (default: INBOX)

    Returns:
        Success message or error
    """
    imap = get_imap_connection()

    try:
        # Select folder (writable)
        status, _ = imap.select(folder)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Remove flag
        status, _ = imap.store(uid, '-FLAGS', flag)
        if status != 'OK':
            return f"Error: Failed to remove flag '{flag}' from UID {uid}"

        mcp_log(f"[IMAP] Removed flag {flag} from UID {uid} in {folder}")
        return f"Success: Flag '{flag}' removed from email UID {uid}"

    except Exception as e:
        mcp_log(f"[IMAP] Remove flag error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_set_custom_flag(uid: str, keyword: str, folder: str = "INBOX") -> str:
    """Set a custom IMAP flag (keyword) on an email.

    Custom flags enable workflow automation (e.g., "NeedsReview", "Processed", "Urgent").

    Args:
        uid: Message UID
        keyword: Custom flag name (no backslash, alphanumeric only)
                Examples: "NeedsReview", "Processed", "FollowUp2025"
        folder: IMAP folder name (default: INBOX)

    Returns:
        Success message or error

    Example:
        imap_set_custom_flag("123", "NeedsReview", "INBOX")
        # Later search: imap_search_emails("INBOX", "KEYWORD NeedsReview")
    """
    imap = get_imap_connection()

    try:
        # Validate keyword (no backslash, alphanumeric)
        if not keyword.replace('_', '').replace('-', '').isalnum():
            return f"Error: Invalid keyword '{keyword}'. Use alphanumeric characters only (A-Z, 0-9, -, _)"

        if keyword.startswith('\\'):
            return "Error: Custom flags must not start with backslash. Use alphanumeric names."

        # Select folder (writable)
        status, _ = imap.select(folder)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Set custom flag (keyword)
        status, response = imap.store(uid, '+FLAGS', keyword)
        if status != 'OK':
            # Check if server supports keywords
            error_msg = str(response)
            if 'PERMANENTFLAGS' in error_msg or 'not supported' in error_msg.lower():
                return f"Error: Server does not support custom flags (keywords). Check PERMANENTFLAGS capability."
            return f"Error: Failed to set custom flag '{keyword}' on UID {uid}"

        mcp_log(f"[IMAP] Set custom flag '{keyword}' on UID {uid} in {folder}")
        return f"Success: Custom flag '{keyword}' set on email UID {uid}"

    except Exception as e:
        mcp_log(f"[IMAP] Set custom flag error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_remove_custom_flag(uid: str, keyword: str, folder: str = "INBOX") -> str:
    """Remove a custom IMAP flag (keyword) from an email.

    Args:
        uid: Message UID
        keyword: Custom flag name to remove
        folder: IMAP folder name (default: INBOX)

    Returns:
        Success message or error
    """
    imap = get_imap_connection()

    try:
        # Select folder (writable)
        status, _ = imap.select(folder)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Remove custom flag
        status, _ = imap.store(uid, '-FLAGS', keyword)
        if status != 'OK':
            return f"Error: Failed to remove custom flag '{keyword}' from UID {uid}"

        mcp_log(f"[IMAP] Removed custom flag '{keyword}' from UID {uid} in {folder}")
        return f"Success: Custom flag '{keyword}' removed from email UID {uid}"

    except Exception as e:
        mcp_log(f"[IMAP] Remove custom flag error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_search_by_custom_flag(keyword: str, folder: str = "INBOX", limit: int = 50) -> str:
    """Search emails by custom IMAP flag (keyword).

    Args:
        keyword: Custom flag name to search for
        folder: IMAP folder name (default: INBOX)
        limit: Maximum results (default: 50)

    Returns:
        JSON array of emails with the custom flag

    Example:
        # First set flag: imap_set_custom_flag("123", "Urgent")
        # Then search: imap_search_by_custom_flag("Urgent")
    """
    imap = get_imap_connection()

    try:
        # Select folder
        status, _ = imap.select(folder, readonly=True)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Search by keyword
        status, message_ids = imap.search(None, f'KEYWORD {keyword}')
        if status != 'OK':
            return f"Error: Search failed for custom flag '{keyword}'"

        # Get UIDs
        uids = message_ids[0].split()
        if not uids:
            return f"No emails found with custom flag: {keyword}"

        # Reverse to get newest first, apply limit
        uids = uids[::-1][:limit]

        # Import parse helper
        from imap.base import parse_email_message

        # Fetch email headers
        emails = []
        for uid in uids:
            try:
                status, msg_data = imap.fetch(uid, '(RFC822.HEADER)')
                if status == 'OK':
                    parsed = parse_email_message(msg_data[0][1])
                    if parsed:
                        emails.append({
                            "uid": uid.decode(),
                            "subject": parsed["subject"],
                            "from": parsed["from"],
                            "date": parsed["date"],
                            "custom_flag": keyword
                        })
            except Exception as e:
                mcp_log(f"[IMAP] Failed to fetch UID {uid}: {e}")
                continue

        if not emails:
            return "No emails could be retrieved"

        return json.dumps(emails, indent=2, ensure_ascii=False)

    except Exception as e:
        mcp_log(f"[IMAP] Search by custom flag error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_list_custom_flags(folder: str = "INBOX") -> str:
    """List all custom flags (keywords) used in a folder.

    Scans all emails in folder and collects unique custom flags.
    Note: This can be slow on large folders.

    Args:
        folder: IMAP folder name (default: INBOX)

    Returns:
        JSON array of unique custom flags found in folder
    """
    imap = get_imap_connection()

    try:
        # Select folder
        status, _ = imap.select(folder, readonly=True)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Get all message UIDs (limit to 1000 for performance)
        status, message_ids = imap.search(None, 'ALL')
        if status != 'OK':
            return "Error: Failed to search folder"

        uids = message_ids[0].split()
        if not uids:
            return json.dumps([], indent=2)

        # Sample UIDs (for large folders, only check recent messages)
        if len(uids) > 1000:
            uids = uids[-1000:]  # Last 1000 messages

        # Collect all custom flags
        custom_flags = set()

        for uid in uids:
            try:
                status, msg_data = imap.fetch(uid, '(FLAGS)')
                if status == 'OK':
                    flags_str = msg_data[0].decode()

                    # Extract flags
                    start = flags_str.find('(FLAGS (')
                    if start != -1:
                        start += len('(FLAGS (')
                        end = flags_str.find('))', start)
                        flags_section = flags_str[start:end]

                        # Parse flags
                        all_flags = flags_section.split()

                        # Collect custom flags (without backslash)
                        for flag in all_flags:
                            if not flag.startswith('\\'):
                                custom_flags.add(flag)

            except Exception as e:
                mcp_log(f"[IMAP] Failed to fetch flags for UID {uid}: {e}")
                continue

        result = sorted(list(custom_flags))
        return json.dumps(result, indent=2)

    except Exception as e:
        mcp_log(f"[IMAP] List custom flags error: {e}")
        return f"Error: {str(e)}"
