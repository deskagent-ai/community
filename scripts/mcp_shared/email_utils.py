# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP Shared - Email Utilities
============================
Common email processing functions used by outlook, msgraph, gmail, and imap MCPs.
"""

import re
import html


def extract_latest_message(body: str, max_length: int = 0) -> str:
    """Extract only the latest message from an email thread.

    Removes:
    - Quoted replies (lines starting with >)
    - Previous message headers (From:, Sent:, To:, Subject:, Date:)
    - Gmail/Outlook thread markers
    - Email metadata (Labels, ID, Thread, INBOX ID, etc.)

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


def html_to_text(html_content: str, mode: str = "full") -> str:
    """Convert HTML content to plain text.

    Args:
        html_content: HTML string to convert
        mode: Conversion mode:
            - "simple" - Quick strip for short content (Teams messages)
            - "full" - Preserve structure for emails (default)

    Returns:
        Plain text content

    Examples:
        # Full mode - preserve structure for emails (default)
        text = html_to_text(body_content)

        # Simple mode - quick strip for short content
        text = html_to_text(content, mode="simple")
    """
    if not html_content:
        return ""

    if mode == "simple":
        # Quick strip for short content
        content = re.sub(r'<[^>]+>', '', html_content)
        content = re.sub(r'\s+', ' ', content).strip()
        return html.unescape(content)

    # Full mode (default) - preserve structure
    # 1. Replace block elements with newlines
    content = re.sub(r'<br\s*/?>', '\n', html_content, flags=re.IGNORECASE)
    content = re.sub(r'</p>', '\n\n', content, flags=re.IGNORECASE)
    content = re.sub(r'</div>', '\n', content, flags=re.IGNORECASE)
    content = re.sub(r'</tr>', '\n', content, flags=re.IGNORECASE)
    content = re.sub(r'</li>', '\n', content, flags=re.IGNORECASE)
    content = re.sub(r'</h[1-6]>', '\n\n', content, flags=re.IGNORECASE)

    # 2. Remove all remaining HTML tags
    content = re.sub(r'<[^>]+>', '', content)

    # 3. Decode HTML entities (&nbsp;, &amp;, etc.)
    content = html.unescape(content)

    # 4. Clean up whitespace but preserve newlines
    lines = content.split('\n')
    lines = [' '.join(line.split()) for line in lines]
    content = '\n'.join(lines)

    # 5. Remove excessive blank lines (max 2)
    content = re.sub(r'\n{3,}', '\n\n', content)

    return content.strip()
