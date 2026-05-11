#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
PDF MCP Server
==============
MCP server for PDF document operations.

Tools:
- pdf_get_info - Get PDF metadata (pages, size, etc.)
- pdf_extract_pages - Extract specific pages to a new PDF
- pdf_merge - Merge multiple PDFs into one
- pdf_split - Split PDF into single-page files
- pdf_render_page - Render PDF page as image (for OCR via Vision LLM)
- pdf_render_pages - Render multiple pages as images
- pdf_get_page_size - Get page dimensions in points
"""

import base64
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config, mcp_log

# Initialize FastMCP server
mcp = FastMCP("pdf")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "picture_as_pdf",
    "color": "#f44336"
}

# Integration schema for Settings UI
INTEGRATION_SCHEMA = {
    "name": "PDF",
    "icon": "picture_as_pdf",
    "color": "#f44336",
    "config_key": None,  # Keine Config noetig
    "auth_type": "none",
}

# No high-risk tools - PDF operations don't return untrusted content
HIGH_RISK_TOOLS = set()

# Read-only tools that only retrieve data (for tool_mode: "read_only")
READ_ONLY_TOOLS = {
    "pdf_get_info",
    "pdf_get_page_size",
    "pdf_render_page",
    "pdf_render_pages",
}

# Destructive tools that create/modify files
DESTRUCTIVE_TOOLS = {
    "pdf_extract_pages",
    "pdf_merge",
    "pdf_split",
}


def is_configured() -> bool:
    """Prüft ob PDF-Verarbeitung verfügbar ist.

    PDF ist lokal verfügbar.
    Kann über pdf.enabled deaktiviert werden.
    """
    config = load_config()
    mcp_config = config.get("pdf", {})

    if mcp_config.get("enabled") is False:
        return False

    return True


# Limits
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


def _parse_page_ranges(page_spec: str, total_pages: int) -> list[int]:
    """Parse page specification into list of 0-indexed page numbers.

    Supports:
    - Single pages: "1", "5"
    - Ranges: "1-5", "10-15"
    - Mixed: "1,3,5-10,15"
    - Negative (from end): "-1" (last), "-3" (third from end)

    Args:
        page_spec: Page specification string (1-indexed for user convenience)
        total_pages: Total number of pages in the PDF

    Returns:
        List of 0-indexed page numbers
    """
    pages = []

    for part in page_spec.split(","):
        part = part.strip()
        if not part:
            continue

        if "-" in part and not part.startswith("-"):
            # Range: "1-5"
            try:
                start, end = part.split("-", 1)
                start_idx = int(start) - 1  # Convert to 0-indexed
                end_idx = int(end) - 1

                if start_idx < 0:
                    start_idx = 0
                if end_idx >= total_pages:
                    end_idx = total_pages - 1

                pages.extend(range(start_idx, end_idx + 1))
            except ValueError:
                continue
        else:
            # Single page (including negative)
            try:
                page_num = int(part)
                if page_num < 0:
                    # Negative index: -1 = last page
                    page_idx = total_pages + page_num
                else:
                    # Positive: 1-indexed to 0-indexed
                    page_idx = page_num - 1

                if 0 <= page_idx < total_pages:
                    pages.append(page_idx)
            except ValueError:
                continue

    # Remove duplicates while preserving order
    seen = set()
    unique_pages = []
    for p in pages:
        if p not in seen:
            seen.add(p)
            unique_pages.append(p)

    return unique_pages


@mcp.tool()
def pdf_get_info(path: str) -> str:
    """Get PDF metadata and information.

    Args:
        path: Absolute path to PDF file

    Returns:
        PDF information (pages, size, metadata)
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return "Error: pypdf not installed. Run 'pip install pypdf'"

    try:
        p = Path(path)

        if not p.exists():
            return f"Error: File not found: {path}"

        if not p.is_file():
            return f"Error: Not a file: {path}"

        if p.suffix.lower() != ".pdf":
            return f"Error: Not a PDF file: {path}"

        size = p.stat().st_size
        if size > MAX_FILE_SIZE:
            return f"Error: File too large ({size // 1024 // 1024}MB > {MAX_FILE_SIZE // 1024 // 1024}MB limit)"

        reader = PdfReader(str(p))
        num_pages = len(reader.pages)

        # Format file size
        if size < 1024:
            size_str = f"{size} bytes"
        elif size < 1024 * 1024:
            size_str = f"{size / 1024:.1f} KB"
        else:
            size_str = f"{size / 1024 / 1024:.1f} MB"

        # Get metadata
        meta = reader.metadata
        info_parts = [
            f"File: {p.name}",
            f"Path: {p.absolute()}",
            f"Pages: {num_pages}",
            f"Size: {size_str}",
        ]

        if meta:
            if meta.title:
                info_parts.append(f"Title: {meta.title}")
            if meta.author:
                info_parts.append(f"Author: {meta.author}")
            if meta.creator:
                info_parts.append(f"Creator: {meta.creator}")
            if meta.creation_date:
                info_parts.append(f"Created: {meta.creation_date}")

        return "\n".join(info_parts)

    except Exception as e:
        return f"Error reading PDF: {e}"


