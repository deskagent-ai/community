# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Gmail MCP - Email Module
========================
Email search, read, and compose operations.
"""

# BULLETPROOF: Add embedded Python Lib path for Nuitka builds
import sys as _sys
import os as _os
_mcp_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_deskagent_dir = _os.path.dirname(_mcp_dir)
_python_lib = _os.path.join(_deskagent_dir, 'python', 'Lib')
if _os.path.isdir(_python_lib) and _python_lib not in _sys.path:
    _sys.path.insert(1, _python_lib)
# ALWAYS clear cached email module (may be cached from python312.zip)
for _mod in list(_sys.modules.keys()):
    if _mod == 'email' or _mod.startswith('email.'):
        del _sys.modules[_mod]
del _mcp_dir, _deskagent_dir, _python_lib

import json
import base64
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from gmail.base import (
    mcp, gmail_tool, require_auth,
    get_gmail_service, get_header, decode_message_body,
    MessageFormatter, format_full_email, system_log
)

# Import shared email utilities for footer rendering
try:
    import sys
    from pathlib import Path
    scripts_path = str(Path(__file__).parent.parent.parent / "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    from email_utils import render_email_footer, append_footer_to_html, strip_markdown_fences
except ImportError:
    def render_email_footer(lang="de"):
        return ""
    def append_footer_to_html(html_body, lang="de"):
        return html_body
    def strip_markdown_fences(text):
        return text


def _format_quoted_original(sender: str, date: str, body: str) -> str:
    """Format original message as quoted text for email replies.

    Args:
        sender: Original sender (e.g., "John Doe <john@example.com>")
        date: Original date string
        body: Original message body

    Returns:
        Formatted quoted text with "On [date], [sender] wrote:" header
    """
    if not body:
        return ""

    # Format the quote header
    quote_header = f"\n\nOn {date}, {sender} wrote:\n"

    # Quote each line with >
    quoted_lines = []
    for line in body.split('\n'):
        # Don't add extra > if line already starts with > (nested quotes)
        if line.startswith('>'):
            quoted_lines.append(f">{line}")
        else:
            quoted_lines.append(f"> {line}")

    return quote_header + '\n'.join(quoted_lines)


@mcp.tool()
@gmail_tool
@require_auth
def gmail_search_emails(
    query: str,
    limit: int = 50,
    include_spam_trash: bool = False
) -> str:
    """Search Gmail emails using Gmail query syntax.

    Args:
        query: Gmail search query. Examples:
               - "from:sender@example.com" - From specific sender
               - "to:recipient@example.com" - To specific recipient
               - "subject:keyword" - Subject contains keyword
               - "has:attachment" - Has attachments
               - "is:unread" - Unread messages
               - "is:starred" - Starred messages
               - "after:2025/01/01" - After date
               - "before:2025/12/31" - Before date
               - "label:INBOX" - In specific label
               - "invoice payment" - Contains words
               - Combine: "from:example.com subject:invoice after:2025/01/01"
        limit: Maximum results (default: 50)
        include_spam_trash: Include spam and trash (default: False)

    Returns:
        List of matching emails with ID, subject, from, date
    """
    service = get_gmail_service()

    results = service.users().messages().list(
        userId='me',
        q=query,
        maxResults=min(limit, 500),
        includeSpamTrash=include_spam_trash
    ).execute()

    messages = results.get('messages', [])

    if not messages:
        return f"No emails found matching: {query}"

    # Get message details
    output_lines = [f"Found {len(messages)} email(s) matching: {query}\n"]

    for msg_ref in messages:
        msg = service.users().messages().get(
            userId='me',
            id=msg_ref['id'],
            format='metadata',
            metadataHeaders=['Subject', 'From', 'Date']
        ).execute()

        output_lines.append(MessageFormatter.format_email_list_item(msg))

    return "\n".join(output_lines)


@mcp.tool()
@gmail_tool
@require_auth
def gmail_get_email(message_id: str) -> str:
    """Get full content of a Gmail message.

    Args:
        message_id: Message ID (from search results)

    Returns:
        Full email content with headers and body
    """
    service = get_gmail_service()

    msg = service.users().messages().get(
        userId='me',
        id=message_id,
        format='full'
    ).execute()

    return format_full_email(msg)


@mcp.tool()
@gmail_tool
@require_auth
def gmail_get_recent_emails(
    days: int = 7,
    limit: int = 50,
    label: str = "INBOX",
    exclude_labels: str = ""
) -> str:
    """Get recent emails from the last N days.

    Args:
        days: Number of days to look back (default: 7)
        limit: Maximum results (default: 50)
        label: Label to filter by (default: INBOX)
        exclude_labels: Comma-separated labels to exclude (e.g., "IsDone,Spam")

    Returns:
        JSON array of recent emails with ID, subject, from, date, labels
    """
    service = get_gmail_service()

    # Build query with date filter
    after_date = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
    query = f"after:{after_date}"
    if label:
        query += f" label:{label}"

    # Add exclusions
    if exclude_labels:
        for excl in exclude_labels.split(","):
            excl = excl.strip()
            if excl:
                query += f" -label:{excl}"

    results = service.users().messages().list(
        userId='me',
        q=query,
        maxResults=min(limit, 500)
    ).execute()

    messages = results.get('messages', [])

    if not messages:
        return json.dumps([], indent=2)

    # Get full metadata for each message
    email_list = []
    for msg_ref in messages:
        msg = service.users().messages().get(
            userId='me',
            id=msg_ref['id'],
            format='metadata',
            metadataHeaders=['Subject', 'From', 'To', 'Date']
        ).execute()

        headers = msg.get("payload", {}).get("headers", [])

        email_list.append({
            "id": msg.get("id"),
            "thread_id": msg.get("threadId"),
            "subject": get_header(headers, "Subject") or "(No subject)",
            "from": get_header(headers, "From") or "Unknown",
            "to": get_header(headers, "To") or "",
            "date": get_header(headers, "Date") or "",
            "labels": msg.get("labelIds", []),
            "is_unread": "UNREAD" in msg.get("labelIds", []),
            "is_starred": "STARRED" in msg.get("labelIds", []),
            "snippet": msg.get("snippet", "")[:100]
        })

    return json.dumps(email_list, ensure_ascii=False, indent=2)


@mcp.tool()
@gmail_tool
@require_auth
def gmail_get_emails_by_label(
    label: str,
    limit: int = 50
) -> str:
    """Get emails with a specific label.

    Args:
        label: Label name (e.g., "INBOX", "SENT", "Work", "Personal")
               Use gmail_list_labels() to see available labels.
        limit: Maximum results (default: 50)

    Returns:
        JSON array of emails with the specified label
    """
    service = get_gmail_service()

    # Get label ID if it's a custom label
    label_id = label
    if not label.startswith("Label_") and label not in ["INBOX", "SENT", "DRAFT", "TRASH", "SPAM", "STARRED", "UNREAD", "IMPORTANT"]:
        # Try to find label by name
        labels_result = service.users().labels().list(userId='me').execute()
        for lbl in labels_result.get('labels', []):
            if lbl['name'].lower() == label.lower():
                label_id = lbl['id']
                break

    results = service.users().messages().list(
        userId='me',
        labelIds=[label_id],
        maxResults=min(limit, 500)
    ).execute()

    messages = results.get('messages', [])

    if not messages:
        return json.dumps([], indent=2)

    # Get full metadata
    email_list = []
    for msg_ref in messages:
        msg = service.users().messages().get(
            userId='me',
            id=msg_ref['id'],
            format='metadata',
            metadataHeaders=['Subject', 'From', 'Date']
        ).execute()

        headers = msg.get("payload", {}).get("headers", [])

        email_list.append({
            "id": msg.get("id"),
            "thread_id": msg.get("threadId"),
            "subject": get_header(headers, "Subject") or "(No subject)",
            "from": get_header(headers, "From") or "Unknown",
            "date": get_header(headers, "Date") or "",
            "labels": msg.get("labelIds", []),
            "is_unread": "UNREAD" in msg.get("labelIds", [])
        })

    return json.dumps(email_list, ensure_ascii=False, indent=2)


@mcp.tool()
@gmail_tool
@require_auth
def gmail_get_unread_emails(limit: int = 20) -> str:
    """Get unread emails from inbox.

    Args:
        limit: Maximum results (default: 20)

    Returns:
        List of unread emails
    """
    service = get_gmail_service()

    results = service.users().messages().list(
        userId='me',
        q='is:unread',
        labelIds=['INBOX'],
        maxResults=min(limit, 100)
    ).execute()

    messages = results.get('messages', [])

    if not messages:
        return "No unread emails."

    output_lines = [f"Found {len(messages)} unread email(s):\n"]

    for msg_ref in messages:
        msg = service.users().messages().get(
            userId='me',
            id=msg_ref['id'],
            format='metadata',
            metadataHeaders=['Subject', 'From', 'Date']
        ).execute()

        output_lines.append(MessageFormatter.format_email_list_item(msg))

    return "\n".join(output_lines)


@mcp.tool()
@gmail_tool
@require_auth
def gmail_get_starred_emails(limit: int = 20) -> str:
    """Get starred emails (similar to flagged in Outlook).

    Args:
        limit: Maximum results (default: 20)

    Returns:
        List of starred emails
    """
    service = get_gmail_service()

    results = service.users().messages().list(
        userId='me',
        labelIds=['STARRED'],
        maxResults=min(limit, 100)
    ).execute()

    messages = results.get('messages', [])

    if not messages:
        return "No starred emails."

    output_lines = [f"Found {len(messages)} starred email(s):\n"]

    for msg_ref in messages:
        msg = service.users().messages().get(
            userId='me',
            id=msg_ref['id'],
            format='metadata',
            metadataHeaders=['Subject', 'From', 'Date']
        ).execute()

        output_lines.append(MessageFormatter.format_email_list_item(msg))

    return "\n".join(output_lines)


@mcp.tool()
@gmail_tool
@require_auth
def gmail_get_thread(thread_id: str) -> str:
    """Get all messages in an email thread (conversation).

    Args:
        thread_id: Thread ID (from email details)

    Returns:
        All messages in the thread, oldest first
    """
    service = get_gmail_service()

    thread = service.users().threads().get(
        userId='me',
        id=thread_id,
        format='full'
    ).execute()

    messages = thread.get('messages', [])

    if not messages:
        return "No messages in thread."

    output_lines = [f"Thread with {len(messages)} message(s):\n"]
    output_lines.append("=" * 60)

    for i, msg in enumerate(messages, 1):
        headers = msg.get("payload", {}).get("headers", [])
        subject = get_header(headers, "Subject") or "(No subject)"
        from_addr = get_header(headers, "From") or "Unknown"
        date_str = get_header(headers, "Date") or ""

        body = decode_message_body(msg.get("payload", {}))

        output_lines.append(f"\n--- Message {i} ---")
        output_lines.append(f"From: {from_addr}")
        output_lines.append(f"Date: {date_str}")
        output_lines.append(f"Subject: {subject}")
        output_lines.append(f"\n{body}")
        output_lines.append("\n" + "-" * 40)

    return "\n".join(output_lines)


@mcp.tool()
@gmail_tool
@require_auth
def gmail_create_draft(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    html: bool = False
) -> str:
    """Create an email draft (does NOT send).

    Args:
        to: Recipient email address(es), comma-separated
        subject: Email subject
        body: Email body (plain text or HTML if html=True)
        cc: CC recipients, comma-separated (optional)
        html: Body is HTML (default: False = plain text)

    Returns:
        Draft ID and confirmation
    """
    service = get_gmail_service()

    # Create message
    if html:
        message = MIMEMultipart('alternative')
        message.attach(MIMEText(body, 'html'))
    else:
        message = MIMEText(body)

    message['to'] = to
    message['subject'] = subject
    if cc:
        message['cc'] = cc

    # Encode message
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

    # Create draft
    draft = service.users().drafts().create(
        userId='me',
        body={'message': {'raw': raw}}
    ).execute()

    return f"""Draft created successfully!

