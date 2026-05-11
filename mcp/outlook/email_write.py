# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Outlook MCP - Email Write Module
===============================
Functions for creating and replying to emails.
"""

import os
import re

from outlook.base import (
    mcp, outlook_tool,
    get_outlook, get_namespace, markdown_to_html, mcp_log
)

# Cache: {original_entry_id: draft_entry_id}
# Prevents duplicate drafts when Claude SDK calls the tool twice
_reply_draft_cache = {}  # type: dict[str, str]


def _try_update_cached_draft(original_id: str, html_body: str) -> str | None:
    """Try to update an existing cached draft instead of creating a new one.

    Args:
        original_id: EntryID of the original email being replied to
        html_body: New HTML body content for the draft

    Returns:
        Success message if draft was updated, None if no cached draft found
    """
    if not original_id or original_id not in _reply_draft_cache:
        return None

    draft_id = _reply_draft_cache[original_id]
    try:
        namespace = get_namespace()
        draft = namespace.GetItemFromID(draft_id)
        if draft.Sent:
            # Draft was already sent, remove stale cache entry
            mcp_log(f"[Outlook] [ReplyDraft] Cache miss: draft already sent for {original_id[:20]}...")
            del _reply_draft_cache[original_id]
            return None
        # Update existing draft
        draft.HTMLBody = html_body
        draft.Save()
        mcp_log(f"[Outlook] [ReplyDraft] Cache hit: updated existing draft for {original_id[:20]}...")
        subject = getattr(draft, "Subject", "")
        return f"Antwort-Entwurf aktualisiert: {subject}"
    except Exception as e:
        # Draft was deleted or moved, remove stale cache entry
        mcp_log(f"[Outlook] [ReplyDraft] Cache miss (invalid): {e} for {original_id[:20]}...")
        _reply_draft_cache.pop(original_id, None)
        return None


def _strip_signature_from_reply(html_body: str) -> str:
    """Strip Outlook's auto-signature from reply, keeping only the quoted original.

    Outlook replies have this structure:
    [Signature] + [Quoted original with "From:", "Sent:", etc. header]

    We want to keep only the quoted original part.
    """
    if not html_body:
        return ""

    # Look for common reply separator patterns in HTML
    # German: "Von:", English: "From:", "Gesendet:", "Sent:", etc.
    patterns = [
        r'<div[^>]*>[\s\S]*?(?:<b>)?(?:Von|From|De):\s*</?(b)?',  # "From:" in div
        r'<p[^>]*>[\s\S]*?(?:<b>)?(?:Von|From|De):\s*</?(b)?',    # "From:" in p
        r'(?:<b>)?(?:Von|From|De):</?(b)?',                        # Simple "From:"
        r'<hr[^>]*>',                                              # Horizontal rule
        r'-{3,}',                                                  # Dashes separator
    ]

    for pattern in patterns:
        match = re.search(pattern, html_body, re.IGNORECASE)
        if match:
            # Return from the match point onwards (the quoted original)
            return html_body[match.start():]

    # No separator found - return empty (no quoted message)
    return ""


@mcp.tool()
@outlook_tool
def outlook_create_reply_draft(body: str, reply_all: bool = True, include_footer: bool = False) -> str:
    """Erstellt einen Antwort-Entwurf auf die ausgewählte E-Mail.

    Args:
        body: Antwort-Text (unterstützt Markdown)
        reply_all: Allen antworten (Standard: True) oder nur dem Absender (False)
        include_footer: DeskAgent-Footer anhängen (Standard: False)
    """
    try:
        outlook = get_outlook()
        explorer = outlook.ActiveExplorer()

        if not explorer:
            return "Fehler: Kein Outlook-Fenster aktiv"

        selection = explorer.Selection
        if selection.Count == 0:
            return "Fehler: Keine E-Mail ausgewählt"

        mail = selection.Item(1)
        original_id = getattr(mail, "EntryID", None)

        # Idempotency check: if we already created a draft for this mail, update it
        html_body = markdown_to_html(body, include_footer=include_footer)
        if original_id:
            updated = _try_update_cached_draft(original_id, html_body)
            if updated:
                return updated

        # Check if there's an active inline response - close it first
        try:
            inline_response = explorer.ActiveInlineResponse
            if inline_response is not None:
                # Delete inline response draft and create fresh reply
                try:
                    inline_response.Delete()
                except Exception:
                    pass  # Ignore if delete fails
        except Exception:
            pass  # ActiveInlineResponse not available in older Outlook

        # Create reply
        try:
            reply = mail.ReplyAll() if reply_all else mail.Reply()
        except Exception as e:
            if "inline response" in str(e).lower():
                # Fallback: Display the mail first to get out of inline mode
                mail.Display()
                reply = mail.ReplyAll() if reply_all else mail.Reply()
            else:
                raise

        # Strip Outlook's auto-signature, keep only quoted original
        quoted_original = _strip_signature_from_reply(reply.HTMLBody)
        reply.HTMLBody = html_body + ("<br><br>" + quoted_original if quoted_original else "")

        # Use Display() + Save() to avoid inline response issues
        reply.Display()
        reply.Save()

        # Cache the draft EntryID for idempotency
        if original_id and getattr(reply, "EntryID", None):
            _reply_draft_cache[original_id] = reply.EntryID
            mcp_log(f"[Outlook] [ReplyDraft] New draft cached for {original_id[:20]}...")

        reply_type = "Allen" if reply_all else "Absender"
        return f"Antwort-Entwurf erstellt ({reply_type}): {mail.Subject}"

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_send_reply(body: str, reply_all: bool = True, include_footer: bool = False) -> str:
    """Erstellt und sendet sofort eine Antwort auf die ausgewählte E-Mail (Draft + Send in einem Schritt).

    Kombiniert outlook_create_reply_draft + Senden für einfachere Workflows.

    Args:
        body: Antwort-Text (unterstützt Markdown)
        reply_all: Allen antworten (Standard: True) oder nur dem Absender (False)
        include_footer: DeskAgent-Footer anhängen (Standard: False)
    """
    try:
        outlook = get_outlook()
        explorer = outlook.ActiveExplorer()

        if not explorer:
            return "Fehler: Kein Outlook-Fenster aktiv"

        selection = explorer.Selection
        if selection.Count == 0:
            return "Fehler: Keine E-Mail ausgewählt"

        mail = selection.Item(1)

        # Check if there's an active inline response - close it first
        try:
            inline_response = explorer.ActiveInlineResponse
            if inline_response is not None:
                try:
                    inline_response.Delete()
                except Exception:
                    pass
        except Exception:
            pass

        # Create reply
        try:
            reply = mail.ReplyAll() if reply_all else mail.Reply()
        except Exception as e:
            if "inline response" in str(e).lower():
                mail.Display()
                reply = mail.ReplyAll() if reply_all else mail.Reply()
            else:
                raise

        html_body = markdown_to_html(body, include_footer=include_footer)
        # Strip Outlook's auto-signature, keep only quoted original
        quoted_original = _strip_signature_from_reply(reply.HTMLBody)
        reply.HTMLBody = html_body + ("<br><br>" + quoted_original if quoted_original else "")

        # Send immediately
        reply.Send()

        reply_type = "Allen" if reply_all else "Absender"
        return f"""Antwort gesendet!
