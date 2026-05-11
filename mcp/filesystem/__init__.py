#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Filesystem MCP Server
=====================
MCP server for generic file system operations.

Security:
- Configure read/write restrictions in system.json under "filesystem"
- Without config: all paths allowed (backward-compatible)

Config example:
    "filesystem": {
        "read": ["E:/workspace/**", "E:/data/config.json"],
        "write": ["E:/workspace/.temp/**"]
    }

Syntax:
- "path/**" - folder + all subfolders
- "path/*" - only direct children
- "path/file.txt" - single file

Tools:
- fs_read_file - Read text file content
- fs_read_pdf - Read PDF text content
- fs_read_pdfs_batch - Read multiple PDFs in one call
- fs_write_file - Write/create text file
- fs_list_directory - List files/folders in directory
- fs_list_all_files - List files recursively with glob patterns
- fs_file_exists - Check if file/folder exists
- fs_get_file_info - Get file metadata
- fs_copy_file - Copy a file to another location
- fs_delete_file - Delete a file
"""

import fnmatch
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config, mcp_log

# Initialize FastMCP server
mcp = FastMCP("filesystem")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "folder",
    "color": "#ffc107"
}

# Integration schema for Settings UI
INTEGRATION_SCHEMA = {
    "name": "Dateisystem",
    "icon": "folder",
    "color": "#ffc107",
    "config_key": None,  # Keine Config noetig
    "auth_type": "none",
}

# Destructive tools that modify, create, or delete data
# These will be simulated in dry-run mode instead of executed
DESTRUCTIVE_TOOLS = {
    "fs_write_file",
    "fs_copy_file",
    "fs_delete_file",
}


# =============================================================================
# Path Security
# =============================================================================

def _check_access(path: str, mode: str) -> tuple[bool, str]:
    """Check if path is allowed for read/write access.

    Args:
        path: Absolute file path to check
        mode: "read" or "write"

    Returns:
        (allowed: bool, error_message: str)
    """
    config = load_config()
    fs_config = config.get("filesystem", {})

    # Get allowed patterns for this mode
    allowed_patterns = fs_config.get(mode)

    # No restrictions configured = allow all (backward-compatible)
    if not allowed_patterns:
        return True, ""

    # Normalize path for comparison
    check_path = str(Path(path).resolve()).replace("\\", "/")

    for pattern in allowed_patterns:
        # Normalize pattern
        norm_pattern = str(Path(pattern).resolve()).replace("\\", "/") if not pattern.endswith("**") and not pattern.endswith("*") else pattern.replace("\\", "/")

        # Handle ** (recursive) patterns
        if pattern.endswith("/**"):
            base_path = norm_pattern[:-3]  # Remove /**
            base_path = str(Path(base_path).resolve()).replace("\\", "/")
            if check_path.startswith(base_path + "/") or check_path == base_path:
                return True, ""

        # Handle * (single level) patterns
        elif pattern.endswith("/*"):
            base_path = norm_pattern[:-2]  # Remove /*
            base_path = str(Path(base_path).resolve()).replace("\\", "/")
            # Check if path is direct child
            if check_path.startswith(base_path + "/"):
                remaining = check_path[len(base_path)+1:]
                if "/" not in remaining:  # No further subdirs
                    return True, ""

        # Exact file/path match
        else:
            full_pattern = str(Path(pattern).resolve()).replace("\\", "/")
            if check_path == full_pattern:
                return True, ""

    return False, f"Access denied: {mode} not allowed for {path}"


def _require_read(path: str) -> str | None:
    """Check read access, return error message or None if allowed."""
    allowed, error = _check_access(path, "read")
    return None if allowed else error


def _require_write(path: str) -> str | None:
    """Check write access, return error message or None if allowed."""
    allowed, error = _check_access(path, "write")
    return None if allowed else error

# Tools that return external/untrusted content (prompt injection risk)
# These will be wrapped with sanitization by the anonymization proxy
HIGH_RISK_TOOLS = {
    "fs_read_file",
    "fs_read_pdf",
    "fs_read_pdfs_batch",
}

# Read-only tools that only retrieve data without modifications
# Used by tool_mode: "read_only" to allow only safe operations
READ_ONLY_TOOLS = {
    "fs_read_file",
    "fs_read_pdf",
    "fs_read_pdfs_batch",
    "fs_list_directory",
    "fs_list_all_files",
    "fs_file_exists",
    "fs_get_file_info",
}


def is_configured() -> bool:
    """Prüft ob Filesystem-Zugriff verfügbar ist.

    Filesystem ist lokal verfügbar.
    Kann über filesystem.enabled deaktiviert werden.
    """
    config = load_config()
    mcp_config = config.get("filesystem", {})

    if mcp_config.get("enabled") is False:
        return False

    return True


# Limits
MAX_READ_SIZE = 10 * 1024 * 1024  # 10 MB


@mcp.tool()
def fs_read_file(path: str, encoding: str = "utf-8") -> str:
    """Read text file content.

    Args:
        path: Absolute file path
        encoding: Text encoding (default: utf-8)

    Returns:
        File content or error message
    """
    # Security check
    if error := _require_read(path):
        return error

    try:
        p = Path(path)

        if not p.exists():
            return f"Error: File not found: {path}"

        if not p.is_file():
            return f"Error: Not a file: {path}"

        size = p.stat().st_size
        if size > MAX_READ_SIZE:
            return f"Error: File too large ({size // 1024 // 1024}MB > {MAX_READ_SIZE // 1024 // 1024}MB limit)"

        content = p.read_text(encoding=encoding)
        lines = content.count('\n') + 1
        mcp_log(f"[File] READ {path} ({lines} lines, {size} bytes)")
        return content

    except UnicodeDecodeError:
        return f"Error: Cannot decode file as {encoding}. Try a different encoding or use read_pdf for PDF files."
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error reading file: {e}"


@mcp.tool()
def fs_read_pdf(path: str) -> str:
    """Read text content from a PDF file.

    Args:
        path: Absolute path to PDF file

    Returns:
        Extracted text content or error message
    """
    # Security check
    if error := _require_read(path):
        return error

    try:
        p = Path(path)

        if not p.exists():
            return f"Error: File not found: {path}"

        if not p.is_file():
            return f"Error: Not a file: {path}"

        if not p.suffix.lower() == '.pdf':
            return f"Error: Not a PDF file: {path}"

        size = p.stat().st_size
        if size > MAX_READ_SIZE:
            return f"Error: File too large ({size // 1024 // 1024}MB > {MAX_READ_SIZE // 1024 // 1024}MB limit)"

        # Read PDF
        try:
            from pypdf import PdfReader
        except ImportError:
            return "Error: pypdf not installed. Run 'pip install pypdf'"

        reader = PdfReader(str(p))
        text_parts = []

        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(f"--- Seite {i+1} ---\n{page_text}")

        if not text_parts:
            return "Error: Could not extract text from PDF (possibly scanned/image-based)"

        mcp_log(f"[File] READ PDF {path} ({len(reader.pages)} pages, {size} bytes)")
        return "\n\n".join(text_parts)

    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error reading PDF: {e}"


@mcp.tool()
def fs_read_pdfs_batch(paths: list[str]) -> str:
    """Read multiple PDF files in a single call. More efficient than calling fs_read_pdf multiple times.

    Args:
        paths: List of absolute paths to PDF files

    Returns:
        Combined text content from all PDFs, with file markers
    """
    if not paths:
        return "Error: No paths provided"

    if len(paths) > 50:
        return f"Error: Too many files ({len(paths)}). Maximum is 50 files per batch."

    # Security check all paths first
    for path in paths:
        if error := _require_read(path):
            return error

    try:
        from pypdf import PdfReader
    except ImportError:
        return "Error: pypdf not installed. Run 'pip install pypdf'"

    results = []
    success_count = 0
    error_count = 0

    for path in paths:
        try:
            p = Path(path)

            if not p.exists():
                results.append(f"=== {p.name} ===\nError: File not found")
                error_count += 1
                continue

            if not p.is_file():
                results.append(f"=== {p.name} ===\nError: Not a file")
                error_count += 1
                continue

            if not p.suffix.lower() == '.pdf':
                results.append(f"=== {p.name} ===\nError: Not a PDF file")
                error_count += 1
                continue

            size = p.stat().st_size
            if size > MAX_READ_SIZE:
                results.append(f"=== {p.name} ===\nError: File too large ({size // 1024 // 1024}MB)")
                error_count += 1
                continue

            # Read PDF
            reader = PdfReader(str(p))
            text_parts = []

            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

            if text_parts:
                content = "\n".join(text_parts)
                results.append(f"=== {p.name} ===\n{content}")
                success_count += 1
            else:
                results.append(f"=== {p.name} ===\nError: No text extracted (possibly scanned/image)")
                error_count += 1

        except Exception as e:
            results.append(f"=== {Path(path).name} ===\nError: {e}")
            error_count += 1

    # Add summary at the top
    summary = f"Batch PDF Read: {success_count} successful, {error_count} failed, {len(paths)} total\n"
    summary += "=" * 60 + "\n\n"

    mcp_log(f"[File] READ PDF BATCH {success_count}/{len(paths)} files successful")
    return summary + "\n\n".join(results)


@mcp.tool()
def fs_write_file(path: str, content: str, encoding: str = "utf-8") -> str:
    """Write content to file. Creates parent directories if needed.

    Args:
        path: Absolute file path
        content: File content to write
        encoding: Text encoding (default: utf-8)

    Returns:
        Success message or error
    """
    # Security check
    if error := _require_write(path):
        return error

    try:
        p = Path(path)

        # Create parent directories
        p.parent.mkdir(parents=True, exist_ok=True)

        existed = p.exists()
        p.write_text(content, encoding=encoding)

        size = len(content.encode(encoding))
        lines = content.count('\n') + 1
        action = "Updated" if existed else "Created"
        mcp_log(f"[File] WRITE {path} ({lines} lines, {size} bytes) [{action.upper()}]")
        return f"{action}: {path} ({size} bytes)"

    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error writing file: {e}"


@mcp.tool()
def fs_list_directory(path: str, pattern: str = "*") -> str:
    """List contents of a directory.

    Args:
        path: Absolute directory path
        pattern: Glob pattern to filter files (default: "*" for all)

    Returns:
        Formatted list of files/folders or error
    """
    # Security check
    if error := _require_read(path):
        return error

    try:
        p = Path(path)

        if not p.exists():
            return f"Error: Directory not found: {path}"

        if not p.is_dir():
            return f"Error: Not a directory: {path}"

        items = []
        for item in sorted(p.glob(pattern)):
            if item.is_dir():
                items.append(f"[DIR]  {item.name}/")
            else:
                size = item.stat().st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size // 1024} KB"
                else:
                    size_str = f"{size // 1024 // 1024} MB"
                items.append(f"[FILE] {item.name} ({size_str})")

        if not items:
            return f"(empty directory or no matches for pattern '{pattern}')"

        return "\n".join(items)

    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error listing directory: {e}"


@mcp.tool()
def fs_list_all_files(path: str, pattern: str = "**/*", include_dirs: bool = False) -> str:
    """List all files recursively in a directory.

    Args:
        path: Absolute directory path
        pattern: Glob pattern (default: "**/*" for all files recursively)
                 Examples: "**/*.md", "**/*.pdf", "**/knowledge/**"
        include_dirs: Include directories in output (default: False)

    Returns:
        Formatted list of files with relative paths
    """
    # Security check
    if error := _require_read(path):
        return error

    try:
        p = Path(path)

        if not p.exists():
            return f"Error: Directory not found: {path}"

        if not p.is_dir():
            return f"Error: Not a directory: {path}"

        items = []
        for item in sorted(p.glob(pattern)):
            # Get relative path from base
            rel_path = item.relative_to(p)

            if item.is_dir():
                if include_dirs:
                    items.append(f"[DIR]  {rel_path}/")
            else:
                size = item.stat().st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size // 1024} KB"
                else:
                    size_str = f"{size // 1024 // 1024} MB"
                items.append(f"[FILE] {rel_path} ({size_str})")

        if not items:
            return f"(no files found matching pattern '{pattern}')"

        mcp_log(f"[File] LIST_ALL {path} pattern={pattern} -> {len(items)} items")
        return f"Found {len(items)} files in {path}:\n\n" + "\n".join(items)

    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error listing directory: {e}"


@mcp.tool()
def fs_file_exists(path: str) -> str:
    """Check if file or directory exists.

    Args:
        path: Absolute path to check

    Returns:
        Status message (exists/not found)
    """
    p = Path(path)

    if p.exists():
        file_type = "directory" if p.is_dir() else "file"
        return f"exists ({file_type})"

    return "not found"


@mcp.tool()
def fs_get_file_info(path: str) -> str:
    """Get file metadata (size, modified date, type).

    Args:
        path: Absolute file/directory path

    Returns:
        Formatted metadata or error
    """
    try:
        p = Path(path)

        if not p.exists():
            return f"Error: Not found: {path}"

        stat = p.stat()
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        created = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")

        if p.is_dir():
            # Count items in directory
            item_count = len(list(p.iterdir()))
            return f"""Path: {p.absolute()}