Draft ID: {draft['id']}
To: {to}
Subject: {subject}

Use gmail_send_draft('{draft['id']}') to send this email."""


@mcp.tool()
@gmail_tool
@require_auth
def gmail_create_reply_draft(
    message_id: str,
    body: str,
    reply_all: bool = True,
    html: bool = False,
    from_email: str = ""
) -> str:
    """Create a reply draft to an existing email (does NOT send).

    The reply automatically includes the quoted original message below your reply,
    formatted as "On [date], [sender] wrote:" followed by the original text with > prefixes.

    Args:
        message_id: Message ID to reply to
        body: Reply body text (plain text, Markdown, or HTML if html=True)
        reply_all: Reply to all recipients (default: True)
        html: Body contains HTML (default: False). If False but body contains
              Markdown (**bold**, [links](url)), it will be auto-converted to HTML.
        from_email: Send from this email address (must be a configured alias in Gmail)

    Returns:
        Draft ID and confirmation
    """
    service = get_gmail_service()

    # Get original message for headers AND body (for quoting)
    original = service.users().messages().get(
        userId='me',
        id=message_id,
        format='full'
    ).execute()

    payload = original.get("payload", {})
    headers = payload.get("headers", [])
    thread_id = original.get("threadId")

    # Extract original body for quoting
    original_body = decode_message_body(payload)
    original_date = get_header(headers, "Date")

    # Build recipient list
    from_addr = get_header(headers, "From")
    to_addr = get_header(headers, "To")
    cc_addr = get_header(headers, "Cc")

    # Primary recipient is original sender
    recipients = from_addr

    if reply_all:
        # Add other recipients (excluding self)
        if to_addr:
            recipients += f", {to_addr}"
        cc = cc_addr if cc_addr else ""
    else:
        cc = ""

    # Build subject
    original_subject = get_header(headers, "Subject") or ""
    if not original_subject.lower().startswith("re:"):
        subject = f"Re: {original_subject}"
    else:
        subject = original_subject

    # Build References header for threading
    message_id_header = get_header(headers, "Message-ID")
    references = get_header(headers, "References") or ""
    if message_id_header:
        if references:
            references += f" {message_id_header}"
        else:
            references = message_id_header

    # Append quoted original message to reply body
    quoted_original = _format_quoted_original(from_addr, original_date, original_body)
    full_body = body + quoted_original

    # Check if body contains Markdown and auto-convert
    html_body = None
    if html:
        # Convert quoted original to HTML (newlines to <br>)
        html_quoted = f"<br><br><div style='color:#666'>{quoted_original.replace(chr(10), '<br>')}</div>"
        html_body = body + html_quoted
    elif _contains_markdown(body):
        # Convert reply to HTML but keep quoted text as plain
        html_body = _markdown_to_html(body) + f"<br><br><div style='color:#666'>{quoted_original.replace(chr(10), '<br>')}</div>"

    # Create message
    if html_body:
        message = MIMEMultipart('alternative')
        # Add plain text version (strip markdown from reply, keep quoted)
        plain_text = _strip_markdown(body) + quoted_original
        message.attach(MIMEText(plain_text, 'plain'))
        message.attach(MIMEText(html_body, 'html'))
    else:
        message = MIMEText(full_body)

    message['to'] = recipients
    message['subject'] = subject
    if from_email:
        message['from'] = from_email
    if cc:
        message['cc'] = cc
    if references:
        message['References'] = references
        message['In-Reply-To'] = message_id_header

    # Encode
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

    # Create draft in same thread
    draft = service.users().drafts().create(
        userId='me',
        body={
            'message': {
                'raw': raw,
                'threadId': thread_id
            }
        }
    ).execute()

    from_info = f"\nFrom: {from_email}" if from_email else ""
    return f"""Reply draft created successfully!