- Betreff: Re: {mail.Subject}
- An: {reply_type}
- Status: Gesendet"""

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_create_reply_draft_with_attachment(
    body: str,
    attachment_path: str,
    display: bool = True,
    reply_all: bool = True,
    include_footer: bool = False
) -> str:
    """Erstellt einen Antwort-Entwurf mit Anhang auf die ausgewählte E-Mail.

    Ideal für: Anfrage erhalten → Angebot erstellen → Mit Angebot-PDF antworten.

    Args:
        body: Antwort-Text (unterstützt Markdown)
        attachment_path: Vollständiger Pfad zur Datei (z.B. PDF von Billomat)
        display: E-Mail im Fenster anzeigen (Standard: True)
        reply_all: Allen antworten (Standard: True) oder nur dem Absender (False)
        include_footer: DeskAgent-Footer anhängen (Standard: False)
    """
    try:
        # Prüfe ob Datei existiert
        if not os.path.exists(attachment_path):
            return f"Fehler: Datei nicht gefunden: {attachment_path}"

        outlook = get_outlook()
        explorer = outlook.ActiveExplorer()

        if not explorer:
            return "Fehler: Kein Outlook-Fenster aktiv"

        selection = explorer.Selection
        if selection.Count == 0:
            return "Fehler: Keine E-Mail ausgewählt"

        mail = selection.Item(1)
        original_id = getattr(mail, "EntryID", None)

        # Idempotency check: if we already created a draft for this mail, update it
        html_body = markdown_to_html(body, include_footer=include_footer)
        if original_id:
            updated = _try_update_cached_draft(original_id, html_body)
            if updated:
                return updated

        # Check if there's an active inline response - close it first
        try:
            inline_response = explorer.ActiveInlineResponse
            if inline_response is not None:
                try:
                    inline_response.Delete()
                except Exception:
                    pass
        except Exception:
            pass

        # Create reply with inline response fallback
        try:
            reply = mail.ReplyAll() if reply_all else mail.Reply()
        except Exception as e:
            if "inline response" in str(e).lower():
                mail.Display()
                reply = mail.ReplyAll() if reply_all else mail.Reply()
            else:
                raise

        # Strip Outlook's auto-signature, keep only quoted original
        quoted_original = _strip_signature_from_reply(reply.HTMLBody)
        reply.HTMLBody = html_body + ("<br><br>" + quoted_original if quoted_original else "")

        # Anhang hinzufügen
        reply.Attachments.Add(attachment_path)

        # Always display to avoid inline response issues, then save
        reply.Display()
        reply.Save()

        # Cache the draft EntryID for idempotency
        if original_id and getattr(reply, "EntryID", None):
            _reply_draft_cache[original_id] = reply.EntryID
            mcp_log(f"[Outlook] [ReplyDraft] New draft with attachment cached for {original_id[:20]}...")

        filename = os.path.basename(attachment_path)
        return f"""Antwort-Entwurf mit Anhang erstellt!
