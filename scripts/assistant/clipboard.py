# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Clipboard utilities for DeskAgent.
Windows-only - on Linux these functions return empty/do nothing.
"""

import sys

# win32clipboard is Windows-only
win32clipboard = None
if sys.platform == 'win32':
    try:
        import win32clipboard
    except ImportError:
        pass


def get_clipboard():
    """Liest Text aus Zwischenablage (Windows-only)."""
    if not win32clipboard:
        return ""
    try:
        win32clipboard.OpenClipboard()
        data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
        return data
    except (TypeError, OSError, AttributeError):
        try:
            win32clipboard.CloseClipboard()
        except (OSError, AttributeError):
            pass
        return ""


def markdown_to_html(text: str) -> str:
    """Konvertiert einfaches Markdown zu HTML."""
    import re
    # Bold: **text** -> <b>text</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic: *text* -> <i>text</i>
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # Links: [text](url) -> <a href="url">text</a>
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
    # Bullet lists: - item -> <li>item</li>
    lines = text.split('\n')
    in_list = False
    result = []
    for line in lines:
        if line.strip().startswith('- '):
            if not in_list:
                result.append('<ul>')
                in_list = True
            result.append(f'<li>{line.strip()[2:]}</li>')
        else:
            if in_list:
                result.append('</ul>')
                in_list = False
            result.append(line)
    if in_list:
        result.append('</ul>')
    text = '\n'.join(result)
    # Line breaks
    text = text.replace('\n\n', '</p><p>')
    text = text.replace('\n', '<br>')
    return f'<p>{text}</p>'


def set_clipboard(text):
    """Schreibt Text und HTML in Zwischenablage für Outlook-Formatierung (Windows-only)."""
    if not win32clipboard:
        return  # Not available on Linux

    html_content = markdown_to_html(text)

    # Windows HTML Clipboard Format erstellen
    html_template = (
        "Version:0.9\r\n"
        "StartHTML:{:08d}\r\n"
        "EndHTML:{:08d}\r\n"
        "StartFragment:{:08d}\r\n"
        "EndFragment:{:08d}\r\n"
        "<html><body>\r\n"
        "<!--StartFragment-->{fragment}<!--EndFragment-->\r\n"
        "</body></html>"
    )

    # Header-Länge berechnen (mit Platzhaltern)
    prefix = html_template.format(0, 0, 0, 0, fragment="")
    start_html = prefix.find("<html>")
    start_fragment = prefix.find("<!--StartFragment-->") + len("<!--StartFragment-->")

    # Mit echtem Content
    full_html = html_template.format(0, 0, 0, 0, fragment=html_content)
    end_fragment = full_html.find("<!--EndFragment-->")
    end_html = len(full_html)

    # Finale Version mit korrekten Offsets
    html_data = html_template.format(start_html, end_html, start_fragment, end_fragment, fragment=html_content)

    CF_HTML = win32clipboard.RegisterClipboardFormat("HTML Format")

    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
    win32clipboard.SetClipboardData(CF_HTML, html_data.encode('utf-8'))
    win32clipboard.CloseClipboard()