@mcp.tool()
def pdf_extract_pages(
    source: str,
    pages: str,
    output: str = ""
) -> str:
    """Extract specific pages from a PDF to a new file.

    Args:
        source: Path to source PDF file
        pages: Pages to extract. Supports:
               - Single pages: "1", "5"
               - Ranges: "1-5", "10-15"
               - Mixed: "1,3,5-10,15"
               - From end: "-1" (last page), "-2" (second to last)
        output: Output file path. If empty, creates "<source>_extracted.pdf"

    Returns:
        Success message with output path or error
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return "Error: pypdf not installed. Run 'pip install pypdf'"

    try:
        src = Path(source)

        if not src.exists():
            return f"Error: Source file not found: {source}"

        if not src.is_file():
            return f"Error: Not a file: {source}"

        if src.suffix.lower() != ".pdf":
            return f"Error: Not a PDF file: {source}"

        size = src.stat().st_size
        if size > MAX_FILE_SIZE:
            return f"Error: File too large ({size // 1024 // 1024}MB)"

        # Read source PDF
        reader = PdfReader(str(src))
        total_pages = len(reader.pages)

        # Parse page specification
        page_indices = _parse_page_ranges(pages, total_pages)

        if not page_indices:
            return f"Error: No valid pages in specification '{pages}'. PDF has {total_pages} pages."

        # Determine output path
        if output:
            out_path = Path(output)
        else:
            out_path = src.parent / f"{src.stem}_extracted.pdf"

        # Ensure .pdf extension
        if out_path.suffix.lower() != ".pdf":
            out_path = out_path.with_suffix(".pdf")

        # Create parent directories
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Extract pages
        writer = PdfWriter()
        for idx in page_indices:
            writer.add_page(reader.pages[idx])

        # Write output
        with open(out_path, "wb") as f:
            writer.write(f)

        out_size = out_path.stat().st_size
        if out_size < 1024:
            size_str = f"{out_size} bytes"
        elif out_size < 1024 * 1024:
            size_str = f"{out_size / 1024:.1f} KB"
        else:
            size_str = f"{out_size / 1024 / 1024:.1f} MB"

        # Format extracted pages for display (1-indexed)
        extracted_display = [str(i + 1) for i in page_indices]

        return f"Extracted {len(page_indices)} pages ({', '.join(extracted_display)}) from {total_pages} total\nOutput: {out_path} ({size_str})"

    except Exception as e:
        return f"Error extracting pages: {e}"


@mcp.tool()
def pdf_merge(
    files: list[str],
    output: str
) -> str:
    """Merge multiple PDF files into one.

    Args:
        files: List of PDF file paths to merge (in order)
        output: Output file path

    Returns:
        Success message or error
    """
    try:
        from pypdf import PdfWriter
    except ImportError:
        return "Error: pypdf not installed. Run 'pip install pypdf'"

    if not files:
        return "Error: No files provided"

    if len(files) < 2:
        return "Error: Need at least 2 files to merge"

    try:
        out_path = Path(output)
        if out_path.suffix.lower() != ".pdf":
            out_path = out_path.with_suffix(".pdf")

        writer = PdfWriter()
        total_pages = 0

        for file_path in files:
            p = Path(file_path)

            if not p.exists():
                return f"Error: File not found: {file_path}"

            if p.suffix.lower() != ".pdf":
                return f"Error: Not a PDF file: {file_path}"

            size = p.stat().st_size
            if size > MAX_FILE_SIZE:
                return f"Error: File too large: {file_path}"

            writer.append(str(p))
            total_pages += len(writer.pages) - total_pages

        # Create parent directories
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "wb") as f:
            writer.write(f)

        out_size = out_path.stat().st_size
        if out_size < 1024 * 1024:
            size_str = f"{out_size / 1024:.1f} KB"
        else:
            size_str = f"{out_size / 1024 / 1024:.1f} MB"

        return f"Merged {len(files)} files ({total_pages} pages total)\nOutput: {out_path} ({size_str})"

    except Exception as e:
        return f"Error merging PDFs: {e}"


@mcp.tool()
def pdf_split(
    source: str,
    output_dir: str = ""
) -> str:
    """Split a PDF into individual single-page files.

    Args:
        source: Path to source PDF file
        output_dir: Output directory. If empty, uses source file's directory

    Returns:
        Success message with list of created files or error
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return "Error: pypdf not installed. Run 'pip install pypdf'"

    try:
        src = Path(source)

        if not src.exists():
            return f"Error: Source file not found: {source}"

        if src.suffix.lower() != ".pdf":
            return f"Error: Not a PDF file: {source}"

        size = src.stat().st_size
        if size > MAX_FILE_SIZE:
            return f"Error: File too large ({size // 1024 // 1024}MB)"

        reader = PdfReader(str(src))
        total_pages = len(reader.pages)

        if total_pages == 0:
            return "Error: PDF has no pages"

        # Determine output directory
        if output_dir:
            out_dir = Path(output_dir)
        else:
            out_dir = src.parent

        out_dir.mkdir(parents=True, exist_ok=True)

        created_files = []
        base_name = src.stem

        for i, page in enumerate(reader.pages):
            writer = PdfWriter()
            writer.add_page(page)

            # Create filename with zero-padded page number
            page_num = str(i + 1).zfill(len(str(total_pages)))
            out_file = out_dir / f"{base_name}_page{page_num}.pdf"

            with open(out_file, "wb") as f:
                writer.write(f)

            created_files.append(out_file.name)

        return f"Split into {total_pages} files in: {out_dir}\nFiles: {', '.join(created_files)}"

    except Exception as e:
        return f"Error splitting PDF: {e}"


