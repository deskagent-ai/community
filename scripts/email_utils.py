# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Email Utilities - Shared functions for all email MCPs
======================================================

This module provides shared email functionality used by:
- outlook_mcp
- gmail_mcp
- imap_mcp

Features:
- Email footer rendering with logo and branding
- Template system with user override support
- Markdown to HTML conversion
"""

import json
import re
import base64
from datetime import datetime
from pathlib import Path


# =============================================================================
# Path Resolution
# =============================================================================

def _get_project_paths() -> tuple:
    """Get project root and deskagent paths.

    Returns:
        tuple: (project_root, deskagent_dir)
    """
    # This file is at: deskagent/scripts/email_utils.py
    scripts_dir = Path(__file__).parent
    deskagent_dir = scripts_dir.parent
    project_root = deskagent_dir.parent
    return project_root, deskagent_dir


# =============================================================================
# Logo Loading
# =============================================================================

_logo_base64_cache = None


def get_logo_base64() -> str:
    """Get DeskAgent logo as base64 data-URI (lazy-loaded, cached).

    Returns:
        Base64 data-URI string for the logo, or empty string if not found
    """
    global _logo_base64_cache
    if _logo_base64_cache is not None:
        return _logo_base64_cache

    project_root, deskagent_dir = _get_project_paths()

    # Search paths for logo (user override first, then system default)
    # Use PNG for best email client compatibility (SVG not supported by Outlook)
    # Use 48px height logo for better visibility in email clients
    logo_paths = [
        project_root / "templates" / "icons" / "logo48h.png",  # User override (48px)
        deskagent_dir / "scripts" / "templates" / "icons" / "logo48h.png",  # System default (48px)
        project_root / "templates" / "icons" / "logo32h.png",  # Fallback (32px)
        deskagent_dir / "scripts" / "templates" / "icons" / "logo32h.png",  # Fallback (32px)
    ]

    for logo_path in logo_paths:
        if logo_path.exists():
            try:
                with open(logo_path, "rb") as f:
                    logo_bytes = f.read()
                _logo_base64_cache = f"data:image/png;base64,{base64.b64encode(logo_bytes).decode('utf-8')}"
                return _logo_base64_cache
            except (OSError, IOError):
                pass  # Logo file read failed - try next path

    # Fallback: empty string (no logo)
    _logo_base64_cache = ""
    return _logo_base64_cache


# =============================================================================
# Template Loading
# =============================================================================

def load_email_template(template_name: str = "email_footer.html") -> str:
    """Load email template with user override support.

    Search order:
      1. templates/{template_name} (user override in project root)
      2. deskagent/templates/{template_name} (system default)

    Args:
        template_name: Name of the template file

    Returns:
        Template content as string, or minimal fallback if not found
    """
    project_root, deskagent_dir = _get_project_paths()

    search_paths = [
        project_root / "templates" / template_name,  # User override
        deskagent_dir / "templates" / template_name,  # System default
    ]

    for template_path in search_paths:
        if template_path.exists():
            try:
                with open(template_path, "r", encoding="utf-8") as f:
                    return f.read()
            except (OSError, IOError, UnicodeDecodeError):
                pass  # Template file read failed - try next path

    # Fallback: minimal footer
    return '<hr style="border: none; border-top: 1px solid #e0e0e0; margin: 16px 0;">'


# =============================================================================
# Configuration
# =============================================================================

_config_cache = None
_config_cache_time = 0


def get_email_config() -> dict:
    """Get email configuration from system.json (cached for 60 seconds).

    Returns:
        Email config dict with keys: footer_enabled, footer_template, footer_slogan
    """
    global _config_cache, _config_cache_time

    # Cache for 60 seconds
    import time
    now = time.time()
    if _config_cache is not None and (now - _config_cache_time) < 60:
        return _config_cache

    project_root, deskagent_dir = _get_project_paths()

    config_paths = [
        project_root / "config" / "system.json",  # User config
        deskagent_dir / "config" / "system.json",  # System default
    ]

    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    _config_cache = config.get("email", {})
                    _config_cache_time = now
                    return _config_cache
            except (json.JSONDecodeError, OSError, IOError, UnicodeDecodeError):
                pass  # Config file read/parse failed - try next path

    _config_cache = {}
    _config_cache_time = now
    return _config_cache


# =============================================================================
# Footer Rendering
# =============================================================================

def render_email_footer(lang: str = "de") -> str:
    """Render email footer from template with placeholders replaced.

    Args:
        lang: Language code ("de", "en") for template selection

    Returns:
        Rendered HTML footer string, or empty string if disabled
    """
    config = get_email_config()

    # Check if footer is enabled (default: False for backwards compatibility)
    if not config.get("footer_enabled", False):
        return ""

    # Determine template name
    template_name = config.get("footer_template", "email_footer.html")

    # Try language-specific template first
    if lang and lang != "de":
        lang_template = template_name.replace(".html", f"_{lang}.html")
        template = load_email_template(lang_template)
        # If language template not found (got fallback), use default
        if "<hr" in template and "table" not in template.lower():
            template = load_email_template(template_name)
    else:
        template = load_email_template(template_name)

    # Replace placeholders
    logo_base64 = get_logo_base64()
    slogan = config.get("footer_slogan", "Your Desktop. Your Agent.")
    year = str(datetime.now().year)

    # Handle default value syntax: {{SLOGAN|}default value|}
    template = re.sub(r'\{\{SLOGAN\|[^}]*\}\}', slogan, template)
    template = template.replace("{{LOGO_BASE64}}", logo_base64)
    template = template.replace("{{SLOGAN}}", slogan)
    template = template.replace("{{YEAR}}", year)

    return template


# =============================================================================
# Markdown to HTML Conversion
# =============================================================================

def markdown_to_html(text: str, include_footer: bool = True, lang: str = "de") -> str:
    """Convert simple Markdown to HTML for email clients.

    Supports:
    - **bold** -> <b>bold</b>
    - *italic* -> <i>italic</i>
    - [text](url) -> <a href="url">text</a>
    - Paragraph breaks (double newline)
    - Line breaks (single newline)

    Args:
        text: Markdown text to convert
        include_footer: Whether to include the DeskAgent footer (if enabled in config)
        lang: Language code for footer template selection ("de", "en")

    Returns:
        HTML string with optional footer
    """
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
    text = text.replace('\n\n', '</p><p>')
    text = text.replace('\n', '<br>')

    html = f'<div style="font-family: Calibri, sans-serif; font-size: 11pt;"><p>{text}</p></div>'

    # Add footer if enabled
    if include_footer:
        footer = render_email_footer(lang)
        if footer:
            html += footer

    return html


# =============================================================================
# Email Thread Parsing
# =============================================================================

def extract_latest_message(body: str, max_length: int = 0) -> str:
    """Extract only the latest message from an email thread.

    Removes:
    - Quoted replies (lines starting with >)
    - Previous message headers (From:, Sent:, To:, Subject:, Date:)
    - Gmail/Outlook thread markers
    - Email metadata (Labels, ID, Thread, INBOX ID, etc.)

    This function is used by outlook_mcp, gmail_mcp, imap_mcp, and msgraph_mcp.

    Args:
        body: Raw email body text
        max_length: Optional max length (0 = unlimited)

    Returns:
        Cleaned email body with only the latest message
    """
    if not body:
        return ""

    # Remove inline metadata patterns (Gmail adds these)
    body = re.sub(r'\s*Labels?:\s*[A-Z_,\s]+(?=\s|$)', '', body)
    body = re.sub(r'\s*INBOX\s*ID:\s*\S+', '', body)
    body = re.sub(r'\s*Thread:\s*\S+', '', body)
    body = re.sub(r'\s*ID:\s*[a-f0-9]+(?=\s|$)', '', body)

    # Remove "Date: Sun, 11 Jan 2026..." patterns
    body = re.sub(r'\s*Date:\s*\w+,\s*\d+\s+\w+\s+\d+\s+[\d:]+\s*[+-]?\d*', '', body)

    # Clean up duplicate subject headers
    body = re.sub(r'Subject:\s*(Re:\s*)+Subject:', 'Betreff:', body)
    body = re.sub(r'Betreff:\s*(Re:\s*)+', 'Betreff: ', body)

    # Remove inline From/To headers
    body = re.sub(r'\s*From:\s*[^<]+<[^>]+>\s*To:\s*[^<]+<[^>]+>', '', body)

    lines = body.split('\n')
    result_lines = []
    in_quoted_section = False

    for line in lines:
        stripped = line.strip()

        # Skip quoted lines
        if stripped.startswith('>'):
            in_quoted_section = True
            continue

        # Detect thread separator patterns - stop here
        if re.search(r'-{3,}.*Original Message.*-{3,}', stripped, re.IGNORECASE):
            break
        if re.match(r'^On .+ wrote:$', stripped):
            break
        if re.match(r'^Am .+ schrieb .+:$', stripped):
            break
        if 'Gesendet von Outlook' in stripped or 'Sent from Outlook' in stripped:
            break
        if re.match(r'^Von:', stripped) and 'Gesendet:' in body[body.find(stripped):body.find(stripped)+200]:
            break
        if re.match(r'^From:', stripped) and 'Sent:' in body[body.find(stripped):body.find(stripped)+200]:
            break

        if stripped and in_quoted_section:
            in_quoted_section = False

        if not in_quoted_section:
            result_lines.append(line)

    result = '\n'.join(result_lines).strip()
    result = re.sub(r'\n{3,}', '\n\n', result)
    result = re.sub(r'  +', ' ', result)

    if max_length > 0 and len(result) > max_length:
        result = result[:max_length] + '...'

    return result


# =============================================================================
# HTML Utilities
# =============================================================================

def strip_markdown_fences(text: str) -> str:
    """Strip markdown code fences from text.

    Removes patterns like:
    - ```html\\n...\\n```
    - ```\\n...\\n```
    - Leading/trailing whitespace

    Args:
        text: Text that may contain markdown code fences

    Returns:
        Clean text without code fences
    """
    if not text:
        return ""

    # Strip leading/trailing whitespace
    text = text.strip()

    # Remove opening fence: ```html, ```xml, ```json, or just ```
    text = re.sub(r'^```\w*\s*\n?', '', text)

    # Remove closing fence
    text = re.sub(r'\n?```\s*$', '', text)

    return text.strip()


def append_footer_to_html(html_body: str, lang: str = "de") -> str:
    """Append email footer to existing HTML body.

    Use this for MCPs that receive raw HTML (not markdown) from agents.

    Args:
        html_body: Existing HTML content
        lang: Language code for footer template selection

    Returns:
        HTML with footer appended (if enabled), or original HTML if disabled
    """
    footer = render_email_footer(lang)
    if footer:
        return html_body + footer
    return html_body


# =============================================================================
# Logging Helpers
# =============================================================================

def truncate_for_log(text: str, max_length: int = 500, single_line: bool = True) -> str:
    """Truncate text for log output.

    Args:
        text: Text to truncate
        max_length: Maximum length (default 500)
        single_line: Replace newlines with spaces (default True)

    Returns:
        Truncated text with "..." suffix if truncated
    """
    if not text:
        return ""
    result = text[:max_length]
    if single_line:
        result = result.replace('\n', ' ')
    if len(text) > max_length:
        result += "..."
    return result


def format_email_log(
    uid: str,
    sender: str = "",
    sender_email: str = "",
    subject: str = "",
    body: str = "",
    max_body: int = 500
) -> str:
    """Format email details for logging.

    Args:
        uid: Email UID
        sender: Sender display name
        sender_email: Sender email address
        subject: Email subject
        body: Email body (will be truncated)
        max_body: Max body preview length

    Returns:
        Multi-line formatted log string
    """
    lines = [
        "INPUT EMAIL:",
        f"  UID: {uid}",
        f"  From: {sender or 'unknown'} <{sender_email or 'unknown'}>",
        f"  Subject: {subject or 'no subject'}",
        f"  Body: {truncate_for_log(body, max_body)}",
    ]
    return "\n".join(lines)


# =============================================================================
# Reply Helpers
# =============================================================================

def build_reply_subject(subject: str) -> str:
    """Ensure subject has Re: prefix for replies.

    Args:
        subject: Original email subject

    Returns:
        Subject with "Re: " prefix if not already present
    """
    if not subject:
        return "Re:"
    if not subject.lower().startswith("re:"):
        return f"Re: {subject}"
    return subject


def build_email_context(
    uid: str,
    message_id: str,
    sender: str,
    sender_email: str,
    subject: str,
    body: str,
    max_body_length: int = 4000
) -> dict:
    """Build standardized context dict for email reply agents.

    This creates the input format expected by email reply agents like
    deskagent_support_reply.

    Args:
        uid: Email UID (IMAP/Graph)
        message_id: Message-ID header for threading
        sender: Sender display name
        sender_email: Sender email address
        subject: Email subject
        body: Email body text
        max_body_length: Max body length to include (default 4000)

    Returns:
        Dict with keys: uid, message_id, sender, sender_email, subject, body
    """
    return {
        "uid": uid,
        "message_id": message_id or "",
        "sender": sender or "",
        "sender_email": sender_email or "",
        "subject": subject or "",
        "body": body[:max_body_length] if body else ""
    }


def build_email_prompt(
    sender: str,
    sender_email: str,
    subject: str,
    body: str,
    lang: str = "de"
) -> str:
    """Build readable prompt string for agent history display.

    Creates a clean, human-readable version of the email for display
    in the History panel. Uses extract_latest_message to remove
    quoted replies and thread history.

    Args:
        sender: Sender display name
        sender_email: Sender email address
        subject: Email subject
        body: Raw email body (will be cleaned)
        lang: Language for header labels ("de" or "en")

    Returns:
        Formatted prompt string
    """
    clean_body = extract_latest_message(body)

    if lang == "en":
        return f"Email from: {sender}\nSubject: {subject}\n\n{clean_body}"
    else:
        return f"E-Mail von: {sender}\nBetreff: {subject}\n\n{clean_body}"


def format_quoted_original(
    sender: str,
    sender_email: str,
    subject: str,
    body: str,
    date: str = "",
    lang: str = "de"
) -> str:
    """Format original email as HTML quote block for inclusion in reply.

    Creates a properly formatted "quoted original" section that appears
    below the reply, similar to standard email clients.

    Args:
        sender: Original sender display name
        sender_email: Original sender email address
        subject: Original email subject
        body: Original email body (plain text)
        date: Original email date (optional)
        lang: Language for labels ("de" or "en")

    Returns:
        HTML string with quoted original email
    """
    # Extract body after "--- Body ---" marker (from IMAP tool output)
    if "--- Body ---" in body:
        body = body.split("--- Body ---", 1)[1]

    # Clean the body (remove previous quotes, metadata)
    clean_body = extract_latest_message(body, max_length=2000)

    # Escape HTML characters in the body
    import html
    safe_body = html.escape(clean_body).replace('\n', '<br>')

    # Format date if provided
    date_line = ""
    if date:
        if lang == "en":
            date_line = f'<b>Sent:</b> {date}<br>'
        else:
            date_line = f'<b>Gesendet:</b> {date}<br>'

    # Build the quoted block
    if lang == "en":
        header = f'''
<b>From:</b> {html.escape(sender)}<br>
{date_line}<b>Subject:</b> {html.escape(subject)}
'''
    else:
        header = f'''
<b>Von:</b> {html.escape(sender)}<br>
{date_line}<b>Betreff:</b> {html.escape(subject)}
'''

    return f'''
<div style="margin-top: 20px; padding-top: 10px; border-top: 1px solid #ccc;">
  <div style="color: #666; font-size: 12px; margin-bottom: 10px;">
    {header.strip()}
  </div>
  <div style="color: #555; font-size: 13px; padding-left: 10px; border-left: 3px solid #ccc;">
    {safe_body}
  </div>
</div>
'''


def build_reply_body(
    response: str,
    sender: str,
    sender_email: str,
    subject: str,
    original_body: str,
    lang: str = "en"
) -> str:
    """Build complete reply body: response + footer + quoted original.

    Convenience function that combines all parts of an email reply.

    Args:
        response: AI-generated response text (HTML)
        sender: Original sender display name
        sender_email: Original sender email address
        subject: Original email subject
        original_body: Original email body
        lang: Language ("de" or "en")

    Returns:
        Complete HTML body ready for sending
    """
    # Start with response
    body = response

    # Add footer
    body = append_footer_to_html(body, lang=lang)

    # Add quoted original
    body += format_quoted_original(
        sender=sender,
        sender_email=sender_email,
        subject=subject,
        body=original_body,
        lang=lang
    )

    return body