Draft ID: {draft['id']}
To: {recipients}{from_info}
Subject: {subject}
Thread ID: {thread_id}

Use gmail_send_draft('{draft['id']}') to send this reply."""


@mcp.tool()
@gmail_tool
@require_auth
def gmail_send_draft(draft_id: str) -> str:
    """Send an existing draft.

    Args:
        draft_id: Draft ID from gmail_create_draft or gmail_create_reply_draft

    Returns:
        Confirmation with sent message ID
    """
    service = get_gmail_service()

    sent = service.users().drafts().send(
        userId='me',
        body={'id': draft_id}
    ).execute()

    return f"""Email sent successfully!

Message ID: {sent['id']}
Thread ID: {sent['threadId']}
Labels: {', '.join(sent.get('labelIds', []))}"""


@mcp.tool()
@gmail_tool
@require_auth
def gmail_send_reply(
    message_id: str,
    body: str,
    reply_all: bool = True,
    html: bool = False,
    from_email: str = ""
) -> str:
    """Create and immediately send a reply to an email (draft + send in one step).

    Combines gmail_create_reply_draft + gmail_send_draft for simpler workflows.
    The reply automatically includes the quoted original message.
    Automatically cleans up markdown code blocks from LLM output.

    Args:
        message_id: Message ID to reply to
        body: Reply body text (plain text, Markdown, or HTML if html=True)
        reply_all: Reply to all recipients (default: True)
        html: Body contains HTML (default: False)
        from_email: Send from this email address (must be a configured alias)

    Returns:
        Confirmation with sent message ID
    """
    body = strip_markdown_fences(body)
    service = get_gmail_service()

    # Get original message for headers AND body (for quoting)
    original = service.users().messages().get(
        userId='me',
        id=message_id,
        format='full'
    ).execute()

    payload = original.get("payload", {})
    headers = payload.get("headers", [])
    thread_id = original.get("threadId")

    # Extract original body for quoting
    original_body = decode_message_body(payload)
    original_date = get_header(headers, "Date")

    # Build recipient list
    from_addr = get_header(headers, "From")
    to_addr = get_header(headers, "To")
    cc_addr = get_header(headers, "Cc")

    recipients = from_addr
    if reply_all:
        if to_addr:
            recipients += f", {to_addr}"
        cc = cc_addr if cc_addr else ""
    else:
        cc = ""

    # Build subject
    original_subject = get_header(headers, "Subject") or ""
    if not original_subject.lower().startswith("re:"):
        subject = f"Re: {original_subject}"
    else:
        subject = original_subject

    # Build References header for threading
    message_id_header = get_header(headers, "Message-ID")
    references = get_header(headers, "References") or ""
    if message_id_header:
        if references:
            references += f" {message_id_header}"
        else:
            references = message_id_header

    # Append quoted original message
    quoted_original = _format_quoted_original(from_addr, original_date, original_body)

    full_body = body + quoted_original

    # Handle HTML/Markdown
    html_body = None
    html_quoted = f"<br><br><div style='color:#666'>{quoted_original.replace(chr(10), '<br>')}</div>"
    if html:
        html_body = body + html_quoted
    elif _contains_markdown(body):
        html_body = _markdown_to_html(body) + html_quoted

    # Create message
    if html_body:
        message = MIMEMultipart('alternative')
        plain_text = _strip_markdown(body) + quoted_original
        message.attach(MIMEText(plain_text, 'plain'))
        message.attach(MIMEText(html_body, 'html'))
    else:
        message = MIMEText(full_body)

    message['to'] = recipients
    message['subject'] = subject
    if from_email:
        message['from'] = from_email
    if cc:
        message['cc'] = cc
    if references:
        message['References'] = references
        message['In-Reply-To'] = message_id_header

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

    # Create draft and send immediately
    draft = service.users().drafts().create(
        userId='me',
        body={'message': {'raw': raw, 'threadId': thread_id}}
    ).execute()

    sent = service.users().drafts().send(
        userId='me',
        body={'id': draft['id']}
    ).execute()

    return f"""Reply sent successfully!

