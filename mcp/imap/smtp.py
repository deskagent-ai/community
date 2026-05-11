# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
IMAP MCP - SMTP Module
=======================
Send emails via SMTP with support for attachments, HTML, and CC/BCC.
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

import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from imap.base import mcp, requires_imap, get_smtp_connection, get_imap_connection, get_config, parse_email_message
from _mcp_api import mcp_log


def _save_to_sent_folder(msg):
    """Save a sent message to the Sent folder via IMAP.

    Reads sent_folder from config, defaults to "Sent".
    Common folder names: "Sent", "Sent Items", "Gesendet", "INBOX.Sent"

    Args:
        msg: The MIMEMultipart message object
    """
    config = get_config()
    sent_folder = config.get("sent_folder", "Sent")

    # Skip if explicitly disabled
    if not sent_folder:
        return

    try:
        imap = get_imap_connection()
        # APPEND message to Sent folder with \\Seen flag
        import datetime
        import imaplib
        # Use timezone-aware datetime (required by imaplib)
        date_time = imaplib.Time2Internaldate(datetime.datetime.now(datetime.timezone.utc))
        result = imap.append(sent_folder, "\\Seen", date_time, msg.as_bytes())
        if result[0] == 'OK':
            mcp_log(f"[SMTP] Saved copy to {sent_folder} folder")
        else:
            mcp_log(f"[SMTP] Failed to save to {sent_folder}: {result}")
    except Exception as e:
        # Don't fail the send if we can't save to Sent
        mcp_log(f"[SMTP] Warning: Could not save to {sent_folder} folder: {e}")

