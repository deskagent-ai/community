# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI Web UI Routes
=====================
Handles the main web UI, static files, themes, and icons.

UI building logic has been extracted to services/ui_builder.py
for better separation of concerns.
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from pydantic import BaseModel

# Path is set up by assistant/__init__.py
from paths import PROJECT_DIR, get_config_dir

# Import UI builder from services
from ..services.ui_builder import build_web_ui, build_preprompt_ui
from ..services.mcp_metadata import get_tool_metadata


def get_templates_dir() -> Path:
    """Get templates directory - evaluated at runtime to support --shared-dir reload."""
    import paths
    return paths.DESKAGENT_DIR / "scripts" / "templates"


router = APIRouter()


def needs_setup() -> bool:
    """Check if initial setup is needed (no API keys configured).

    Returns True if:
    - backends.json doesn't exist, OR
    - backends.json is empty or has no API keys AND setup_completed is False

    Note: Uses dynamic import to get fresh get_config_dir after --shared-dir reload.
    Also checks CLI override path if set.
    """
    import paths
    import json
    from config import _cli_config_overrides

    # Check CLI override path first
    if "backends.json" in _cli_config_overrides:
        backends_path = Path(_cli_config_overrides["backends.json"])
    else:
        backends_path = paths.get_config_dir() / "backends.json"

    if not backends_path.exists():
        return True

    # Check if file has any API keys configured
    try:
        config = json.loads(backends_path.read_text(encoding="utf-8"))
        if not config:
            return True  # Empty dict

        # Check if setup was completed (user explicitly skipped all keys)
        if config.get("setup_completed"):
            return False

        # Check for any api_key in any backend or SDK subscription
        ai_backends = config.get("ai_backends", config)  # Support both formats
        for backend in ai_backends.values():
            if isinstance(backend, dict):
                # Has API key OR is SDK subscription (no key needed)
                if backend.get("api_key") or backend.get("type") == "claude_agent_sdk":
                    return False
        return True  # No valid backends found
    except (json.JSONDecodeError, Exception):
        return True


def _save_branding_to_system_config(body: "SetupRequest") -> None:
    """Save branding fields from setup wizard to config/system.json.

    Merges with existing system.json content - does not overwrite other settings.
    Only writes if at least one branding field was provided.
    """
    import paths

    # Check if any branding data was provided
    has_branding = any([
        body.company_name.strip(),
        body.industry.strip(),
        body.assistant_intro.strip(),
        body.language != "de"  # Only save if non-default
    ])
    if not has_branding:
        return

    system_config_path = paths.get_config_dir() / "system.json"

    # Load existing system.json or start fresh
    existing = {}
    if system_config_path.exists():
        try:
            existing = json.loads(system_config_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    # Merge branding section
    branding = existing.get("branding", {})
    if body.company_name.strip():
        branding["company_name"] = body.company_name.strip()
    if body.industry.strip():
        branding["industry"] = body.industry.strip()
    if body.assistant_intro.strip():
        branding["assistant_intro"] = body.assistant_intro.strip()
    branding["language"] = body.language or "de"

    existing["branding"] = branding
    system_config_path.parent.mkdir(parents=True, exist_ok=True)
    system_config_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


# =============================================================================
# Setup Wizard
# =============================================================================

@router.get("/setup", response_class=HTMLResponse)
async def serve_setup():
    """Serves the initial setup wizard page."""
    setup_path = get_templates_dir() / "setup.html"
    if setup_path.exists():
        html = setup_path.read_text(encoding="utf-8")

        # Try to load existing keys from backends.json first, fallback to env vars
        anthropic_key = ""
        gemini_key = ""
        openai_key = ""

        try:
            from config import _cli_config_overrides
            if "backends.json" in _cli_config_overrides:
                backends_path = Path(_cli_config_overrides["backends.json"])
            else:
                backends_path = get_config_dir() / "backends.json"

            if backends_path.exists():
                backends = json.loads(backends_path.read_text(encoding="utf-8"))
                ai_backends = backends.get("ai_backends", {})

                # Get API keys from existing config
                if "claude_sdk" in ai_backends:
                    anthropic_key = ai_backends["claude_sdk"].get("api_key", "")
                if "gemini" in ai_backends:
                    gemini_key = ai_backends["gemini"].get("api_key", "")
                if "openai" in ai_backends:
                    openai_key = ai_backends["openai"].get("api_key", "")
        except Exception:
            pass  # Ignore errors, fall back to env vars

        # Environment variables override file config
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "") or anthropic_key
        gemini_key = os.environ.get("GEMINI_API_KEY", "") or gemini_key
        openai_key = os.environ.get("OPENAI_API_KEY", "") or openai_key

        html = html.replace("{{ANTHROPIC_API_KEY}}", anthropic_key)
        html = html.replace("{{GEMINI_API_KEY}}", gemini_key)
        html = html.replace("{{OPENAI_API_KEY}}", openai_key)

        # Branding variables from app config (XSS-safe)
        import html as html_lib
        from ..skills import load_config
        config = load_config()
        app_cfg = config.get("app", {})
        html = html.replace("{{BRANDING_LICENSE_URL}}", html_lib.escape(app_cfg.get("license_url", "")))
        html = html.replace("{{BRANDING_PRIVACY_URL}}", html_lib.escape(app_cfg.get("privacy_url", "")))
        html = html.replace("{{BRANDING_ORDER_URL}}", html_lib.escape(app_cfg.get("order_url", "")))

        return HTMLResponse(content=html)
    return HTMLResponse(content="<h1>Setup template not found</h1>", status_code=404)


