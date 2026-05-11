# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
IMAP MCP - Attachments Module
==============================
Email attachment operations: list, download, read PDF.
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
import json
import email
from pathlib import Path
from imap.base import mcp, requires_imap, get_imap_connection
from _mcp_api import mcp_log


def _fetch_email_message(imap, uid, folder="INBOX"):
    """Fetch and parse a full email message by UID.

    Args:
        imap: IMAP connection
        uid: Message UID (str or bytes)
        folder: IMAP folder name

    Returns:
        email.message.Message object or None
    """
    status, _ = imap.select(folder, readonly=True)
    if status != 'OK':
        return None

    # Ensure uid is bytes for fetch
    if isinstance(uid, str):
        uid = uid.encode()

    status, msg_data = imap.fetch(uid, '(RFC822)')
    if status != 'OK' or not msg_data or not msg_data[0]:
        return None

    return email.message_from_bytes(msg_data[0][1])


def _get_attachment_parts(msg):
    """Extract attachment parts from an email message.

    Returns list of dicts with: index, filename, size, content_type, part (MIME part object)
    """
    attachments = []

    if not msg.is_multipart():
        return attachments

    for part in msg.walk():
        content_disposition = part.get_content_disposition()
        filename = part.get_filename()

        # Attachment = has filename or content-disposition is "attachment"
        if content_disposition == "attachment" or (filename and content_disposition != "inline"):
            payload = part.get_payload(decode=True)
            size = len(payload) if payload else 0

            attachments.append({
                "index": len(attachments),
                "filename": filename or f"attachment_{len(attachments)}",
                "content_type": part.get_content_type(),
                "size_bytes": size,
                "size_kb": round(size / 1024, 1),
                "_part": part,  # Internal: MIME part for download
            })

    return attachments


@mcp.tool()
@requires_imap
def imap_get_attachments(uid: str, folder: str = "INBOX") -> str:
    """List all attachments of an email.

    Args:
        uid: Message UID (from search results)
        folder: IMAP folder name (default: INBOX)

    Returns:
        JSON with attachment list (index, filename, size, content_type)

    Example:
        imap_get_attachments("123", "INBOX")
    """
    imap = get_imap_connection()

    try:
        msg = _fetch_email_message(imap, uid, folder)
        if not msg:
            return json.dumps({
                "error": f"Failed to fetch email UID {uid} from {folder}",
                "attachments": [],
                "count": 0
            }, indent=2)

        parts = _get_attachment_parts(msg)

        # Remove internal _part object from output
        attachments = []
        for p in parts:
            attachments.append({
                "index": p["index"],
                "filename": p["filename"],
                "content_type": p["content_type"],
                "size_bytes": p["size_bytes"],
                "size_kb": p["size_kb"],
            })

        return json.dumps({
            "uid": uid,
            "folder": folder,
            "attachments": attachments,
            "count": len(attachments)
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        mcp_log(f"[IMAP] Get attachments error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_download_attachment(
    uid: str,
    attachment_index: int = 0,
    folder: str = "INBOX",
    save_path: str = ""
) -> str:
    """Download an email attachment to disk.

    Args:
        uid: Message UID
        attachment_index: Attachment index (from imap_get_attachments, default: 0 = first)
        folder: IMAP folder name (default: INBOX)
        save_path: Directory to save to (default: .temp/)

    Returns:
        Path to downloaded file with size info

    Example:
        imap_download_attachment("123", 0, "INBOX", "/path/to/save")
    """
    imap = get_imap_connection()

    try:
        msg = _fetch_email_message(imap, uid, folder)
        if not msg:
            return f"Error: Failed to fetch email UID {uid} from {folder}"

        parts = _get_attachment_parts(msg)

        if not parts:
            return "Error: Email has no attachments"

        if attachment_index < 0 or attachment_index >= len(parts):
            return f"Error: Invalid attachment index {attachment_index}. Email has {len(parts)} attachment(s) (0-{len(parts)-1})"

        attachment = parts[attachment_index]
        part = attachment["_part"]
        filename = attachment["filename"]

        # Get file data
        file_data = part.get_payload(decode=True)
        if not file_data:
            return f"Error: No data in attachment '{filename}'"

        # Determine save path
        if not save_path:
            save_path = ".temp"

        save_dir = Path(save_path)
        save_dir.mkdir(parents=True, exist_ok=True)

        file_path = save_dir / filename

        # Handle duplicate filenames
        counter = 1
        original_stem = file_path.stem
        while file_path.exists():
            file_path = save_dir / f"{original_stem}_{counter}{file_path.suffix}"
            counter += 1

        # Write file
        file_path.write_bytes(file_data)

        mcp_log(f"[IMAP] Downloaded attachment '{filename}' ({len(file_data)} bytes) to {file_path}")

        return f"""Attachment downloaded successfully!

File: {file_path}
Size: {len(file_data):,} bytes ({round(len(file_data)/1024, 1)} KB)"""

    except Exception as e:
        mcp_log(f"[IMAP] Download attachment error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_read_pdf_attachment(
    uid: str,
    attachment_index: int = 0,
    folder: str = "INBOX"
) -> str:
    """Extract text from a PDF attachment without saving to disk.

    Useful for reading invoices, documents, etc. directly.

    Args:
        uid: Message UID
        attachment_index: Attachment index (from imap_get_attachments, default: 0 = first)
        folder: IMAP folder name (default: INBOX)

    Returns:
        Extracted text from PDF (page by page)

    Example:
        imap_read_pdf_attachment("123", 0, "INBOX")
    """
    imap = get_imap_connection()

    try:
        msg = _fetch_email_message(imap, uid, folder)
        if not msg:
            return f"Error: Failed to fetch email UID {uid} from {folder}"

        parts = _get_attachment_parts(msg)

        if not parts:
            return "Error: Email has no attachments"

        if attachment_index < 0 or attachment_index >= len(parts):
            return f"Error: Invalid attachment index {attachment_index}. Email has {len(parts)} attachment(s) (0-{len(parts)-1})"

        attachment = parts[attachment_index]
        part = attachment["_part"]
        filename = attachment["filename"]
        content_type = attachment["content_type"]

        # Check if it's a PDF
        if content_type != "application/pdf" and not filename.lower().endswith('.pdf'):
            return f"Error: Attachment '{filename}' is not a PDF (type: {content_type}). Use imap_download_attachment() instead."

        # Get file data
        pdf_data = part.get_payload(decode=True)
        if not pdf_data:
            return f"Error: No data in attachment '{filename}'"

        # Extract text using pypdf
        try:
            import io
            from pypdf import PdfReader

            pdf_file = io.BytesIO(pdf_data)
            reader = PdfReader(pdf_file)

            text_parts = []
            for page_num, page in enumerate(reader.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"--- Page {page_num} ---\n{page_text}")

            if text_parts:
                mcp_log(f"[IMAP] Read PDF attachment '{filename}' ({len(reader.pages)} pages)")
                return "\n\n".join(text_parts)
            else:
                return "PDF contains no extractable text (may be a scanned document)."

        except ImportError:
            return "Error: pypdf not installed. Run: pip install pypdf"

    except Exception as e:
        mcp_log(f"[IMAP] Read PDF attachment error: {e}")
        return f"Error: {str(e)}"