# Import shared email utilities
try:
    import sys
    from pathlib import Path
    scripts_path = str(Path(__file__).parent.parent.parent / "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    from email_utils import append_footer_to_html, strip_markdown_fences
except ImportError:
    def append_footer_to_html(html_body, lang="de"):
        return html_body
    def strip_markdown_fences(text):
        return text


def _clean_email_body(body: str, html: bool = False) -> str:
    """Clean email body before sending.

    - Strips markdown code fences (```html...```) from agent output
    - Only applied to HTML emails (plain text kept as-is)

    Args:
        body: Email body text
        html: Whether this is an HTML email

    Returns:
        Cleaned body text
    """
    if html and body:
        return strip_markdown_fences(body)
    return body


@mcp.tool()
@requires_imap
def smtp_send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    html: bool = False,
    reply_to: str = ""
) -> str:
    """Send an email via SMTP.

    Args:
        to: Recipient email address(es), comma-separated
        subject: Email subject
        body: Email body (plain text or HTML)
        cc: CC recipients, comma-separated (optional)
        bcc: BCC recipients, comma-separated (optional)
        html: Send as HTML email (default: False, plain text)
        reply_to: Reply-To address (optional)

    Returns:
        Success message or error

    Example:
        smtp_send_email(
            to="customer@example.com",
            subject="Re: Your inquiry",
            body="Thank you for your message...",
            cc="team@company.com"
        )
    """
    config = get_config()
    from_addr = config.get("smtp_user")

    if not from_addr:
        return "Error: SMTP user not configured"

    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = from_addr
        msg['To'] = to
        msg['Subject'] = subject

        if cc:
            msg['Cc'] = cc
        if reply_to:
            msg['Reply-To'] = reply_to

        # Attach body (clean markdown fences for HTML)
        clean_body = _clean_email_body(body, html)
        mime_type = 'html' if html else 'plain'
        msg.attach(MIMEText(clean_body, mime_type, 'utf-8'))

        # Get recipients list
        recipients = [addr.strip() for addr in to.split(',')]
        if cc:
            recipients.extend([addr.strip() for addr in cc.split(',')])
        if bcc:
            recipients.extend([addr.strip() for addr in bcc.split(',')])

        # Send email
        smtp = get_smtp_connection()
        try:
            smtp.send_message(msg, from_addr=from_addr, to_addrs=recipients)
            mcp_log(f"[SMTP] Sent email to {to}: {subject}")
        finally:
            smtp.quit()

        # Save to Sent folder via IMAP
        _save_to_sent_folder(msg)

        return f"Success: Email sent to {to}"

    except Exception as e:
        mcp_log(f"[SMTP] Send email error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def smtp_send_with_attachment(
    to: str,
    subject: str,
    body: str,
    attachment_path: str,
    cc: str = "",
    bcc: str = "",
    html: bool = False,
    reply_to: str = ""
) -> str:
    """Send an email with file attachment via SMTP.

    Args:
        to: Recipient email address(es), comma-separated
        subject: Email subject
        body: Email body (plain text or HTML)
        attachment_path: Full path to attachment file
        cc: CC recipients, comma-separated (optional)
        bcc: BCC recipients, comma-separated (optional)
        html: Send as HTML email (default: False)
        reply_to: Reply-To address (optional)

    Returns:
        Success message or error

    Example:
        smtp_send_with_attachment(
            to="customer@example.com",
            subject="Your invoice",
            body="Please find attached...",
            attachment_path="/path/to/invoice.pdf"
        )
    """
    config = get_config()
    from_addr = config.get("smtp_user")

    if not from_addr:
        return "Error: SMTP user not configured"

    # Check if attachment exists
    if not os.path.exists(attachment_path):
        return f"Error: Attachment file not found: {attachment_path}"

    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = from_addr
        msg['To'] = to
        msg['Subject'] = subject

        if cc:
            msg['Cc'] = cc
        if reply_to:
            msg['Reply-To'] = reply_to

        # Attach body (clean markdown fences for HTML)
        clean_body = _clean_email_body(body, html)
        mime_type = 'html' if html else 'plain'
        msg.attach(MIMEText(clean_body, mime_type, 'utf-8'))

        # Attach file
        with open(attachment_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)

            filename = os.path.basename(attachment_path)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)

        # Get recipients list
        recipients = [addr.strip() for addr in to.split(',')]
        if cc:
            recipients.extend([addr.strip() for addr in cc.split(',')])
        if bcc:
            recipients.extend([addr.strip() for addr in bcc.split(',')])

        # Send email
        smtp = get_smtp_connection()
        try:
            smtp.send_message(msg, from_addr=from_addr, to_addrs=recipients)
            mcp_log(f"[SMTP] Sent email with attachment to {to}: {subject}")
        finally:
            smtp.quit()

        # Save to Sent folder via IMAP
        _save_to_sent_folder(msg)

        return f"Success: Email with attachment sent to {to}"

    except Exception as e:
        mcp_log(f"[SMTP] Send with attachment error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def smtp_send_reply(
    to: str,
    subject: str,
    body: str,
    in_reply_to: str,
    references: str = "",
    cc: str = "",
    html: bool = False
) -> str:
    """Send a reply email via SMTP with proper threading headers.

    Args:
        to: Recipient email address(es), comma-separated
        subject: Email subject (should start with "Re: ")
        body: Email body
        in_reply_to: Message-ID of email being replied to
        references: Space-separated Message-IDs for thread (optional)
        cc: CC recipients, comma-separated (optional)
        html: Send as HTML email (default: False)

    Returns:
        Success message or error

    Example:
        smtp_send_reply(
            to="customer@example.com",
            subject="Re: Your inquiry",
            body="Thank you for your message...",
            in_reply_to="<abc123@example.com>"
        )
    """
    config = get_config()
    from_addr = config.get("smtp_user")

    if not from_addr:
        return "Error: SMTP user not configured"

    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = from_addr
        msg['To'] = to
        msg['Subject'] = subject

        if cc:
            msg['Cc'] = cc

        # Threading headers
        msg['In-Reply-To'] = in_reply_to
        if references:
            msg['References'] = f"{references} {in_reply_to}"
        else:
            msg['References'] = in_reply_to

        # Attach body (clean markdown fences for HTML)
        clean_body = _clean_email_body(body, html)
        mime_type = 'html' if html else 'plain'
        msg.attach(MIMEText(clean_body, mime_type, 'utf-8'))

        # Get recipients list
        recipients = [addr.strip() for addr in to.split(',')]
        if cc:
            recipients.extend([addr.strip() for addr in cc.split(',')])

        # Send email
        smtp = get_smtp_connection()
        try:
            smtp.send_message(msg, from_addr=from_addr, to_addrs=recipients)
            mcp_log(f"[SMTP] Sent reply to {to}: {subject}")
        finally:
            smtp.quit()

        # Save to Sent folder via IMAP
        _save_to_sent_folder(msg)

        return f"Success: Reply sent to {to}"

    except Exception as e:
        mcp_log(f"[SMTP] Send reply error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_send_reply(
    uid: str,
    folder: str = "INBOX",
    body: str = "",
    html: bool = False,
    reply_all: bool = False
) -> str:
    """Reply to an email by UID - reads headers automatically and sends via SMTP.

    Combines imap_get_email + smtp_send_reply in one step:
    1. Reads original email headers (From, Subject, Message-ID, CC)
    2. Constructs proper reply with threading headers
    3. Sends via SMTP

    Args:
        uid: Message UID of email to reply to
        folder: IMAP folder name (default: INBOX)
        body: Reply body text
        html: Send as HTML email (default: False)
        reply_all: Reply to all recipients including CC (default: False)

    Returns:
        Success message or error

    Example:
        imap_send_reply("123", body="Thank you for your message. We'll get back to you shortly.")
    """
    config = get_config()
    from_addr = config.get("smtp_user")

    if not from_addr:
        return "Error: SMTP user not configured"

    if not body:
        return "Error: Reply body is empty"

    try:
        # Step 1: Fetch original email to get headers
        imap = get_imap_connection()

        status, _ = imap.select(folder, readonly=True)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Ensure uid is bytes for fetch
        uid_bytes = uid.encode() if isinstance(uid, str) else uid

        status, msg_data = imap.fetch(uid_bytes, '(RFC822)')
        if status != 'OK' or not msg_data or not msg_data[0]:
            return f"Error: Failed to fetch email UID {uid}"

        import email as email_mod
        original = email_mod.message_from_bytes(msg_data[0][1])

        # Extract headers from original
        orig_from = original.get("From", "")
        orig_subject = original.get("Subject", "")
        orig_message_id = original.get("Message-ID", "")
        orig_references = original.get("References", "")
        orig_cc = original.get("Cc", "")
        orig_to = original.get("To", "")

        # Build reply subject
        reply_subject = orig_subject
        if not reply_subject.lower().startswith("re:"):
            reply_subject = f"Re: {reply_subject}"

        # Determine reply recipient
        reply_to = orig_from

        # Build CC for reply-all
        cc_list = ""
        if reply_all:
            cc_addrs = set()
            # Add original CC recipients
            if orig_cc:
                for addr in orig_cc.split(","):
                    addr = addr.strip()
                    if addr and from_addr.lower() not in addr.lower():
                        cc_addrs.add(addr)
            # Add original To recipients (except ourselves)
            if orig_to:
                for addr in orig_to.split(","):
                    addr = addr.strip()
                    if addr and from_addr.lower() not in addr.lower() and addr != reply_to:
                        cc_addrs.add(addr)
            if cc_addrs:
                cc_list = ", ".join(cc_addrs)

        # Build references chain
        references = ""
        if orig_references:
            references = f"{orig_references} {orig_message_id}"
        elif orig_message_id:
            references = orig_message_id

        # Step 2: Create and send reply
        msg = MIMEMultipart()
        msg['From'] = from_addr
        msg['To'] = reply_to
        msg['Subject'] = reply_subject

        if cc_list:
            msg['Cc'] = cc_list

        # Threading headers
        if orig_message_id:
            msg['In-Reply-To'] = orig_message_id
        if references:
            msg['References'] = references

        # Attach body
        clean_body = _clean_email_body(body, html)
        mime_type = 'html' if html else 'plain'
        msg.attach(MIMEText(clean_body, mime_type, 'utf-8'))

        # Get all recipients
        recipients = [addr.strip() for addr in reply_to.split(',')]
        if cc_list:
            recipients.extend([addr.strip() for addr in cc_list.split(',')])

        # Send via SMTP
        smtp = get_smtp_connection()
        try:
            smtp.send_message(msg, from_addr=from_addr, to_addrs=recipients)
            mcp_log(f"[SMTP] Sent reply to {reply_to}: {reply_subject}")
        finally:
            smtp.quit()

        # Save to Sent folder
        _save_to_sent_folder(msg)

        result = f"Success: Reply sent to {reply_to}"
        if cc_list:
            result += f" (CC: {cc_list})"
        return result

    except Exception as e:
        mcp_log(f"[SMTP] Send reply by UID error: {e}")
        return f"Error: {str(e)}"