- Antwort auf: {mail.Subject}
- Von: {mail.SenderName}
- Anhang: {filename}
- Status: Entwurf gespeichert und geöffnet"""

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_update_draft(body: str, replace: bool = False) -> str:
    """Aktualisiert den zuletzt erstellten/geöffneten E-Mail-Entwurf.

    Sucht zuerst nach einem offenen Entwurf-Fenster, dann im Entwürfe-Ordner.

    Args:
        body: Neuer Text für den Entwurf (unterstützt Markdown)
        replace: True = Text komplett ersetzen, False = Text voranstellen (Standard)
    """
    try:
        outlook = get_outlook()

        # 1. Versuche offenes Entwurf-Fenster zu finden
        draft = None
        for inspector in outlook.Inspectors:
            item = inspector.CurrentItem
            # Prüfe ob es ein ungesendeter Mail-Entwurf ist (Class 43 = MailItem)
            if hasattr(item, 'Class') and item.Class == 43:
                if not item.Sent:
                    draft = item
                    break

        # 2. Falls kein offenes Fenster, neuesten Entwurf aus Ordner holen
        if draft is None:
            drafts_folder = outlook.GetNamespace("MAPI").GetDefaultFolder(16)  # 16 = Drafts
            if drafts_folder.Items.Count > 0:
                # Sortiere nach Erstellungsdatum, neuester zuerst
                drafts_folder.Items.Sort("[CreationTime]", True)
                draft = drafts_folder.Items.GetFirst()

        if draft is None:
            return "Fehler: Kein Entwurf gefunden (weder offen noch im Entwürfe-Ordner)"

        # Aktualisiere den Body
        html_body = markdown_to_html(body)
        if replace:
            draft.HTMLBody = html_body
        else:
            # Voranstellen: neuer Text + vorhandener Body
            draft.HTMLBody = html_body + "<br><br>" + draft.HTMLBody

        draft.Save()

        return f"Entwurf aktualisiert: {draft.Subject}"

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_create_new_email(to: str, subject: str, body: str) -> str:
    """Erstellt eine neue E-Mail als Entwurf."""
    try:
        outlook = get_outlook()
        mail = outlook.CreateItem(0)

        mail.To = to
        mail.Subject = subject
        mail.HTMLBody = markdown_to_html(body)
        mail.Save()

        return f"E-Mail-Entwurf erstellt: '{subject}' an {to}"

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_create_new_email_with_attachment(
    to: str,
    subject: str,
    body: str,
    attachment_path: str,
    cc: str = "",
    display: bool = True
) -> str:
    """Erstellt eine neue E-Mail mit Anhang als Entwurf.

    Args:
        to: Empfänger E-Mail-Adresse
        subject: Betreff
        body: E-Mail-Text (unterstützt Markdown)
        attachment_path: Vollständiger Pfad zur Datei (z.B. PDF von Billomat)
        cc: CC-Empfänger (optional)
        display: E-Mail im Fenster anzeigen (Standard: True)
    """
    try:
        # Prüfe ob Datei existiert
        if not os.path.exists(attachment_path):
            return f"Fehler: Datei nicht gefunden: {attachment_path}"

        outlook = get_outlook()
        mail = outlook.CreateItem(0)

        mail.To = to
        mail.Subject = subject
        mail.HTMLBody = markdown_to_html(body)

        if cc:
            mail.CC = cc

        # Anhang hinzufügen
        mail.Attachments.Add(attachment_path)

        mail.Save()

        # Optional: E-Mail-Fenster öffnen
        if display:
            mail.Display()

        filename = os.path.basename(attachment_path)
        return f"""E-Mail-Entwurf mit Anhang erstellt!
- An: {to}
- Betreff: {subject}
- Anhang: {filename}
- Status: Entwurf gespeichert{' und geöffnet' if display else ''}"""

    except Exception as e:
        return f"Fehler: {str(e)}"