Message ID: {sent['id']}
To: {recipients}
Subject: {subject}
Thread ID: {sent['threadId']}"""


@mcp.tool()
@gmail_tool
@require_auth
def gmail_mark_read(
    message_id: str,
    is_read: bool = True
) -> str:
    """Mark an email as read or unread.

    Args:
        message_id: Message ID
        is_read: True to mark as read, False for unread (default: True)

    Returns:
        Confirmation
    """
    service = get_gmail_service()

    if is_read:
        # Remove UNREAD label
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()
        return f"Marked message {message_id} as read."
    else:
        # Add UNREAD label
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'addLabelIds': ['UNREAD']}
        ).execute()
        return f"Marked message {message_id} as unread."


@mcp.tool()
@gmail_tool
@require_auth
def gmail_get_profile() -> str:
    """Get Gmail profile information (email address, total messages, etc.).

    Returns:
        Profile information
    """
    service = get_gmail_service()

    profile = service.users().getProfile(userId='me').execute()

    return f"""Gmail Profile:

Email: {profile.get('emailAddress', 'Unknown')}
Total messages: {profile.get('messagesTotal', 0):,}
Total threads: {profile.get('threadsTotal', 0):,}
History ID: {profile.get('historyId', 'N/A')}"""


# ============================================================================
# Markdown Helper Functions
# ============================================================================

def _contains_markdown(text: str) -> bool:
    """Check if text contains Markdown formatting that should be converted to HTML."""
    import re
    # Check for common Markdown patterns
    patterns = [
        r'\*\*.+?\*\*',          # **bold**
        r'\*.+?\*',              # *italic* (but not ** which is bold)
        r'`.+?`',                # `code`
        r'\[.+?\]\(.+?\)',       # [link](url)
        r'^\s*[-*+]\s+',         # - list item
        r'^\s*\d+\.\s+',         # 1. numbered list
        r'^#{1,6}\s+',           # # headers
    ]
    for pattern in patterns:
        if re.search(pattern, text, re.MULTILINE):
            return True
    return False


def _markdown_to_html(text: str) -> str:
    """Convert Markdown text to HTML with compact styling."""
    import re

    # Escape HTML entities first
    html = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # Convert inline Markdown to HTML
    # Bold: **text** -> <strong>text</strong>
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)

    # Italic: *text* -> <em>text</em> (but not ** which is bold)
    html = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', html)

    # Code: `text` -> <code>text</code>
    html = re.sub(r'`(.+?)`', r'<code style="background:#f0f0f0;padding:1px 4px;border-radius:3px;">\1</code>', html)

    # Links: [text](url) -> <a href="url">text</a>
    html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html)

    # Process lines for lists
    lines = html.split('\n')
    in_ol = False
    in_ul = False
    result = []

    for line in lines:
        stripped = line.strip()

        # Check for numbered list
        match = re.match(r'^\d+\.\s+(.+)$', stripped)
        if match:
            content = match.group(1)
            if in_ul:
                result.append('</ul>')
                in_ul = False
            if not in_ol:
                result.append('<ol style="margin:0.5em 0;padding-left:1.5em;">')
                in_ol = True
            result.append(f'<li style="margin:0.2em 0;">{content}</li>')
            continue

        # Check for bullet list
        match = re.match(r'^[-*+]\s+(.+)$', stripped)
        if match:
            content = match.group(1)
            if in_ol:
                result.append('</ol>')
                in_ol = False
            if not in_ul:
                result.append('<ul style="margin:0.5em 0;padding-left:1.5em;">')
                in_ul = True
            result.append(f'<li style="margin:0.2em 0;">{content}</li>')
            continue

        # Not a list item - close any open lists
        if in_ol:
            result.append('</ol>')
            in_ol = False
        if in_ul:
            result.append('</ul>')
            in_ul = False

        # Add non-list line
        if stripped:
            result.append(line)
        else:
            result.append('<br>')  # Empty line = paragraph break

    # Close any remaining lists
    if in_ol:
        result.append('</ol>')
    if in_ul:
        result.append('</ul>')

    # Join without extra line breaks between list items
    html = ''.join(result)

    # Clean up multiple <br> tags
    html = re.sub(r'(<br>)+', '<br><br>', html)

    # Wrap in a div with reasonable styling
    html = f'<div style="font-family:Arial,sans-serif;line-height:1.4;">{html}</div>'

    return html


def _strip_markdown(text: str) -> str:
    """Remove Markdown formatting for plain text version."""
    import re

    # Remove bold markers
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)

    # Remove italic markers
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'\1', text)

    # Remove code markers
    text = re.sub(r'`(.+?)`', r'\1', text)

    # Convert links to text (url)
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'\1 (\2)', text)

    return text