@mcp.tool()
def pdf_render_page(
    path: str,
    page: int = 1,
    dpi: int = 150
) -> str:
    """Render a PDF page as image for Vision LLM processing (OCR for scanned documents).

    Use this when text extraction fails (scanned PDFs). The image is returned
    in a special format that Vision LLMs (Gemini, Claude) can process directly.

    Args:
        path: Path to PDF file
        page: Page number (1-indexed, default: 1)
        dpi: Resolution (default: 150, higher = better quality but larger)

    Returns:
        Image data in format: [IMAGE:image/png:base64data]
        Or error message if rendering fails
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return "Error: pypdfium2 not installed. Run 'pip install pypdfium2'"

    try:
        p = Path(path)

        if not p.exists():
            return f"Error: File not found: {path}"

        if p.suffix.lower() != ".pdf":
            return f"Error: Not a PDF file: {path}"

        size = p.stat().st_size
        if size > MAX_FILE_SIZE:
            return f"Error: File too large ({size // 1024 // 1024}MB)"

        # Open PDF
        doc = pdfium.PdfDocument(str(p))
        total_pages = len(doc)

        if total_pages == 0:
            return "Error: PDF has no pages"

        # Convert 1-indexed to 0-indexed
        page_idx = page - 1
        if page_idx < 0 or page_idx >= total_pages:
            return f"Error: Page {page} out of range (PDF has {total_pages} pages)"

        # Render page to image
        pdf_page = doc[page_idx]
        scale = dpi / 72  # Convert DPI to scale factor (72 is base DPI)
        bitmap = pdf_page.render(scale=scale)
        pil_image = bitmap.to_pil()

        # Convert to PNG bytes
        import io
        buffer = io.BytesIO()
        pil_image.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()

        # Encode as base64
        b64_data = base64.b64encode(png_bytes).decode("ascii")

        # Return in special format for Vision LLM detection
        # Format: [IMAGE:mime_type:base64data]
        size_kb = len(png_bytes) / 1024
        mcp_log(f"[PDF MCP] Rendered page {page}/{total_pages} at {dpi}dpi ({size_kb:.1f} KB)")

        return f"[IMAGE:image/png:{b64_data}]"

    except Exception as e:
        return f"Error rendering PDF page: {e}"


@mcp.tool()
def pdf_render_pages(
    path: str,
    pages: str = "1",
    dpi: int = 150
) -> str:
    """Render multiple PDF pages as images for Vision LLM processing.

    Use this for multi-page scanned documents. Returns multiple images
    that Vision LLMs can process.

    Args:
        path: Path to PDF file
        pages: Page specification (e.g., "1", "1-3", "1,3,5")
        dpi: Resolution (default: 150)

    Returns:
        Multiple [IMAGE:...] blocks, one per page
        Or error message if rendering fails
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return "Error: pypdfium2 not installed. Run 'pip install pypdfium2'"

    try:
        import io
        p = Path(path)

        if not p.exists():
            return f"Error: File not found: {path}"

        if p.suffix.lower() != ".pdf":
            return f"Error: Not a PDF file: {path}"

        # Open PDF
        doc = pdfium.PdfDocument(str(p))
        total_pages = len(doc)

        if total_pages == 0:
            return "Error: PDF has no pages"

        # Parse page specification
        page_indices = _parse_page_ranges(pages, total_pages)

        if not page_indices:
            return f"Error: No valid pages in '{pages}'. PDF has {total_pages} pages."

        # Limit to prevent huge responses
        if len(page_indices) > 10:
            return f"Error: Too many pages ({len(page_indices)}). Maximum 10 pages per call."

        results = []
        total_size = 0
        scale = dpi / 72  # Convert DPI to scale factor

        for idx in page_indices:
            pdf_page = doc[idx]
            bitmap = pdf_page.render(scale=scale)
            pil_image = bitmap.to_pil()

            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG")
            png_bytes = buffer.getvalue()

            b64_data = base64.b64encode(png_bytes).decode("ascii")
            total_size += len(png_bytes)

            results.append(f"--- Page {idx + 1} ---\n[IMAGE:image/png:{b64_data}]")

        mcp_log(f"[PDF MCP] Rendered {len(page_indices)} pages at {dpi}dpi ({total_size / 1024:.1f} KB total)")

        return "\n\n".join(results)

    except Exception as e:
        return f"Error rendering PDF pages: {e}"


