# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Gmail MCP - Attachments Module
==============================
Email attachment operations: list, download, read PDF.
"""

import json
import base64
import os
from pathlib import Path

from gmail.base import (
    mcp, gmail_tool, require_auth,
    get_gmail_service, get_header, system_log
)


@mcp.tool()
@gmail_tool
@require_auth
def gmail_get_attachments(message_id: str) -> str:
    """List all attachments of an email.

    Args:
        message_id: Message ID

    Returns:
        JSON list of attachments with index, name, size, and mimeType
    """
    service = get_gmail_service()

    msg = service.users().messages().get(
        userId='me',
        id=message_id,
        format='full'
    ).execute()

    attachments = []
    payload = msg.get("payload", {})

    def find_attachments(parts, index_prefix=""):
        """Recursively find attachments in message parts."""
        nonlocal attachments

        for i, part in enumerate(parts):
            filename = part.get("filename", "")
            mime_type = part.get("mimeType", "")
            body = part.get("body", {})
            attachment_id = body.get("attachmentId", "")
            size = body.get("size", 0)

            if filename and attachment_id:
                attachments.append({
                    "index": len(attachments),
                    "filename": filename,
                    "mimeType": mime_type,
                    "size_bytes": size,
                    "size_kb": round(size / 1024, 1),
                    "attachment_id": attachment_id,
                    "part_path": f"{index_prefix}{i}" if index_prefix else str(i)
                })

            # Check nested parts
            if "parts" in part:
                find_attachments(part["parts"], f"{index_prefix}{i}.")

    # Start from payload parts
    if "parts" in payload:
        find_attachments(payload["parts"])

    if not attachments:
        return json.dumps({
            "message_id": message_id,
            "attachments": [],
            "count": 0
        }, indent=2)

    return json.dumps({
        "message_id": message_id,
        "attachments": attachments,
        "count": len(attachments)
    }, ensure_ascii=False, indent=2)


@mcp.tool()
@gmail_tool
@require_auth
def gmail_download_attachment(
    message_id: str,
    attachment_id: str,
    save_path: str = ""
) -> str:
    """Download an email attachment.

    Args:
        message_id: Message ID
        attachment_id: Attachment ID (from gmail_get_attachments)
        save_path: Directory to save to (default: .temp/)

    Returns:
        Path to downloaded file
    """
    service = get_gmail_service()

    # Get attachment data
    attachment = service.users().messages().attachments().get(
        userId='me',
        messageId=message_id,
        id=attachment_id
    ).execute()

    data = attachment.get("data", "")
    if not data:
        return "ERROR: No attachment data received."

    # Decode base64url
    file_data = base64.urlsafe_b64decode(data)

    # Get filename from message
    msg = service.users().messages().get(
        userId='me',
        id=message_id,
        format='full'
    ).execute()

    filename = _find_attachment_filename(msg.get("payload", {}), attachment_id)
    if not filename:
        filename = f"attachment_{attachment_id[:8]}"

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

    return f"""Attachment downloaded successfully!

File: {file_path}
Size: {len(file_data):,} bytes ({round(len(file_data)/1024, 1)} KB)"""


@mcp.tool()
@gmail_tool
@require_auth
def gmail_read_pdf_attachment(
    message_id: str,
    attachment_id: str
) -> str:
    """Extract text from a PDF attachment without saving to disk.

    Useful for reading invoices, documents, etc. directly.

    Args:
        message_id: Message ID
        attachment_id: Attachment ID (from gmail_get_attachments)

    Returns:
        Extracted text from PDF
    """
    service = get_gmail_service()

    # Get attachment data
    attachment = service.users().messages().attachments().get(
        userId='me',
        messageId=message_id,
        id=attachment_id
    ).execute()

    data = attachment.get("data", "")
    if not data:
        return "ERROR: No attachment data received."

    # Decode base64url
    pdf_data = base64.urlsafe_b64decode(data)

    # Try to extract text using pypdf
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
            return "\n\n".join(text_parts)
        else:
            return "PDF contains no extractable text (may be a scanned document)."

    except ImportError:
        return "ERROR: pypdf not installed. Run: pip install pypdf"
    except Exception as e:
        return f"ERROR: Could not extract PDF text: {e}"


@mcp.tool()
@gmail_tool
@require_auth
def gmail_download_all_attachments(
    message_id: str,
    save_path: str = ""
) -> str:
    """Download all attachments from an email.

    Args:
        message_id: Message ID
        save_path: Directory to save to (default: .temp/)

    Returns:
        Summary of downloaded files
    """
    service = get_gmail_service()

    # Get message with full payload
    msg = service.users().messages().get(
        userId='me',
        id=message_id,
        format='full'
    ).execute()

    # Determine save path
    if not save_path:
        save_path = ".temp"

    save_dir = Path(save_path)
    save_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    errors = []

    def process_parts(parts):
        """Recursively process message parts for attachments."""
        for part in parts:
            filename = part.get("filename", "")
            body = part.get("body", {})
            attachment_id = body.get("attachmentId", "")

            if filename and attachment_id:
                try:
                    # Get attachment data
                    att = service.users().messages().attachments().get(
                        userId='me',
                        messageId=message_id,
                        id=attachment_id
                    ).execute()

                    data = att.get("data", "")
                    if data:
                        file_data = base64.urlsafe_b64decode(data)

                        file_path = save_dir / filename

                        # Handle duplicates
                        counter = 1
                        original_stem = file_path.stem
                        while file_path.exists():
                            file_path = save_dir / f"{original_stem}_{counter}{file_path.suffix}"
                            counter += 1

                        file_path.write_bytes(file_data)
                        downloaded.append({
                            "filename": filename,
                            "path": str(file_path),
                            "size_kb": round(len(file_data) / 1024, 1)
                        })
                except Exception as e:
                    errors.append({"filename": filename, "error": str(e)})

            # Process nested parts
            if "parts" in part:
                process_parts(part["parts"])

    # Start processing
    payload = msg.get("payload", {})
    if "parts" in payload:
        process_parts(payload["parts"])

    # Format result
    result = {
        "message_id": message_id,
        "save_directory": str(save_dir),
        "downloaded": downloaded,
        "errors": errors,
        "total_downloaded": len(downloaded),
        "total_errors": len(errors)
    }

    return json.dumps(result, ensure_ascii=False, indent=2)


# =============================================================================
# Helper Functions
# =============================================================================

def _find_attachment_filename(payload: dict, attachment_id: str) -> str:
    """Find filename for an attachment ID in message payload."""

    def search_parts(parts):
        for part in parts:
            body = part.get("body", {})
            if body.get("attachmentId") == attachment_id:
                return part.get("filename", "")

            if "parts" in part:
                result = search_parts(part["parts"])
                if result:
                    return result
        return ""

    if "parts" in payload:
        return search_parts(payload["parts"])

    return ""