Type: directory
Items: {item_count}
Created: {created}
Modified: {modified}"""
        else:
            size = stat.st_size
            if size < 1024:
                size_str = f"{size} bytes"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / 1024 / 1024:.1f} MB"

            return f"""Path: {p.absolute()}
Type: file
Size: {size_str}
Extension: {p.suffix or '(none)'}
Created: {created}
Modified: {modified}"""

    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error getting file info: {e}"


@mcp.tool()
def fs_copy_file(source: str, destination: str) -> str:
    """Copy a file to another location.

    Args:
        source: Source file path
        destination: Destination path (file or directory)

    Returns:
        Success message or error
    """
    # Security checks
    if error := _require_read(source):
        return error
    if error := _require_write(destination):
        return error

    try:
        import shutil

        src = Path(source)
        dst = Path(destination)

        if not src.exists():
            return f"Error: Source not found: {source}"

        if not src.is_file():
            return f"Error: Source is not a file: {source}"

        # If destination is a directory, use source filename
        if dst.is_dir():
            dst = dst / src.name

        # Create parent directories
        dst.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(src, dst)
        size = dst.stat().st_size

        mcp_log(f"[File] COPY {source} -> {dst} ({size} bytes)")
        return f"Copied: {source} -> {dst} ({size} bytes)"

    except PermissionError:
        return f"Error: Permission denied"
    except Exception as e:
        return f"Error copying file: {e}"


@mcp.tool()
def fs_delete_file(path: str) -> str:
    """Delete a file. Does NOT delete directories (for safety).

    Args:
        path: File path to delete

    Returns:
        Success message or error
    """
    # Security check (delete requires write permission)
    if error := _require_write(path):
        return error

    try:
        p = Path(path)

        if not p.exists():
            return f"Error: File not found: {path}"

        if p.is_dir():
            return f"Error: Cannot delete directory (safety restriction): {path}"

        size = p.stat().st_size
        p.unlink()

        mcp_log(f"[File] DELETE {path} ({size} bytes)")
        return f"Deleted: {path} ({size} bytes)"

    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error deleting file: {e}"


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    mcp_log("[Filesystem MCP] Starting server...")
    mcp.run()