@mcp.tool()
def pdf_get_page_size(path: str, page: int = 1) -> str:
    """Get the size of a PDF page in points.

    72 points = 1 inch.
    Common sizes: A4 = 595x842, Letter = 612x792

    Args:
        path: Path to PDF file
        page: Page number (1-indexed, default: 1)

    Returns:
        Page dimensions (width x height in points)
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return "Error: pypdfium2 not installed. Run 'pip install pypdfium2'"

    try:
        p = Path(path)

        if not p.exists():
            return f"Error: File not found: {path}"

        if p.suffix.lower() != ".pdf":
            return f"Error: Not a PDF file: {path}"

        doc = pdfium.PdfDocument(str(p))
        total_pages = len(doc)

        if total_pages == 0:
            return "Error: PDF has no pages"

        page_idx = page - 1
        if page_idx < 0 or page_idx >= total_pages:
            return f"Error: Page {page} out of range (PDF has {total_pages} pages)"

        pdf_page = doc[page_idx]
        width = pdf_page.get_width()
        height = pdf_page.get_height()

        return f"Page {page}: {width:.1f} x {height:.1f} points ({width/72:.2f} x {height/72:.2f} inches)"

    except Exception as e:
        return f"Error getting page size: {e}"


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    mcp_log("[PDF MCP] Starting server...")
    mcp.run()