class SetupRequest(BaseModel):
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    skip: bool = False
    # Branding fields (saved to system.json)
    company_name: str = ""
    industry: str = ""
    language: str = "de"
    assistant_intro: str = ""


@router.get("/api/setup/prefill")
async def get_setup_prefill():
    """Get prefill values for setup wizard (for sandbox testing).

    Reads from config/prefill-setup.json if it exists.
    This allows testing the wizard with pre-filled API keys.
    """
    import paths
    import json

    prefill_path = paths.get_config_dir() / "prefill-setup.json"
    if not prefill_path.exists():
        return {"prefill": False}

    try:
        data = json.loads(prefill_path.read_text(encoding="utf-8"))
        return {
            "prefill": True,
            "license_code": data.get("license_code", ""),
            "license_email": data.get("license_email", ""),
            "anthropic_api_key": data.get("anthropic_api_key", ""),
            "gemini_api_key": data.get("gemini_api_key", ""),
            "openai_api_key": data.get("openai_api_key", ""),
        }
    except Exception:
        return {"prefill": False}


@router.get("/api/setup/check-spacy")
async def check_spacy_models():
    """Check if spaCy models are installed."""
    try:
        import spacy
        available = []
        missing = []

        for model in ["de_core_news_lg", "en_core_web_sm"]:
            try:
                spacy.load(model)
                available.append(model)
            except OSError:
                missing.append(model)

        return {"available": available, "missing": missing}
    except ImportError:
        return {"available": [], "missing": ["de_core_news_lg", "en_core_web_sm"]}


@router.post("/api/setup/install-spacy")
async def install_spacy_models():
    """Download and install spaCy models."""
    import subprocess
    import sys
    from ai_agent import system_log
    from paths import get_embedded_python

    # Use embedded Python (works for both dev mode and Nuitka build)
    embedded_python = get_embedded_python()
    if embedded_python and embedded_python.exists():
        python = str(embedded_python)
    else:
        # Fallback to sys.executable (dev mode without embedded Python)
        python = sys.executable

    models = ["de_core_news_lg", "en_core_web_sm"]
    results = []

    system_log(f"[spacy] Installing models with Python: {python}")

    for model in models:
        try:
            system_log(f"[spacy] Downloading {model}...")
            # Build kwargs - need CREATE_NO_WINDOW for Windows GUI apps without console
            run_kwargs = {
                "capture_output": True,
                "text": True,
                "timeout": 600,
                "stdin": subprocess.DEVNULL
            }
            if sys.platform == "win32":
                run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                [python, "-m", "spacy", "download", model],
                **run_kwargs
            )
            if result.returncode == 0:
                system_log(f"[spacy] {model} installed successfully")
                results.append({"model": model, "success": True})
            else:
                error_msg = result.stderr.strip() or result.stdout.strip() or f"Exit code {result.returncode}"
                system_log(f"[spacy] {model} failed: {error_msg}")
                results.append({"model": model, "success": False, "error": error_msg[:200]})
        except subprocess.TimeoutExpired:
            system_log(f"[spacy] {model} timeout")
            results.append({"model": model, "success": False, "error": "Download timeout (10 min)"})
        except Exception as e:
            system_log(f"[spacy] {model} exception: {e}")
            results.append({"model": model, "success": False, "error": str(e)[:200]})

    return {"results": results}


