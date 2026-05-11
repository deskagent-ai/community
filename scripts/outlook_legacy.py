# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Outlook-Integration
===================
Funktionen für die Kommunikation mit Microsoft Outlook.
"""

import json
import re
from datetime import datetime
from .config import TEMP_DIR, CURRENT_EMAIL, DRAFT_RESPONSE

# Import system_log for logging
try:
    from ai_agent import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available


def markdown_to_html(text: str) -> str:
    """Konvertiert einfaches Markdown zu HTML für Outlook."""
    # Bold: **text** -> <b>text</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic: *text* -> <i>text</i>
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # Links: [text](url) -> <a href="url">text</a>
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
    # Line breaks
    text = text.replace('\n\n', '</p><p>')
    text = text.replace('\n', '<br>')
    # Wrap in paragraph
    text = f'<p>{text}</p>'
    return text


def init_outlook():
    """Initialisiert Outlook COM-Objekt"""
    import pythoncom
    import win32com.client
    
    pythoncom.CoInitialize()
    return win32com.client.Dispatch("Outlook.Application")


def export_selected_email() -> dict | None:
    """
    Exportiert die in Outlook markierte E-Mail nach .temp/current-email.json
    
    Returns:
        dict mit E-Mail-Daten oder None bei Fehler
    """
    try:
        outlook = init_outlook()
        explorer = outlook.ActiveExplorer()
        
        if not explorer:
            system_log("[Outlook] Kein Outlook-Fenster aktiv")
            return None

        selection = explorer.Selection

        if selection.Count == 0:
            system_log("[Outlook] Keine E-Mail ausgewaehlt")
            return None
        
        mail = selection.Item(1)
        
        email_data = {
            "id": mail.EntryID,
            "subject": mail.Subject,
            "sender_email": str(mail.SenderEmailAddress),
            "sender_name": str(mail.SenderName),
            "body": mail.Body,
            "received": str(mail.ReceivedTime),
            "exported_at": datetime.now().isoformat()
        }
        
        TEMP_DIR.mkdir(exist_ok=True)
        CURRENT_EMAIL.write_text(
            json.dumps(email_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        system_log(f"[Outlook] E-Mail exportiert: {mail.Subject[:50]}...")
        return email_data

    except Exception as e:
        system_log(f"[Outlook] Fehler beim Export: {e}")
        return None


def create_outlook_draft() -> bool:
    """
    Erstellt einen Outlook-Draft aus der generierten Antwort.
    
    Liest .temp/draft-response.md und erstellt eine Antwort
    auf die Original-E-Mail als Entwurf.
    
    Returns:
        True bei Erfolg, False bei Fehler
    """
    if not DRAFT_RESPONSE.exists():
        system_log("[Outlook] Keine Antwort-Datei gefunden")
        return False

    if not CURRENT_EMAIL.exists():
        system_log("[Outlook] Keine E-Mail-Daten gefunden")
        return False
    
    try:
        draft_body = DRAFT_RESPONSE.read_text(encoding="utf-8")
        email_data = json.loads(CURRENT_EMAIL.read_text(encoding="utf-8"))
        
        outlook = init_outlook()
        namespace = outlook.GetNamespace("MAPI")
        
        original = namespace.GetItemFromID(email_data["id"])
        reply = original.Reply()

        # Convert markdown to HTML and prepend to existing HTML body
        html_draft = markdown_to_html(draft_body)
        reply.HTMLBody = html_draft + "<br><br>" + reply.HTMLBody
        reply.Save()
        
        system_log("[Outlook] Draft in Outlook erstellt")
        system_log("[Outlook] Oeffne Entwuerfe-Ordner um zu pruefen und zu senden")
        return True

    except Exception as e:
        system_log(f"[Outlook] Fehler beim Draft-Erstellen: {e}")
        return False


def get_unread_emails(limit: int = 10) -> list:
    """
    Holt ungelesene E-Mails aus dem Posteingang.
    
    Args:
        limit: Maximale Anzahl E-Mails
        
    Returns:
        Liste mit E-Mail-Daten
    """
    try:
        outlook = init_outlook()
        namespace = outlook.GetNamespace("MAPI")
        inbox = namespace.GetDefaultFolder(6)  # 6 = Inbox
        
        messages = inbox.Items
        messages.Sort("[ReceivedTime]", True)
        
        result = []
        count = 0
        
        for msg in messages:
            if not msg.UnRead:
                continue
            result.append({
                "id": msg.EntryID,
                "subject": msg.Subject,
                "sender_email": str(msg.SenderEmailAddress),
                "sender_name": str(msg.SenderName),
                "received": str(msg.ReceivedTime)
            })
            count += 1
            if count >= limit:
                break
        
        return result
        
    except Exception as e:
        system_log(f"[Outlook] Fehler beim Abrufen: {e}")
        return []
