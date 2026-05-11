# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Outlook MCP - Attachments Module
================================
Functions for handling email attachments.
"""

import json
import os
import re
import tempfile

from outlook.base import (
    mcp, outlook_tool,
    get_namespace, EmailFinder
)


@mcp.tool()
@outlook_tool
def outlook_get_email_attachments(query: str = None, index: int = 0, selection_index: int = 1) -> str:
    """Listet alle Anhänge einer E-Mail auf.

    Args:
        query: Suchbegriff für E-Mail (None = markierte E-Mail verwenden)
        index: Index in den Suchergebnissen (0 = neueste)
        selection_index: Bei Mehrfachauswahl: welche E-Mail (1-basiert, Standard: 1)

    Returns:
        Liste der Anhänge mit Index, Name und Größe
    """
    finder = EmailFinder()
    mail, error = finder.get_mail(query=query, index=index, selection_index=selection_index)
    if error:
        return error

    attachments = mail.Attachments
    if attachments.Count == 0:
        return f"E-Mail '{mail.Subject}' hat keine Anhänge"

    result = [f"Anhänge der E-Mail: {mail.Subject}\n"]
    for i in range(1, attachments.Count + 1):
        att = attachments.Item(i)
        size_kb = att.Size / 1024
        result.append(f"[{i-1}] {att.FileName} ({size_kb:.1f} KB)")

    return "\n".join(result)


@mcp.tool()
@outlook_tool
def outlook_save_email_attachment(
    attachment_index: int = 0,
    query: str = None,
    email_index: int = 0,
    save_path: str = None,
    selection_index: int = 1
) -> str:
    """Speichert einen E-Mail-Anhang auf die Festplatte.

    Args:
        attachment_index: Index des Anhangs (0 = erster Anhang)
        query: Suchbegriff für E-Mail (None = markierte E-Mail)
        email_index: Index in den Suchergebnissen (0 = neueste)
        save_path: Zielordner (None = temp-Verzeichnis)
        selection_index: Bei Mehrfachauswahl: welche E-Mail (1-basiert, Standard: 1)

    Returns:
        Vollständiger Pfad zur gespeicherten Datei
    """
    finder = EmailFinder()
    mail, error = finder.get_mail(query=query, index=email_index, selection_index=selection_index)
    if error:
        return error

    attachments = mail.Attachments
    if attachments.Count == 0:
        return f"E-Mail '{mail.Subject}' hat keine Anhänge"

    if attachment_index >= attachments.Count:
        return f"Anhang-Index {attachment_index} außerhalb des Bereichs (max: {attachments.Count - 1})"

    att = attachments.Item(attachment_index + 1)

    # Zielverzeichnis bestimmen
    if save_path is None:
        save_path = tempfile.gettempdir()

    # Datei speichern
    full_path = os.path.join(save_path, att.FileName)
    att.SaveAsFile(full_path)

    return f"Anhang gespeichert: {full_path}"


@mcp.tool()
@outlook_tool
def outlook_read_pdf_attachment(
    attachment_index: int = 0,
    query: str = None,
    email_index: int = 0,
    selection_index: int = 1
) -> str:
    """Liest den Textinhalt eines PDF-Anhangs aus einer E-Mail.

    Ideal für Rechnungen, Bestellungen und andere PDF-Dokumente.

    Args:
        attachment_index: Index des PDF-Anhangs (0 = erster Anhang)
        query: Suchbegriff für E-Mail (None = markierte E-Mail)
        email_index: Index in den Suchergebnissen (0 = neueste)
        selection_index: Bei Mehrfachauswahl: welche E-Mail (1-basiert, Standard: 1)

    Returns:
        Textinhalt des PDFs
    """
    finder = EmailFinder()
    mail, error = finder.get_mail(query=query, index=email_index, selection_index=selection_index)
    if error:
        return error

    attachments = mail.Attachments
    if attachments.Count == 0:
        return f"E-Mail '{mail.Subject}' hat keine Anhänge"

    if attachment_index >= attachments.Count:
        return f"Anhang-Index {attachment_index} außerhalb des Bereichs"

    att = attachments.Item(attachment_index + 1)
    filename = att.FileName.lower()

    if not filename.endswith('.pdf'):
        return f"Anhang '{att.FileName}' ist kein PDF. Verwende get_email_attachments um alle Anhänge zu sehen."

    # In temp speichern
    temp_path = os.path.join(tempfile.gettempdir(), att.FileName)
    att.SaveAsFile(temp_path)

    # PDF lesen
    try:
        from pypdf import PdfReader
    except ImportError:
        return "Fehler: pypdf nicht installiert. Führe 'pip install pypdf' aus."

    reader = PdfReader(temp_path)
    text_parts = []

    for i, page in enumerate(reader.pages):
        page_text = page.extract_text()
        if page_text:
            text_parts.append(f"--- Seite {i+1} ---\n{page_text}")

    # Temp-Datei löschen
    try:
        os.remove(temp_path)
    except OSError:
        pass

    if not text_parts:
        return f"PDF '{att.FileName}' enthält keinen extrahierbaren Text (evtl. gescanntes Dokument)"

    return f"PDF-Inhalt von '{att.FileName}':\n\n" + "\n\n".join(text_parts)


@mcp.tool()
@outlook_tool
def outlook_get_email_attachments_by_id(entry_id: str) -> str:
    """Listet alle Anhänge einer E-Mail anhand der Entry-ID.

    Args:
        entry_id: Entry-ID der E-Mail (aus get_folder_emails, get_recent_emails, etc.)

    Returns:
        JSON mit Anhängen: [{"index": 0, "name": "file.pdf", "size_kb": 125}, ...]
    """
    try:
        namespace = get_namespace()
        mail = namespace.GetItemFromID(entry_id)

        attachments = mail.Attachments
        if attachments.Count == 0:
            return json.dumps([], ensure_ascii=False)

        result = []
        for i in range(1, attachments.Count + 1):
            att = attachments.Item(i)
            result.append({
                "index": i - 1,
                "name": att.FileName,
                "size_kb": round(att.Size / 1024, 1)
            })

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
@outlook_tool
def outlook_save_attachment_by_entry_id(
    entry_id: str,
    attachment_index: int = 0,
    save_path: str = None
) -> str:
    """Speichert einen Anhang einer E-Mail anhand der Entry-ID.

    Args:
        entry_id: Entry-ID der E-Mail (aus get_folder_emails, get_recent_emails, etc.)
        attachment_index: Index des Anhangs (0 = erster Anhang)
        save_path: Zielordner (None = temp-Verzeichnis)

    Returns:
        Vollständiger Pfad zur gespeicherten Datei
    """
    try:
        namespace = get_namespace()
        mail = namespace.GetItemFromID(entry_id)

        attachments = mail.Attachments
        if attachments.Count == 0:
            return f"Fehler: E-Mail '{mail.Subject}' hat keine Anhänge"

        if attachment_index >= attachments.Count:
            return f"Fehler: Anhang-Index {attachment_index} außerhalb des Bereichs (max: {attachments.Count - 1})"

        att = attachments.Item(attachment_index + 1)

        # Zielverzeichnis bestimmen
        if save_path is None:
            save_path = tempfile.gettempdir()

        # Ordner erstellen falls nicht vorhanden
        os.makedirs(save_path, exist_ok=True)

        # Datei speichern
        full_path = os.path.join(save_path, att.FileName)
        att.SaveAsFile(full_path)

        return f"Anhang gespeichert: {full_path}"

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_read_pdf_attachment_by_id(
    entry_id: str,
    attachment_index: int = 0
) -> str:
    """Liest den Textinhalt eines PDF-Anhangs anhand der Entry-ID.

    Ideal für Rechnungen in Workflows die mit entry_id arbeiten
    (get_recent_emails, get_folder_emails, etc.).

    Args:
        entry_id: Entry-ID der E-Mail (aus get_folder_emails, get_recent_emails, etc.)
        attachment_index: Index des PDF-Anhangs (0 = erster Anhang)

    Returns:
        Textinhalt des PDFs
    """
    try:
        namespace = get_namespace()
        mail = namespace.GetItemFromID(entry_id)

        attachments = mail.Attachments
        if attachments.Count == 0:
            return f"E-Mail '{mail.Subject}' hat keine Anhänge"

        if attachment_index >= attachments.Count:
            return f"Anhang-Index {attachment_index} außerhalb des Bereichs (max: {attachments.Count - 1})"

        att = attachments.Item(attachment_index + 1)
        filename = att.FileName.lower()

        if not filename.endswith('.pdf'):
            return f"Anhang '{att.FileName}' ist kein PDF. Verwende get_email_attachments_by_id um alle Anhänge zu sehen."

        # In temp speichern
        temp_path = os.path.join(tempfile.gettempdir(), att.FileName)
        att.SaveAsFile(temp_path)

        # PDF lesen
        try:
            from pypdf import PdfReader
        except ImportError:
            return "Fehler: pypdf nicht installiert. Führe 'pip install pypdf' aus."

        reader = PdfReader(temp_path)
        text_parts = []

        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(f"--- Seite {i+1} ---\n{page_text}")

        # Temp-Datei löschen
        try:
            os.remove(temp_path)
        except OSError:
            pass

        if not text_parts:
            return f"PDF '{att.FileName}' enthält keinen extrahierbaren Text (evtl. gescanntes Dokument)"

        return f"PDF-Inhalt von '{att.FileName}':\n\n" + "\n\n".join(text_parts)

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_save_email_as_pdf(
    entry_id: str,
    save_path: str = None,
    filename: str = None
) -> str:
    """Speichert eine E-Mail als PDF-Datei anhand der Entry-ID.

    Nutzt Word-Export für saubere PDF-Ausgabe mit Formatierung.

    Args:
        entry_id: Entry-ID der E-Mail (aus get_folder_emails, get_recent_emails, etc.)
        save_path: Zielordner (None = temp-Verzeichnis)
        filename: Dateiname ohne .pdf (None = aus Subject generieren)

    Returns:
        Vollständiger Pfad zur gespeicherten PDF-Datei
    """
    try:
        namespace = get_namespace()
        mail = namespace.GetItemFromID(entry_id)

        # Zielverzeichnis bestimmen
        if save_path is None:
            save_path = tempfile.gettempdir()

        # Ordner erstellen falls nicht vorhanden
        os.makedirs(save_path, exist_ok=True)

        # Dateiname generieren
        if filename is None:
            # Aus Subject einen sicheren Dateinamen machen
            subject = mail.Subject or "email"
            # Datum hinzufügen
            try:
                date_str = mail.ReceivedTime.strftime("%Y%m%d")
            except (AttributeError, ValueError):
                date_str = "00000000"
            # Ungültige Zeichen entfernen
            safe_subject = re.sub(r'[<>:"/\\|?*]', '', subject)[:50].strip()
            filename = f"{date_str}_{safe_subject}"

        full_path = os.path.join(save_path, f"{filename}.pdf")

        # Methode 1: Word-Export (beste Qualität)
        try:
            inspector = mail.GetInspector
            word_doc = inspector.WordEditor

            # PDF speichern (17 = wdFormatPDF)
            word_doc.SaveAs2(full_path, 17)

            # Inspector schließen ohne E-Mail zu speichern
            inspector.Close(1)  # 1 = olDiscard

            return f"E-Mail als PDF gespeichert: {full_path}"

        except Exception as word_error:
            # Methode 2: Als MSG speichern (Fallback)
            msg_path = os.path.join(save_path, f"{filename}.msg")
            mail.SaveAs(msg_path, 3)  # 3 = olMSG

            return f"E-Mail als MSG gespeichert (PDF-Export fehlgeschlagen): {msg_path}"

    except Exception as e:
        return f"Fehler: {str(e)}"