@router.post("/api/setup")
async def handle_setup(body: SetupRequest):
    """Handle setup wizard form submission.

    Merges new settings with existing backends.json to preserve
    other backends (gemini_flash, mistral, etc.) and pricing info.
    """
    try:
        # Check for CLI override path first
        from config import _cli_config_overrides
        if "backends.json" in _cli_config_overrides:
            backends_path = Path(_cli_config_overrides["backends.json"])
            backends_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            config_dir = get_config_dir()
            config_dir.mkdir(parents=True, exist_ok=True)
            backends_path = config_dir / "backends.json"

        # Handle skip action - mark setup as completed even without keys
        if body.skip:
            if backends_path.exists():
                try:
                    config = json.loads(backends_path.read_text(encoding="utf-8"))
                except Exception:
                    config = {"ai_backends": {}}
            else:
                config = {"ai_backends": {}}
            config["setup_completed"] = True
            backends_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            return {"success": True}

        # Load existing config or start fresh
        if backends_path.exists():
            try:
                backends_config = json.loads(backends_path.read_text(encoding="utf-8"))
                if "ai_backends" not in backends_config:
                    backends_config["ai_backends"] = {}
            except Exception:
                backends_config = {"ai_backends": {}}
        else:
            backends_config = {"ai_backends": {}}

        # Claude - update only if API key provided
        anthropic_key = body.anthropic_api_key.strip()
        if anthropic_key:
            existing = backends_config["ai_backends"].get("claude_sdk", {})
            existing.update({
                "type": "claude_agent_sdk",
                "api_key": anthropic_key,
                "permission_mode": "bypassPermissions",
                "anonymize": True
            })
            backends_config["ai_backends"]["claude_sdk"] = existing

        # Gemini - update only if key provided
        gemini_key = body.gemini_api_key.strip()
        if gemini_key:
            existing = backends_config["ai_backends"].get("gemini", {})
            existing.update({
                "type": "gemini_adk",
                "api_key": gemini_key,
                "model": existing.get("model", "gemini-2.5-pro"),
                "anonymize": True
            })
            backends_config["ai_backends"]["gemini"] = existing
            if "default_ai" not in backends_config:
                backends_config["default_ai"] = "gemini"

        # OpenAI - update only if key provided
        openai_key = body.openai_api_key.strip()
        if openai_key:
            existing = backends_config["ai_backends"].get("openai", {})
            existing.update({
                "type": "openai_api",
                "api_key": openai_key,
                "model": existing.get("model", "gpt-4o"),
                "anonymize": True
            })
            backends_config["ai_backends"]["openai"] = existing

        # Mark setup as completed
        backends_config["setup_completed"] = True
        backends_path.write_text(json.dumps(backends_config, indent=2), encoding="utf-8")

        # Save branding fields to system.json (merge, don't overwrite)
        _save_branding_to_system_config(body)

        return {"success": True}

    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# Offline Support (Service Worker)
# =============================================================================

@router.get("/sw.js")
async def serve_service_worker():
    """Serve the service worker script from root path."""
    sw_path = get_templates_dir() / "sw.js"
    if sw_path.exists():
        return Response(
            content=sw_path.read_text(encoding="utf-8"),
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"}
        )
    return Response(status_code=404)


@router.get("/offline.html", response_class=HTMLResponse)
async def serve_offline_page():
    """Serve the offline loading page (shown when server is starting)."""
    offline_path = get_templates_dir() / "offline.html"
    if offline_path.exists():
        return HTMLResponse(content=offline_path.read_text(encoding="utf-8"))
    # Fallback minimal HTML
    return HTMLResponse(content="""<!DOCTYPE html><html><head>
<meta charset="UTF-8"><title>DeskAgent</title>
<style>body{font-family:system-ui;display:flex;align-items:center;justify-content:center;
min-height:100vh;margin:0}div{text-align:center}</style></head>
<body><div><h2>DeskAgent</h2><p>Connecting...</p>
<script>setInterval(()=>fetch('/status').then(r=>r.ok&&location.reload()),1000)</script>
</div></body></html>""")


# =============================================================================
# Main UI
# =============================================================================

@router.get("/", response_class=HTMLResponse)
async def serve_web_ui(preprompt: str = None):
    """Serves the main tile-based web UI or Pre-Prompt overlay.

    Args:
        preprompt: Optional agent name. If provided, serves minimal Pre-Prompt UI
                   for the Quick Access mode context input window.
    """
    # Pre-Prompt mode: minimal UI for context input
    if preprompt:
        html = build_preprompt_ui(preprompt)
        return HTMLResponse(content=html)

    # Redirect to setup if no config exists
    if needs_setup():
        return RedirectResponse(url="/setup", status_code=302)
    html = build_web_ui()
    return HTMLResponse(content=html)


