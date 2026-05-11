# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""File upload handling for DeskAgent.

Extracted from routes/execution.py to separate upload logic from HTTP routes.
"""

from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from ..core import TEMP_UPLOADS_DIR
from ai_agent import log


async def save_uploaded_files(form: Any) -> Dict[str, Any]:
    """Save uploaded files from a multipart form to temp directory.

    Args:
        form: FastAPI form data from request.form()

    Returns:
        Dict with 'paths' (list of absolute paths) and 'count'
    """
    # Create temp directory
    TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    saved_paths: List[str] = []

    for field_name in form:
        upload_file = form[field_name]
        if hasattr(upload_file, 'filename') and upload_file.filename:
            # Sanitize filename - only keep the basename
            filename = Path(upload_file.filename).name

            # Add timestamp to avoid conflicts
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_filename = f"{timestamp}_{filename}"
            file_path = TEMP_UPLOADS_DIR / safe_filename

            # Read and save file
            content = await upload_file.read()
            file_path.write_bytes(content)

            saved_paths.append(str(file_path.absolute()))
            log(f"[Upload] Saved: {file_path} ({len(content)} bytes)")

    return {"paths": saved_paths, "count": len(saved_paths)}