# =============================================================================
# Static Files
# =============================================================================

@router.get("/icon.ico")
@router.get("/icon.png")
async def serve_icon(path: str = "icon.ico"):
    """Serve application icon."""
    # Check deskagent/ first, then project root
    import paths
    for file in ["icon.ico", "icon.png"]:
        icon_path = paths.DESKAGENT_DIR / file
        if not icon_path.exists():
            icon_path = PROJECT_DIR / file
        if icon_path.exists() and file in path:
            return FileResponse(
                path=icon_path,
                media_type="image/x-icon" if file.endswith(".ico") else "image/png",
                headers={"Cache-Control": "max-age=3600"}
            )
    return Response(status_code=404)


@router.get("/static/icons/{icon_name:path}")
async def serve_static_icon(icon_name: str):
    """Serve static icons."""
    icon_path = get_templates_dir() / "icons" / icon_name
    if icon_path.exists() and icon_path.is_file():
        ext = icon_path.suffix.lower()
        content_types = {
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".jpg": "image/jpeg",
            ".ico": "image/x-icon"
        }
        content_type = content_types.get(ext, "application/octet-stream")
        return FileResponse(
            path=icon_path,
            media_type=content_type,
            headers={"Cache-Control": "max-age=3600"}
        )
    return Response(status_code=404)


@router.get("/styles/main.css")
async def serve_unified_styles():
    """Serve unified theme CSS file with data-theme support.

    The unified styles.css contains both light and dark theme variables
    that are activated via data-theme attribute on the <html> element.
    """
    css_path = get_templates_dir() / "themes" / "styles.css"
    if css_path.exists():
        return FileResponse(
            path=css_path,
            media_type="text/css; charset=utf-8",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    return Response(status_code=404)


@router.get("/static/js/{js_name:path}")
async def serve_javascript(js_name: str):
    """Serve JavaScript modules."""
    js_path = get_templates_dir() / "js" / js_name
    if js_path.exists() and js_path.is_file():
        return FileResponse(
            path=js_path,
            media_type="application/javascript; charset=utf-8",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    return Response(status_code=404)


@router.get("/static/css/{css_name:path}")
async def serve_css(css_name: str):
    """Serve CSS stylesheets."""
    css_path = get_templates_dir() / "css" / css_name
    if css_path.exists() and css_path.is_file():
        return FileResponse(
            path=css_path,
            media_type="text/css; charset=utf-8",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    return Response(status_code=404)


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/api/tool-metadata")
async def tool_metadata():
    """Return tool metadata (icons, colors) for all loaded MCP servers.

    Used by WebUI to dynamically style tool call badges.
    """
    return get_tool_metadata()


@router.post("/quickaccess/toggle")
async def toggle_quickaccess():
    """Toggle Quick Access overlay window from browser.

    Opens the Quick Access pywebview window if available,
    otherwise returns instructions to use the hotkey.
    """
    try:
        from .. import quickaccess
        from ..state import get_active_port
        from ..skills import load_config

        if not quickaccess.is_available():
            return {
                "success": False,
                "error": "pywebview not installed",
                "message": "Quick Access requires pywebview. Use Alt+Q hotkey instead."
            }

        config = load_config()
        port = get_active_port()
        ui_config = config.get("ui", {})
        category = ui_config.get("quickaccess_category", "pinned")

        opened = quickaccess.toggle_window(port, category=category)
        return {"success": True, "opened": opened}

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/preprompt/open")
async def open_preprompt_window(agent: str):
    """Open Pre-Prompt overlay window for adding context before running an agent.

    Used in Quick Access mode where the main window is too small for dialogs.
    Opens a separate pywebview window with a context input form.

    Args:
        agent: Name of the agent to run after context input
    """
    try:
        from .. import quickaccess
        from ..state import get_active_port

        if not quickaccess.is_available():
            return {
                "success": False,
                "error": "pywebview not installed",
                "message": "Pre-Prompt window requires pywebview."
            }

        port = get_active_port()
        quickaccess.create_preprompt_window(port, agent)
        return {"success": True}

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/preprompt/close")
async def close_preprompt_window():
    """Close the Pre-Prompt overlay window if open."""
    try:
        from .. import quickaccess
        quickaccess.close_preprompt_window()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
