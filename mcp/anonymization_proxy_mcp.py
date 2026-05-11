#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Dynamic Anonymization Proxy MCP Server
=======================================
Dynamisch ladender Proxy-Server der alle MCP-Tool-Aufrufe abfaengt.
Laedt automatisch alle MCP-Packages (Subfolders mit __init__.py) und wrapped deren Tools.

Architektur:
    Claude Agent SDK
           | (tool call)
    Anonymization Proxy MCP  <- Hier wird anonymisiert
           | (forwards)
    Real MCP Servers (automatisch geladen)
           | (result)
    Anonymization Proxy MCP  <- Response anonymisieren
           | (anonymized result)
    Claude Agent SDK

API-basiert (Nuitka-kompatibel):
    - Anonymisierung via HTTP API (/api/mcp/anonymize, /api/mcp/deanonymize)
    - Logging via HTTP API (/api/mcp/log, /api/mcp/log_tool_call)
    - Config via HTTP API (/api/mcp/config)

Transport Modes:
    - stdio: Direct subprocess (--session flag, no --transport)
    - sse/http: HTTP server (--transport sse/streamable-http)
"""

import asyncio
import base64
import importlib
import inspect
import ipaddress
import json
import os
import re
import sys
import uuid
from functools import wraps
from pathlib import Path
from typing import get_type_hints

from mcp.server.fastmcp import FastMCP, Context

# Project paths (Parent-Folder-Suche)
# MCP-Datei liegt in: deskagent/mcp/
DESKAGENT_DIR = Path(__file__).parent.parent  # deskagent/
MCP_DIR = DESKAGENT_DIR / "mcp"

# Add MCP_DIR to path so _mcp_api can be imported
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))


def _is_stdio_mode() -> bool:
    """Detect if running as stdio subprocess (no --transport flag).

    stdio mode is used when started with --session flag but no --transport.
    HTTP mode is used when --transport sse or --transport streamable-http is passed.
    """
    return "--transport" not in sys.argv


if _is_stdio_mode():
    # === STDIO MODE: Direkte Python-Imports ===
    # Used when proxy runs as subprocess of Claude SDK (no HTTP server)
    sys.path.insert(0, str(DESKAGENT_DIR / "scripts"))
    from paths import load_config as _load_config, get_logs_dir
    from ai_agent.anonymizer import (
        AnonymizationContext,
        anonymize_with_context as _anonymize,
        deanonymize as _deanonymize,
        is_available as _is_available
    )
    from ai_agent.base import system_log as _log, log_tool_call as _log_tool

    # Wrapper for unified API (matches _mcp_api interface)
    def load_config():
        return _load_config()

    def mcp_log(msg):
        _log(msg)

    def anonymize(text, session_id):
        # stdio mode (Claude Desktop): no anonymization needed.
        # Claude IS the LLM - anonymizing tool results would hide
        # the real data Claude needs to work with.
        return text

    def deanonymize(text, session_id):
        # stdio mode: no anonymization context available, return text as-is.
        # Anonymization makes no sense in Claude Desktop anyway -
        # Claude IS the LLM and needs real data, not placeholders.
        return text

    def is_anonymizer_available():
        return _is_available()

    def log_tool_call(name, args, result, is_anonymized=False):
        _log_tool(name, args, result, 0)

    def cleanup_session(session_id):
        pass  # Not needed for stdio (subprocess ends with agent)

    def get_task_context():
        return {}  # No shared context in stdio mode

else:
    # === HTTP MODE: API-basierte Imports (Nuitka-kompatibel) ===
    from _mcp_api import (
        load_config,
        mcp_log,
        get_logs_dir,
        anonymize,
        deanonymize,
        is_anonymizer_available,
        cleanup_session,
        get_task_context,
        log_tool_call,
    )


# ===== Input Sanitizer (inline) =====
# Prompt injection protection patterns

INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|above)",
    r"system\s*prompt",
    r"new\s+instructions?",
    r"override\s+(previous|all)",
    r"disregard\s+(previous|all|above)",
    r"forget\s+(previous|all|above)",
    r"you\s+are\s+now",
    r"act\s+as\s+if",
    r"pretend\s+(to\s+be|you're|you\s+are)",
    r"respond\s+as\s+if",
    r"</?(system|user|assistant)>",
    r"\[INST\]|\[/INST\]",
    r"<\|im_start\|>|<\|im_end\|>",
]


def wrap_untrusted_content(text: str, source_type: str = "external", source_info: str = "", sanitize: bool = True) -> str:
    """Wrap external content with clear delimiters.

    Args:
        text: Content to wrap
        source_type: Type of source (e.g., "email", "pdf", "ticket")
        source_info: Additional info (e.g., tool name)
        sanitize: Whether to sanitize the content

    Returns:
        Wrapped content with delimiters
    """
    if sanitize:
        text = sanitize_for_json(text)

    # Escape delimiters in content to prevent delimiter injection
    text = text.replace("--- END UNTRUSTED CONTENT ---", "[ESCAPED: END DELIMITER]")
    text = text.replace("--- BEGIN UNTRUSTED CONTENT", "[ESCAPED: BEGIN DELIMITER]")

    source_line = f" (source: {source_type}"
    if source_info:
        source_line += f"/{source_info}"
    source_line += ")"

    return f"--- BEGIN UNTRUSTED CONTENT{source_line} ---\n{text}\n--- END UNTRUSTED CONTENT ---"


def detect_injection_attempts(text: str) -> list:
    """Detect potential injection patterns.

    Args:
        text: Text to analyze

    Returns:
        List of matched pattern strings
    """
    matches = []
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            matches.append(pattern)
    return matches


def sanitize_for_json(text: str) -> str:
    """Sanitize text for safe JSON encoding.

    Args:
        text: Text to sanitize

    Returns:
        Sanitized text with control characters removed
    """
    if not isinstance(text, str):
        return str(text)
    # Remove control characters except newline and tab
    return "".join(c for c in text if c >= " " or c in "\n\t")


# ===== End Input Sanitizer =====


# Fallback list for MCPs that don't declare their own HIGH_RISK_TOOLS
# Each MCP can define: HIGH_RISK_TOOLS = {"tool1", "tool2"} to override
_FALLBACK_HIGH_RISK_TOOLS = {
    "get_selected_email", "get_selected_emails", "get_email_content",
    "read_pdf_attachment", "read_file", "read_pdf", "get_clipboard",
}

# Internal helper functions that should NOT be registered as tools
# These are common utility functions in MCP modules with docstrings
_INTERNAL_HELPERS = {
    # Config/setup functions
    "is_configured", "get_config", "api_request", "load_config",
    "get_api_key", "get_credentials", "init", "setup", "cleanup",
    "get_client", "get_session", "get_connection", "get_token",
    # OAuth flow functions
    "start_auth_flow", "complete_auth_flow", "refresh_token",
    "get_auth_url", "exchange_code", "validate_token",
    # FastMCP internals
    "run", "main", "serve",
}

# Track registered tool names to prevent duplicates
_registered_tool_names = set()

# Initialize FastMCP server
# NOTE: stateless_http=True is required for SSE/streamable-http transport
# Without it, FastMCP tries to manage sessions but Claude SDK expects stateless mode
_DESKAGENT_INSTRUCTIONS = """DeskAgent is a local AI desktop assistant providing business productivity tools via MCP.

Available tool categories: Email (Outlook, Gmail, IMAP/SMTP), Calendar, Invoicing (Billomat, Lexware, sevDesk),
Documents (ecoDMS, Paperless-ngx), Filesystem, PDF, Excel, Browser automation, Clipboard, Database/Datastore,
SEPA transfers, LinkedIn, Instagram, Telegram, Teams, SAP, and system management.

## Available Workflows

When the user asks for one of these tasks, use the corresponding MCP tools to execute the workflow.
Read the matching MCP prompt (via prompts/get) for detailed step-by-step instructions.

### Email & Communication
- **Daily Check** (daily_check): Täglicher Überblick - Termine, offene Angebote, Rechnungen, Tickets
- **Reply Email**: Flagged E-Mails professionell beantworten (outlook/graph tools)
- **New Mail** (new_mail): Neue E-Mail basierend auf Kontext erstellen
- **Check Open Items** (check_open_items): E-Mails der letzten 7 Tage auf offene Punkte prüfen
- **Find Emails** (find_emails_by_sender): E-Mails von bestimmtem Absender suchen
- **Cleanup Newsletters** (cleanup_newsletters): Newsletter aus Mailboxen in ToDelete sortieren
- **Check Support** (check_support): UserEcho auf unbeantwortete Support-Tickets prüfen
- **Claude Support** (claude_support): Kundenanfragen mit Claude Code beantworten
- **Customer Support** (customer_support): Eingehende Support-Anfragen beantworten

### Finance & Invoicing
- **Create Invoice from Email** (create_invoice_from_email): Rechnung aus E-Mail/PDF erstellen (inkl. Kundenanlage)
- **Create Invoice from Timelog** (create_invoice_from_timelog): Rechnung aus Zeiteinträgen erstellen
- **Export Invoices** (export_invoices): Rechnungen eines Zeitraums als PDF exportieren
- **Check Payments** (check_payments): Zahlungseingänge mit offenen Rechnungen abgleichen
- **Check CC Invoices** (check_cc_invoices): Kreditkartenabrechnungen gegen Paperless-Rechnungen abgleichen
- **Bank Statement Match** (kontoauszug_rechnung_abgleich): Kontoauszüge mit Eingangsrechnungen abgleichen
- **Create Transfer** (create_transfer): Überweisungsformular im Online-Banking ausfüllen
- **Extract Invoice Amounts** (extract_invoice_amounts): Beträge aus Eingangsrechnungen extrahieren
- **Payroll Extract** (extract_gehaltsabrechnung): Gehaltsabrechnungen aus PDFs extrahieren

### Documents & DMS
- **Archive to DMS** (archive_invoices_to_dms): Rechnungs-E-Mails aus DoneInvoices ins DMS archivieren
- **Paperless Auto-Tag** (paperless_auto_tag): Paperless-Dokumente analysieren und Tags zuweisen
- **Paperless Export** (paperless_export_steuerberater): Dokumente für Steuerberater exportieren
- **Search DMS** (search_dms_documents): Volltextsuche in ecoDMS & Paperless
- **List DMS Documents** (list_ecodms_documents): Neueste Dokumente aus ecoDMS listen

### Projects & Reporting
- **SAP Query** (ask_sap): Fragen zu SAP-Daten mit optionaler Visualisierung
- **Process Order** (process_order): DeskAgent-Bestellungen verarbeiten

Tips:
- Tools are prefixed by their MCP server (outlook_, graph_, billomat_, fs_, pdf_, etc.)
- Use proxy_reset_context at the start of a new task to reset anonymization
- Read knowledge resources for company info, products, and email style guidelines
"""

mcp = FastMCP("anonymization-proxy", instructions=_DESKAGENT_INSTRUCTIONS, stateless_http=True)

# Session ID for anonymization (set at startup)
_session_id: str = None

# Loaded modules cache
_loaded_modules = {}

# =============================================================================
# Per-Request Tool Filtering (integrated from mcp_filter_proxy.py)
# =============================================================================
# This replaces the separate Filter Proxy layer - filtering now happens directly
# in FastMCP via query parameters.

import threading
import time as _time

_session_filters: dict[str, str] = {}  # session_id -> filter_pattern
_session_filters_lock = threading.Lock()
_session_last_access: dict[str, float] = {}  # session_id -> timestamp
_SESSION_TTL_SECONDS = 3600  # 1 hour TTL for stale sessions


def register_session_filter(session_id: str, filter_pattern: str) -> None:
    """Register or update MCP filter for a session."""
    with _session_filters_lock:
        old_filter = _session_filters.get(session_id)
        if old_filter != filter_pattern:
            _session_filters[session_id] = filter_pattern
            _session_last_access[session_id] = _time.time()
            mcp_log(f"[Filter] Session {session_id}: filter={filter_pattern}")
        else:
            _session_last_access[session_id] = _time.time()


def get_session_filter(session_id: str) -> str | None:
    """Get filter pattern for a session."""
    with _session_filters_lock:
        if session_id in _session_filters:
            _session_last_access[session_id] = _time.time()
        return _session_filters.get(session_id)


def clear_session_filter(session_id: str) -> None:
    """Remove filter for a session (called when agent ends)."""
    with _session_filters_lock:
        _session_filters.pop(session_id, None)
        _session_last_access.pop(session_id, None)
        mcp_log(f"[Filter] Session {session_id}: cleared")


def _filter_tools_in_response(session_id: str, response_body: bytes) -> bytes:
    """Filter tools/list response based on session filter.

    Handles SSE format from FastMCP (stateless_http=True).
    """
    filter_pattern = get_session_filter(session_id)
    if not filter_pattern:
        return response_body  # No filter -> return unchanged

    try:
        text = response_body.decode("utf-8").strip()
    except UnicodeDecodeError:
        return response_body

    # Parse SSE format: event: message\ndata: {...}
    is_sse = text.startswith("event:") or "\ndata:" in text
    sse_event = None
    data = None

    if is_sse:
        # Extract event type and data
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("event:"):
                sse_event = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    pass
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return response_body

    if not data or "result" not in data or "tools" not in data.get("result", {}):
        return response_body

    # Compile filter regex
    try:
        filter_re = re.compile(filter_pattern, re.IGNORECASE)
    except re.error as e:
        mcp_log(f"[Filter] Invalid regex '{filter_pattern}': {e}")
        return response_body

    result = data["result"]
    original_count = len(result["tools"])

    # Filter tools by MCP name (first part before "_")
    # prefix mapping: graph -> msgraph, teams -> msgraph
    prefix_to_mcp = {"graph": "msgraph", "teams": "msgraph"}
    filtered_tools = []

    for tool in result["tools"]:
        tool_name = tool.get("name", "")
        mcp_name = tool_name.split("_")[0] if "_" in tool_name else tool_name
        mcp_name = prefix_to_mcp.get(mcp_name, mcp_name)

        # Always allow proxy system tools
        if mcp_name == "proxy" or filter_re.search(mcp_name):
            filtered_tools.append(tool)

    result["tools"] = filtered_tools
    filtered_count = len(filtered_tools)

    mcp_log(f"[Filter] Session {session_id}: {filtered_count}/{original_count} tools (filter: {filter_pattern})")

    # Rebuild response
    if is_sse:
        lines = []
        if sse_event:
            lines.append(f"event: {sse_event}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")
        return "\n".join(lines).encode("utf-8")
    else:
        return json.dumps(data).encode("utf-8")


class ToolFilterMiddleware:
    """ASGI Middleware for per-request tool filtering and auth.

    Reads session_id and filter from query parameters,
    stores filter per session, and filters tools/list responses.
    Validates Bearer token auth when configured.
    Serves /health endpoint without auth.
    """

    def __init__(self, app):
        self.app = app
        self._auth_token: str | None = None
        self._version: str = ""
        self._auth_initialized = False
        self._load_version()

    def _load_version(self):
        """Load version from version.json (once at startup)."""
        try:
            version_file = DESKAGENT_DIR / "version.json"
            if version_file.exists():
                import json as _json
                data = _json.loads(version_file.read_text(encoding="utf-8"))
                self._version = data.get("version", "unknown")
        except Exception:
            self._version = "unknown"

    def _load_auth_token(self):
        """Load auth token from config (lazy, cached after first call)."""
        if self._auth_initialized:
            return
        self._auth_initialized = True
        try:
            config = load_config()
            token = config.get("claude_desktop", {}).get("auth_token", "")
            self._auth_token = token if token else None
            if self._auth_token:
                mcp_log("[Auth] Bearer token auth enabled")
        except Exception as e:
            mcp_log(f"[Auth] Failed to load auth token: {e}")
            self._auth_token = None

    def _get_request_path(self, scope) -> str:
        """Extract path from ASGI scope."""
        return scope.get("path", "")

    def _get_auth_header(self, scope) -> str | None:
        """Extract Authorization header from ASGI scope."""
        headers = scope.get("headers", [])
        for name, value in headers:
            if name.lower() == b"authorization":
                return value.decode("utf-8")
        return None

    async def _send_json_response(self, send, status: int, body: dict):
        """Send a JSON response."""
        body_bytes = json.dumps(body).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body_bytes)).encode()),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body_bytes,
            "more_body": False,
        })

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_path = self._get_request_path(scope)
        request_method = scope.get("method", "GET")

        # === Health-Check Endpoint (no auth required) ===
        if request_path == "/health" and request_method == "GET":
            await self._send_json_response(send, 200, {
                "status": "ok",
                "version": self._version,
            })
            return

        # === Auth-Token Validation (optional, skip for localhost clients) ===
        self._load_auth_token()
        if self._auth_token:
            auth_header = self._get_auth_header(scope)
            # Allow requests without auth from localhost (Claude Desktop has no header support)
            client = scope.get("client", ("", 0))
            client_host = client[0] if client else ""
            is_localhost = client_host in ("127.0.0.1", "::1", "localhost", "")
            if not is_localhost:
                expected = f"Bearer {self._auth_token}"
                if auth_header != expected:
                    mcp_log(f"[Auth] Unauthorized request to {request_path} from {client_host}")
                    # Consume the request body to avoid ASGI protocol errors
                    while True:
                        message = await receive()
                        if message["type"] == "http.request":
                            if not message.get("more_body", False):
                                break
                        elif message["type"] == "http.disconnect":
                            return
                    await self._send_json_response(send, 401, {
                        "error": "Unauthorized",
                        "message": "Invalid or missing Bearer token",
                    })
                    return

        # Extract query params from scope
        query_string = scope.get("query_string", b"").decode("utf-8")
        params = {}
        for param in query_string.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)
                # URL decode
                import urllib.parse
                params[key] = urllib.parse.unquote(value)

        session_id = params.get("session", "default")
        filter_pattern = params.get("filter")

        # Register filter for this session
        if filter_pattern:
            register_session_filter(session_id, filter_pattern)

        # Track if this is a tools/list request by reading the body
        body_chunks = []
        is_tools_list = False

        async def receive_wrapper():
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                body_chunks.append(body)
                # Quick check for tools/list
                if b'"tools/list"' in body:
                    nonlocal is_tools_list
                    is_tools_list = True
            return message

        # Capture response for filtering
        response_body = []
        response_started = False
        response_headers = []
        response_status = 200

        async def send_wrapper(message):
            nonlocal response_started, response_status
            if message["type"] == "http.response.start":
                response_started = True
                response_status = message.get("status", 200)
                response_headers.extend(message.get("headers", []))
                # Don't send yet - wait for body
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                response_body.append(body)
                more_body = message.get("more_body", False)

                if not more_body:
                    # All body received - filter if needed
                    full_body = b"".join(response_body)

                    if is_tools_list and get_session_filter(session_id):
                        full_body = _filter_tools_in_response(session_id, full_body)

                    # Update content-length header
                    new_headers = []
                    for name, value in response_headers:
                        if name.lower() != b"content-length":
                            new_headers.append((name, value))
                    new_headers.append((b"content-length", str(len(full_body)).encode()))

                    # Send start
                    await send({
                        "type": "http.response.start",
                        "status": response_status,
                        "headers": new_headers,
                    })
                    # Send body
                    await send({
                        "type": "http.response.body",
                        "body": full_body,
                        "more_body": False,
                    })
            else:
                await send(message)

        await self.app(scope, receive_wrapper, send_wrapper)


def _is_demo_mode_enabled(config: dict) -> bool:
    """Check if demo mode is enabled in config.

    Args:
        config: Config dict

    Returns:
        True if demo mode is enabled
    """
    return config.get("demo_mode", {}).get("enabled", False)


def _get_mock_response(tool_name: str, args: dict, config: dict) -> str | None:
    """Get mock response for a tool in demo mode.

    Args:
        tool_name: Name of the tool
        args: Tool arguments
        config: Config dict

    Returns:
        Mock response string or None if not configured
    """
    demo_config = config.get("demo_mode", {})
    mock_responses = demo_config.get("mock_responses", {})
    return mock_responses.get(tool_name)


def _apply_mock_delay(tool_name: str, config: dict) -> None:
    """Apply simulated delay for demo mode.

    Args:
        tool_name: Name of the tool
        config: Config dict
    """
    import time
    demo_config = config.get("demo_mode", {})
    delay = demo_config.get("delay_ms", 0) / 1000.0
    if delay > 0:
        time.sleep(delay)


def anonymize_result(result: str) -> str:
    """Anonymize a tool result string via API.

    Args:
        result: Tool result to anonymize

    Returns:
        Anonymized result string
    """
    if not is_anonymizer_available():
        return result

    if not isinstance(result, str):
        return result

    # Skip error responses
    if result.startswith("Fehler:") or result.startswith("Error:"):
        return result

    config = load_config()
    anon_config = config.get("anonymization", {})

    if not anon_config.get("enabled", False):
        return result

    # Anonymize via API (session-based)
    anonymized = anonymize(result, _session_id)

    return anonymized


def deanonymize_args(args: dict) -> dict:
    """De-anonymize all string arguments via API.

    Args:
        args: Dict of arguments with potential placeholders

    Returns:
        Dict with placeholders replaced by original values
    """
    result = {}
    for key, value in args.items():
        if isinstance(value, str):
            original_value = value
            result[key] = deanonymize(value, _session_id)
            # Log if something was de-anonymized
            if result[key] != original_value:
                mcp_log(f"[Proxy] De-anonymized {key}: found placeholders")
        else:
            result[key] = value
    return result


def load_mcp_package(package_dir: Path, module_name_override: str = None):
    """Load an MCP package (subfolder with __init__.py) and return it.

    Args:
        package_dir: Path to the package directory (e.g., mcp/outlook/ or plugins/sap/mcp/)
        module_name_override: Optional override for module name (used for plugins)

    Returns:
        The loaded module
    """
    # Use override if provided (for plugins where dir is "mcp" but we want "plugin_sap_mcp")
    package_name = module_name_override or package_dir.name

    if package_name in _loaded_modules:
        return _loaded_modules[package_name]

    # Add parent directory to path for imports
    parent = str(package_dir.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    # For plugin MCPs (with override), load directly from file
    if module_name_override:
        init_file = package_dir / "__init__.py"
        if init_file.exists():
            spec = importlib.util.spec_from_file_location(package_name, init_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[package_name] = module
                spec.loader.exec_module(module)
                _loaded_modules[package_name] = module
                return module

    # Standard import for system MCPs
    module = importlib.import_module(package_name)
    _loaded_modules[package_name] = module
    return module


def find_tool_functions(module) -> list:
    """Find all functions decorated with @mcp.tool() in a module.

    Supports package-structured MCPs where tools may be defined in
    sub-modules (e.g., outlook.email_read, gmail.calendar).

    NOTE: This uses a docstring heuristic as fallback. The primary method
    is FastMCP's _tool_manager which contains actually registered tools.
    """
    tools = []
    seen_names = set()  # Track names to prevent duplicates from submodules

    # Get the package name (e.g., "outlook", "gmail", "billomat", "plugin_sap_mcp")
    package_name = module.__name__

    for name, obj in inspect.getmembers(module):
        # Skip private/magic methods
        if name.startswith('_'):
            continue

        # Skip already seen (prevents duplicates from re-exports)
        if name in seen_names:
            continue

        # Skip internal helper functions EARLY (before adding to list)
        # This prevents "Tool already exists" warnings from FastMCP
        if name in _INTERNAL_HELPERS:
            continue

        # Check if it's a callable
        if not callable(obj):
            continue

        # Check if it's a function with a docstring
        if not inspect.isfunction(obj):
            continue
        if not obj.__doc__:
            continue

        # Accept functions from:
        # 1. The package itself (e.g., __module__ == "outlook")
        # 2. Sub-modules of the package (e.g., __module__ == "outlook.email_read")
        # 3. Plugin MCPs loaded via spec (e.g., __module__ == "plugin_sap_mcp")
        # 4. Functions defined in __init__.py often have __module__ == package name
        func_module = obj.__module__
        if (func_module == package_name or
            func_module.startswith(package_name + ".") or
            (package_name.startswith("plugin_") and func_module == package_name)):
            tools.append((name, obj))
            seen_names.add(name)

    return tools


def create_wrapped_tool(
    func,
    module_name: str,
    anonymize_output: bool = True,
    deanonymize_input: bool = True,
    sanitize_output: bool = False
):
    """Create a wrapped version of a tool function.

    Args:
        func: Original tool function
        module_name: Name of the source module (e.g., "outlook", "filesystem")
        anonymize_output: Whether to anonymize PII in output
        deanonymize_input: Whether to de-anonymize placeholders in input
        sanitize_output: Whether to apply prompt injection protection
    """
    sig = inspect.signature(func)
    tool_name = func.__name__

    @wraps(func)
    def wrapper(**kwargs):
        # Log the call BEFORE de-anonymizing (what AI sent - with placeholders)
        args_str = json.dumps(kwargs, ensure_ascii=False, default=str) if kwargs else "{}"
        log_tool_call(tool_name, "CALL", args_str, is_anonymized=True)

        # Check for demo mode first - return mock responses
        config = load_config()
        if _is_demo_mode_enabled(config):
            mcp_log(f"[Proxy] DEMO MODE: Intercepting {tool_name}")
            mock_response = _get_mock_response(tool_name, kwargs, config)

            if mock_response is not None:
                # Apply simulated delay if configured
                _apply_mock_delay(tool_name, config)
                mcp_log(f"[Proxy] DEMO MODE: Returning mock response ({len(mock_response)} chars)")
                log_tool_call(tool_name, "RESULT", f"[DEMO] {mock_response[:200]}...", is_anonymized=False)
                return mock_response
            else:
                mcp_log(f"[Proxy] DEMO MODE: No mock for {tool_name}, falling through to real execution")

        # De-anonymize string inputs if enabled
        if deanonymize_input:
            try:
                kwargs = deanonymize_args(kwargs)
            except Exception as e:
                mcp_log(f"[Proxy] De-anonymize failed for {tool_name}: {e}, using original args")

        # Call original function
        result = func(**kwargs)

        # Skip non-string results
        if not isinstance(result, str):
            log_tool_call(tool_name, "RESULT", f"(non-string: {type(result).__name__})", is_anonymized=False)
            return result

        # Skip error responses
        if result.startswith("Fehler:") or result.startswith("Error:"):
            log_tool_call(tool_name, "RESULT", result, is_anonymized=False)
            return result

        # Anonymize output if enabled
        if anonymize_output:
            result = anonymize_result(result)

        # Log the result AFTER anonymizing (what AI receives - with placeholders)
        log_tool_call(tool_name, "RESULT", result, is_anonymized=anonymize_output)

        # Apply prompt injection protection if enabled
        if sanitize_output:
            config = load_config()
            security_config = config.get("security", {})

            if security_config.get("prompt_injection_protection", True):
                # Detect suspicious patterns
                detections = detect_injection_attempts(result)

                if detections and security_config.get("log_suspicious_patterns", True):
                    mcp_log(f"[Proxy] SECURITY: {len(detections)} suspicious patterns in {tool_name}")

                # Wrap external content with clear delimiters
                if security_config.get("wrap_external_content", True):
                    result = wrap_untrusted_content(
                        result,
                        source_type=module_name,
                        source_info=tool_name,
                        sanitize=True
                    )

        return result

    # Preserve signature for FastMCP
    wrapper.__signature__ = sig
    wrapper.__doc__ = func.__doc__
    wrapper.__name__ = func.__name__

    return wrapper


def register_tools_from_package(package_dir: Path, config: dict, plugin_name: str = None):
    """Load an MCP package and register all its tools with the proxy.

    Args:
        package_dir: Path to the package directory (e.g., mcp/outlook/ or plugins/sap/mcp/)
        config: System configuration dict
        plugin_name: Optional plugin name (for plugins/{plugin}/mcp/ structure)
    """
    # For plugin MCPs, use plugin name as display name
    # For system MCPs, use directory name
    if plugin_name:
        internal_module_name = f"plugin_{plugin_name}_mcp"  # For Python import
        display_name = f"{plugin_name} (plugin)"
        source_name = plugin_name  # For sanitization source info
    else:
        internal_module_name = package_dir.name
        display_name = internal_module_name
        source_name = internal_module_name

    mcp_log(f"[Proxy] Loading package: {display_name}")

    try:
        module = load_mcp_package(package_dir, internal_module_name if plugin_name else None)
    except Exception as e:
        mcp_log(f"[Proxy] Failed to load {display_name}: {e}")
        return 0

    # Get proxy config
    proxy_config = config.get("anonymization_proxy", {})
    no_anonymize = set(proxy_config.get("no_anonymize_output", []))
    no_deanonymize = set(proxy_config.get("no_deanonymize_input", []))

    # Get security config
    security_config = config.get("security", {})
    injection_protection = security_config.get("prompt_injection_protection", True)

    # Check for IS_HIGH_RISK flag (MCP-level: all tools are high-risk)
    # If True, all tools in this MCP will be sanitized
    is_high_risk_mcp = getattr(module, "IS_HIGH_RISK", False)

    # Get HIGH_RISK_TOOLS from the module itself, or use fallback
    # Each MCP can define: HIGH_RISK_TOOLS = {"tool1", "tool2"}
    module_high_risk = getattr(module, "HIGH_RISK_TOOLS", None)
    if is_high_risk_mcp:
        # All tools in this MCP are high-risk (will be populated after tool discovery)
        high_risk_tools = None  # Special marker: all tools
        mcp_log(f"[Proxy]   IS_HIGH_RISK=True: All tools will be sanitized")
    elif module_high_risk:
        high_risk_tools = set(module_high_risk)
        mcp_log(f"[Proxy]   HIGH_RISK_TOOLS defined: {len(high_risk_tools)} tools")
    else:
        high_risk_tools = _FALLBACK_HIGH_RISK_TOOLS

    # Try to find tools using multiple methods
    tools = find_tool_functions(module)

    # Also check FastMCP's registered tools (for package-style MCPs like outlook)
    # This is the same approach used by tool_bridge.py
    mcp_instance = getattr(module, 'mcp', None)
    if mcp_instance:
        registered_tools = []

        # Method 1: Check for _tool_manager._tools (FastMCP)
        if hasattr(mcp_instance, '_tool_manager'):
            tool_manager = mcp_instance._tool_manager
            if hasattr(tool_manager, '_tools'):
                registered_tools = list(tool_manager._tools.values())
                mcp_log(f"[Proxy]   Found {len(registered_tools)} tools in FastMCP _tool_manager")

        # Method 2: Check for _tools directly
        if not registered_tools and hasattr(mcp_instance, '_tools'):
            registered_tools = list(mcp_instance._tools.values())
            mcp_log(f"[Proxy]   Found {len(registered_tools)} tools in FastMCP _tools")

        # Add FastMCP tools to our list (if not already found)
        existing_names = {name for name, _ in tools}
        for tool in registered_tools:
            # Get the actual function
            if callable(tool):
                func = tool
            elif hasattr(tool, 'fn'):
                func = tool.fn
            elif hasattr(tool, 'func'):
                func = tool.func
            else:
                continue

            func_name = getattr(func, '__name__', None)
            if not func_name:
                continue

            # Skip internal helpers (shouldn't be in FastMCP, but safety check)
            if func_name in _INTERNAL_HELPERS:
                continue

            if func_name not in existing_names:
                tools.append((func_name, func))
                existing_names.add(func_name)

    registered = 0

    for name, func in tools:
        # Skip internal helper functions (not actual tools)
        if name in _INTERNAL_HELPERS:
            continue

        # Skip already registered tools (prevents duplicates)
        if name in _registered_tool_names:
            mcp_log(f"[Proxy]   - {name}: skipped (duplicate)")
            continue

        try:
            # Check config for this specific tool
            anonymize_output = name not in no_anonymize
            deanonymize_input = name not in no_deanonymize

            # Determine if this tool needs sanitization
            # Tool is sanitized if:
            # - IS_HIGH_RISK=True (all tools) OR
            # - Tool name is in HIGH_RISK_TOOLS (or fallback)
            if high_risk_tools is None:
                # IS_HIGH_RISK=True: All tools are high-risk
                sanitize_output = injection_protection
            else:
                sanitize_output = injection_protection and name in high_risk_tools

            # Create wrapped function
            wrapped = create_wrapped_tool(
                func, source_name,
                anonymize_output, deanonymize_input,
                sanitize_output
            )

            # Register with FastMCP
            mcp.tool()(wrapped)
            _registered_tool_names.add(name)
            registered += 1

            flags = []
            if not anonymize_output:
                flags.append("no-anon")
            if not deanonymize_input:
                flags.append("no-deanon")
            if sanitize_output:
                flags.append("sanitize")
            flag_str = f" [{', '.join(flags)}]" if flags else ""

            mcp_log(f"[Proxy]   + {name}{flag_str}")

        except Exception as e:
            mcp_log(f"[Proxy]   x {name}: {e}")

    return registered


def _get_plugin_mcp_dirs() -> list:
    """Get Plugin MCP directories.

    Returns:
        List of (plugin_name, mcp_dir_path) tuples for plugins with MCP servers.
        Uses simplified structure: plugins/{plugin}/mcp/__init__.py
    """
    result = []

    # Find plugins directory (relative to DESKAGENT_DIR)
    # In dev: aiassistant/plugins/ (symlink to workspace)
    # In production: workspace/plugins/
    plugins_dir = DESKAGENT_DIR.parent / "plugins"

    if not plugins_dir.exists():
        # Try alternate location via environment variable
        workspace_dir = os.environ.get("DESKAGENT_WORKSPACE_DIR")
        if workspace_dir:
            plugins_dir = Path(workspace_dir) / "plugins"

    if not plugins_dir.exists():
        return result

    for plugin_folder in sorted(plugins_dir.iterdir()):
        if not plugin_folder.is_dir():
            continue
        if plugin_folder.name.startswith('.') or plugin_folder.name.startswith('_'):
            continue

        # Check for plugin.json manifest
        manifest = plugin_folder / "plugin.json"
        if not manifest.exists():
            continue

        # Check for MCP in new simplified structure: mcp/__init__.py
        mcp_init = plugin_folder / "mcp" / "__init__.py"
        if mcp_init.exists():
            result.append((plugin_folder.name, plugin_folder / "mcp"))

    return result


def discover_and_register_all_tools():
    """Discover all MCP packages (system and plugins) and register their tools."""
    config = load_config()
    total_tools = 0

    # Check for MCP server filtering pattern from environment variable
    # This filters which MCP servers (packages) are loaded, not individual tools
    allowed_pattern = os.environ.get("ALLOWED_MCP_PATTERN")
    mcp_filter = None
    if allowed_pattern:
        try:
            mcp_filter = re.compile(allowed_pattern, re.IGNORECASE)
            mcp_log(f"[Proxy] MCP server filter active: {allowed_pattern}")
        except re.error as e:
            mcp_log(f"[Proxy] Invalid MCP filter pattern: {e}")

    # =========================================================================
    # 1. System MCPs (deskagent/mcp/)
    # =========================================================================
    skipped_modules = []
    for mcp_dir in sorted(MCP_DIR.iterdir()):
        # Skip non-directories
        if not mcp_dir.is_dir():
            continue

        # Skip __pycache__ and hidden folders
        if mcp_dir.name.startswith('_') or mcp_dir.name.startswith('.'):
            continue

        # Check for __init__.py (valid Python package)
        init_file = mcp_dir / "__init__.py"
        if not init_file.exists():
            continue

        module_name = mcp_dir.name  # e.g., "outlook", "gmail", "billomat"

        # Check if module matches the filter pattern
        if mcp_filter and not mcp_filter.search(module_name):
            skipped_modules.append(module_name)
            continue

        count = register_tools_from_package(mcp_dir, config)
        total_tools += count

    if skipped_modules:
        mcp_log(f"[Proxy] Skipped system packages: {', '.join(skipped_modules)}")

    # =========================================================================
    # 2. Plugin MCPs (plugins/{plugin}/mcp/)
    # =========================================================================
    plugin_mcps = _get_plugin_mcp_dirs()
    skipped_plugins = []

    for plugin_name, plugin_mcp_dir in plugin_mcps:
        # Check if plugin matches the filter pattern
        # Plugin filter format: "plugin_name" matches both "plugin_name" and "plugin_name:*"
        if mcp_filter and not mcp_filter.search(plugin_name):
            skipped_plugins.append(plugin_name)
            continue

        # Pass plugin_name to register_tools_from_package for proper module naming
        count = register_tools_from_package(plugin_mcp_dir, config, plugin_name=plugin_name)
        total_tools += count

    if skipped_plugins:
        mcp_log(f"[Proxy] Skipped plugin packages: {', '.join(skipped_plugins)}")

    mcp_log(f"[Proxy] Registered {total_tools} tools from MCP packages (system + plugins)")
    return total_tools


# =============================================================================
# Proxy-specific tools (always available)
# =============================================================================

@mcp.tool()
def proxy_reset_context() -> str:
    """Setzt den Anonymisierungs-Kontext zurueck.
    Nutze dies am Anfang einer neuen Aufgabe."""
    cleanup_session(_session_id)
    return "Anonymisierungs-Kontext zurueckgesetzt"


@mcp.tool()
def proxy_get_session_id() -> str:
    """Zeigt die aktuelle Session-ID fuer Anonymisierung.
    Nur fuer Debug-Zwecke."""
    return f"Session ID: {_session_id}"


@mcp.tool()
async def proxy_reload_tools(ctx: Context) -> str:
    """Reload all MCP tools and notify the client.
    Use this after MCP configuration changes (e.g. enabling/disabling integrations)
    so the client gets updated tools without restart."""
    global _registered_tool_names, _lazy_modules

    old_count = len(_registered_tool_names)

    # Clear existing tools (keep proxy_* tools)
    proxy_tools = {n for n in _registered_tool_names if n.startswith("proxy_")}
    _registered_tool_names.clear()
    _registered_tool_names.update(proxy_tools)
    _lazy_modules.clear()

    # Re-discover and register tools
    discover_and_register_all_tools()

    new_count = len(_registered_tool_names)
    mcp_log(f"[Proxy] Reloaded tools: {old_count} -> {new_count}")

    # Notify client that tool list changed
    try:
        await ctx.session.send_tool_list_changed()
        mcp_log("[Proxy] Sent tool_list_changed notification")
    except Exception as e:
        mcp_log(f"[Proxy] Failed to send tool_list_changed: {e}")

    return f"Tools reloaded: {old_count} -> {new_count} tools"


@mcp.tool()
def proxy_list_tools() -> str:
    """Listet alle verfuegbaren Tools im Proxy auf."""
    lines = [f"Verfuegbare Tools im Anonymization Proxy: {len(_registered_tool_names)}"]

    # Show all registered tools (works in both cache and slow-path mode)
    if _registered_tool_names:
        # Group by prefix (mcp name)
        groups: dict[str, list[str]] = {}
        for name in sorted(_registered_tool_names):
            prefix = name.split("_")[0] if "_" in name else "other"
            groups.setdefault(prefix, []).append(name)
        for prefix in sorted(groups.keys()):
            lines.append(f"\n## {prefix} ({len(groups[prefix])} tools)")
            for tool_name in groups[prefix]:
                lines.append(f"  - {tool_name}")

    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================

# =============================================================================
# Fast startup via cache
# =============================================================================

# Lazy-loaded module cache for tool execution
_lazy_modules: dict = {}


def _load_from_cache(mcp_filter: str = None) -> int:
    """Load tool schemas from cache file for fast startup.

    Supports both v1 and v2 cache formats:
    - v1: Basic tool schemas (name, description, parameters, module)
    - v2: Extended with mcp_mtimes, configured_mcps, is_high_risk per tool

    In v2 mode, HIGH_RISK_TOOLS are read from cache metadata, enabling
    prompt injection protection even before MCP modules are imported.

    Returns number of tools registered, or 0 if cache not available.
    """
    try:
        # Find cache file - use DESKAGENT_WORKSPACE_DIR env var or derive from MCP_DIR
        workspace_dir = os.environ.get("DESKAGENT_WORKSPACE_DIR")
        if workspace_dir:
            cache_file = Path(workspace_dir) / ".temp" / "proxy_tool_cache.json"
        else:
            # Derive workspace from MCP_DIR: deskagent/mcp -> ../workspace
            cache_file = MCP_DIR.parent.parent / "workspace" / ".temp" / "proxy_tool_cache.json"

        if not cache_file.exists():
            mcp_log("[Proxy] No cache file found, using slow path")
            return 0

        cache_data = json.loads(cache_file.read_text(encoding='utf-8'))
        cache_version = cache_data.get("version", 1)
        mcp_log(f"[Proxy] Loading from cache v{cache_version} ({cache_data.get('generated', 'unknown')})")

        # Validate mtimes - check if any MCP file was modified since cache was built
        cached_mtimes = cache_data.get("mcp_mtimes", {})
        if cached_mtimes:
            for mcp_name, cached_mtime in cached_mtimes.items():
                init_file = MCP_DIR / mcp_name / "__init__.py"
                if init_file.exists():
                    try:
                        current_mtime = init_file.stat().st_mtime
                        if abs(current_mtime - cached_mtime) > 0.01:
                            mcp_log(f"[Proxy] Cache stale: {mcp_name} modified since cache build, using slow path")
                            return 0
                    except OSError:
                        return 0

            # Check for new MCP directories not in cache (system + plugins)
            current_mcps = {
                d.name for d in MCP_DIR.iterdir()
                if d.is_dir() and not d.name.startswith("_") and (d / "__init__.py").exists()
            }
            # Also check plugin MCPs
            plugins_dir = MCP_DIR.parent.parent / "plugins"
            if not plugins_dir.exists():
                ws = os.environ.get("DESKAGENT_WORKSPACE_DIR")
                if ws:
                    plugins_dir = Path(ws) / "plugins"
            if plugins_dir.exists():
                for pd in plugins_dir.iterdir():
                    if pd.is_dir() and not pd.name.startswith(("_", ".")) and (pd / "mcp" / "__init__.py").exists():
                        current_mcps.add(f"plugin_{pd.name}_mcp")
            new_mcps = current_mcps - set(cached_mtimes.keys())
            if new_mcps:
                mcp_log(f"[Proxy] Cache stale: new MCPs detected: {new_mcps}, using slow path")
                return 0

        # Build filter regex if provided
        filter_re = None
        if mcp_filter:
            try:
                filter_re = re.compile(mcp_filter, re.IGNORECASE)
            except re.error:
                pass

        config = load_config()
        injection_protection = config.get("security", {}).get("prompt_injection_protection", True)

        # v2: Build high-risk tools set from cache metadata
        cached_high_risk_tools = set()
        if cache_version >= 2:
            for tool_info in cache_data.get("tools", []):
                if tool_info.get("is_high_risk", False):
                    cached_high_risk_tools.add(tool_info["name"])
            if cached_high_risk_tools:
                mcp_log(f"[Proxy] Loaded {len(cached_high_risk_tools)} HIGH_RISK_TOOLS from cache")

        registered = 0
        for tool_info in cache_data.get("tools", []):
            tool_name = tool_info["name"]
            module_name = tool_info.get("module", "")

            # Apply MCP filter (check if module name matches)
            if filter_re:
                # Extract MCP name from module (e.g., "msgraph" from tool name prefix)
                # Tool names are prefixed: graph_get_email -> msgraph
                mcp_name = tool_name.split("_")[0] if "_" in tool_name else tool_name
                # Map common prefixes to module names
                prefix_to_module = {
                    "graph": "msgraph",
                    "outlook": "outlook",
                    "userecho": "userecho",
                    "teams": "msgraph",
                }
                mcp_name = prefix_to_module.get(mcp_name, mcp_name)
                if not filter_re.search(mcp_name):
                    continue

            # Skip if already registered
            if tool_name in _registered_tool_names:
                continue

            # Determine sanitization from cache metadata (v2) or fallback (v1)
            if cache_version >= 2:
                sanitize_output = injection_protection and tool_info.get("is_high_risk", False)
            else:
                # v1 fallback: use fallback set
                sanitize_output = injection_protection and tool_name in _FALLBACK_HIGH_RISK_TOOLS

            # Create lazy wrapper that imports module on first call
            def make_lazy_wrapper(name: str, mod: str, params: dict, needs_sanitize: bool):
                async def lazy_tool(**kwargs):
                    # FIX: FastMCP doesn't support **kwargs in tool signatures properly.
                    if len(kwargs) == 1 and "kwargs" in kwargs:
                        inner = kwargs["kwargs"]
                        if isinstance(inner, dict):
                            kwargs = inner
                        elif inner is None:
                            kwargs = {}

                    # De-anonymize string inputs
                    try:
                        str_kwargs = {}
                        for key, value in kwargs.items():
                            if isinstance(value, str):
                                str_kwargs[key] = deanonymize(value, _session_id)
                            else:
                                str_kwargs[key] = value
                        kwargs = str_kwargs
                    except Exception as e:
                        mcp_log(f"[Proxy] De-anonymize failed for {name}: {e}, using original args")

                    # Import module on first call
                    if mod not in _lazy_modules:
                        mcp_log(f"[Proxy] Lazy loading module for: {name} from {mod}")

                        mod_parts = mod.split(".")
                        package_name = mod_parts[0]

                        for mcp_dir in MCP_DIR.iterdir():
                            if mcp_dir.is_dir() and mcp_dir.name == package_name:
                                init_file = mcp_dir / "__init__.py"
                                if init_file.exists() and package_name not in sys.modules:
                                    spec = importlib.util.spec_from_file_location(package_name, init_file)
                                    pkg_module = importlib.util.module_from_spec(spec)
                                    sys.modules[package_name] = pkg_module
                                    spec.loader.exec_module(pkg_module)

                                if len(mod_parts) > 1:
                                    submod_name = mod_parts[1]
                                    submod_file = mcp_dir / f"{submod_name}.py"
                                    if submod_file.exists():
                                        spec = importlib.util.spec_from_file_location(mod, submod_file)
                                        submodule = importlib.util.module_from_spec(spec)
                                        sys.modules[mod] = submodule
                                        spec.loader.exec_module(submodule)
                                        _lazy_modules[mod] = submodule
                                    else:
                                        mcp_log(f"[Proxy] Submodule not found: {submod_file}")
                                else:
                                    _lazy_modules[mod] = sys.modules.get(package_name)
                                break

                    # Find the actual function via FastMCP's tool registry
                    module = _lazy_modules.get(mod)
                    if module:
                        func = None

                        mcp_instance = getattr(module, 'mcp', None)
                        if mcp_instance and hasattr(mcp_instance, '_tool_manager'):
                            tool_manager = mcp_instance._tool_manager
                            if hasattr(tool_manager, '_tools'):
                                tool = tool_manager._tools.get(name)
                                if tool and hasattr(tool, 'fn'):
                                    func = tool.fn

                        if not func:
                            func = getattr(module, name, None)

                        if func and callable(func):
                            result = await func(**kwargs) if asyncio.iscoroutinefunction(func) else func(**kwargs)

                            # Apply prompt injection protection if needed
                            if needs_sanitize and isinstance(result, str):
                                security_config = config.get("security", {})
                                if security_config.get("wrap_external_content", True):
                                    # Extract source name from module
                                    source_name = mod.split(".")[0] if mod else "unknown"
                                    result = wrap_untrusted_content(
                                        result,
                                        source_type=source_name,
                                        source_info=name,
                                        sanitize=True
                                    )

                            # Anonymize output
                            if isinstance(result, str):
                                result = anonymize_result(result)

                            return result

                    return f"Error: Could not find function {name} in module {mod}"

                lazy_tool.__name__ = name
                lazy_tool.__doc__ = params.get("description", "")

                # Build typed signature from cache schema so FastMCP generates correct parameter schema
                schema_props = params.get("properties", {})
                schema_required = set(params.get("required", []))
                if schema_props:
                    type_map = {"string": str, "integer": int, "number": float, "boolean": bool}
                    sig_params = []
                    for pname, pinfo in schema_props.items():
                        ptype = type_map.get(pinfo.get("type", "string"), str)
                        if pname in schema_required:
                            sig_params.append(
                                inspect.Parameter(pname, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=ptype)
                            )
                        else:
                            sig_params.append(
                                inspect.Parameter(pname, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                                  default=None, annotation=ptype)
                            )
                    lazy_tool.__signature__ = inspect.Signature(sig_params)

                return lazy_tool

            # Create and register the lazy wrapper
            wrapper = make_lazy_wrapper(tool_name, module_name, tool_info.get("parameters", {}), sanitize_output)
            mcp.tool()(wrapper)
            _registered_tool_names.add(tool_name)
            registered += 1

        mcp_log(f"[Proxy] Loaded {registered} tools from cache v{cache_version}")
        return registered

    except Exception as e:
        mcp_log(f"[Proxy] Cache load failed: {e}, using slow path")
        return 0


def _register_knowledge_resources():
    """Register knowledge markdown files as MCP resources.

    Exposes user knowledge (company, products, mail style) and key system docs
    so Claude can read them for context. Files from both knowledge/ (user) and
    deskagent/knowledge/ (system) are registered.
    """
    registered = 0

    # Find knowledge directories
    knowledge_dirs = []

    # User knowledge: workspace/../knowledge/
    workspace_dir = os.environ.get("DESKAGENT_WORKSPACE_DIR")
    if workspace_dir:
        user_knowledge = Path(workspace_dir).parent / "knowledge"
    else:
        user_knowledge = MCP_DIR.parent.parent / "knowledge"
    if user_knowledge.exists():
        knowledge_dirs.append(("user", user_knowledge))

    # System knowledge: deskagent/knowledge/
    system_knowledge = MCP_DIR.parent / "knowledge"
    if system_knowledge.exists():
        knowledge_dirs.append(("system", system_knowledge))

    for source, kdir in knowledge_dirs:
        for md_file in sorted(kdir.rglob("*.md")):
            rel = md_file.relative_to(kdir)
            name = str(rel).replace("\\", "/").replace(".md", "")
            uri = f"knowledge://{source}/{name}"

            # Use default arg to capture file_path per iteration
            def _make_reader(fpath=md_file):
                def _read() -> str:
                    return fpath.read_text(encoding="utf-8")
                return _read

            try:
                reader_fn = _make_reader()
                mcp.resource(uri, name=f"{source}/{name}",
                             description=f"Knowledge: {name}",
                             mime_type="text/markdown")(reader_fn)
                registered += 1
            except Exception as e:
                mcp_log(f"[Proxy] Failed to register resource {uri}: {e}")

    if registered:
        mcp_log(f"[Proxy] Registered {registered} knowledge resources")


def _register_agent_prompts():
    """Register DeskAgent agents as MCP Prompts (slash commands).

    Scans agents/*.md files directly (no discover_agents() import to avoid
    sse_manager dependency chain). Agents become /deskagent_<name> commands
    in Claude Desktop.
    """
    registered = 0

    # Find agent directories (same logic as knowledge)
    agent_dirs = []

    workspace_dir = os.environ.get("DESKAGENT_WORKSPACE_DIR")
    if workspace_dir:
        user_agents = Path(workspace_dir).parent / "agents"
    else:
        user_agents = MCP_DIR.parent.parent / "agents"
    if user_agents.exists():
        agent_dirs.append(("user", user_agents))

    system_agents = MCP_DIR.parent / "agents"
    if system_agents.exists():
        agent_dirs.append(("system", system_agents))

    # Track registered names to avoid duplicates (user overrides system)
    seen_names = set()

    for source, adir in agent_dirs:
        for md_file in sorted(adir.glob("*.md")):
            agent_name = md_file.stem  # e.g. "reply_email"

            # Skip duplicates (user takes precedence over system)
            if agent_name in seen_names:
                continue
            seen_names.add(agent_name)

            # Sanitize name: only alphanumeric, underscore, hyphen
            if not re.match(r'^[a-zA-Z0-9_\-]+$', agent_name):
                continue

            # Parse frontmatter to check enabled status and get description
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            # Parse JSON frontmatter
            frontmatter = {}
            prompt_content = content
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        frontmatter = json.loads(parts[1].strip())
                    except (json.JSONDecodeError, ValueError):
                        pass
                    prompt_content = parts[2].strip()

            # Skip disabled agents
            if frontmatter.get("enabled") is False:
                continue

            # Skip agents without explicit prompt exposure if they have tool definition
            # (tool-agents are already exposed as MCP tools, not prompts)
            if "tool" in frontmatter:
                continue

            description = frontmatter.get("description", f"Run {agent_name} workflow")
            prompt_name = agent_name

            def _make_prompt_fn(pcontent=prompt_content, pname=prompt_name):
                def _prompt_fn() -> str:
                    return pcontent
                _prompt_fn.__name__ = pname
                _prompt_fn.__doc__ = description
                return _prompt_fn

            try:
                fn = _make_prompt_fn()
                mcp.prompt(name=prompt_name, description=description)(fn)
                registered += 1
            except Exception as e:
                mcp_log(f"[Proxy] Failed to register prompt {prompt_name}: {e}")

    if registered:
        mcp_log(f"[Proxy] Registered {registered} agent prompts")


def _register_agent_resources():
    """Register agent and skill files as MCP resource templates.

    Exposes agents as agent://<name> and skills as skill://<name> URIs
    so Claude can read workflow definitions dynamically.
    """
    registered = 0

    # Agent directories
    agent_dirs = []
    workspace_dir = os.environ.get("DESKAGENT_WORKSPACE_DIR")
    if workspace_dir:
        user_agents = Path(workspace_dir).parent / "agents"
    else:
        user_agents = MCP_DIR.parent.parent / "agents"
    if user_agents.exists():
        agent_dirs.append(("user", user_agents))
    system_agents = MCP_DIR.parent / "agents"
    if system_agents.exists():
        agent_dirs.append(("system", system_agents))

    # Build agent lookup (user overrides system)
    agent_files = {}
    for source, adir in agent_dirs:
        for md_file in sorted(adir.glob("*.md")):
            name = md_file.stem
            if re.match(r'^[a-zA-Z0-9_\-]+$', name):
                agent_files[name] = md_file

    # Register each agent as a resource
    for name, fpath in sorted(agent_files.items()):
        uri = f"agent://{name}"

        def _make_reader(fp=fpath):
            def _read() -> str:
                return fp.read_text(encoding="utf-8")
            return _read

        try:
            reader_fn = _make_reader()
            mcp.resource(uri, name=f"agent/{name}",
                         description=f"Agent workflow: {name}",
                         mime_type="text/markdown")(reader_fn)
            registered += 1
        except Exception as e:
            mcp_log(f"[Proxy] Failed to register agent resource {uri}: {e}")

    # Skill directories
    skill_dirs = []
    if workspace_dir:
        user_skills = Path(workspace_dir).parent / "skills"
    else:
        user_skills = MCP_DIR.parent.parent / "skills"
    if user_skills.exists():
        skill_dirs.append(("user", user_skills))
    system_skills = MCP_DIR.parent / "skills"
    if system_skills.exists():
        skill_dirs.append(("system", system_skills))

    skill_files = {}
    for source, sdir in skill_dirs:
        for md_file in sorted(sdir.rglob("*.md")):
            rel = md_file.relative_to(sdir)
            name = str(rel).replace("\\", "/").replace(".md", "")
            if not re.match(r'^[a-zA-Z0-9_\-/]+$', name):
                continue
            skill_files[name] = md_file

    for name, fpath in sorted(skill_files.items()):
        uri = f"skill://{name}"

        def _make_reader(fp=fpath):
            def _read() -> str:
                return fp.read_text(encoding="utf-8")
            return _read

        try:
            reader_fn = _make_reader()
            mcp.resource(uri, name=f"skill/{name}",
                         description=f"Skill: {name}",
                         mime_type="text/markdown")(reader_fn)
            registered += 1
        except Exception as e:
            mcp_log(f"[Proxy] Failed to register skill resource {uri}: {e}")

    if registered:
        mcp_log(f"[Proxy] Registered {registered} agent/skill resources")


def _ensure_ssl_cert():
    """Generate a self-signed SSL certificate for HTTPS on localhost.

    Creates cert/key files in the workspace/.state/ directory if they don't exist.
    Returns (certfile_path, keyfile_path) or (None, None) on failure.
    """
    import ssl
    import subprocess
    import tempfile

    # Store certs next to the proxy script (deskagent/mcp/.ssl/)
    ssl_dir = Path(__file__).parent / ".ssl"
    certfile = ssl_dir / "localhost.pem"
    keyfile = ssl_dir / "localhost-key.pem"

    if certfile.exists() and keyfile.exists():
        return str(certfile), str(keyfile)

    ssl_dir.mkdir(parents=True, exist_ok=True)

    # Generate using Python's ssl module (no external tools needed)
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        keyfile.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
        certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        mcp_log(f"[SSL] Generated self-signed cert: {certfile}")
        return str(certfile), str(keyfile)

    except ImportError:
        mcp_log("[SSL] cryptography package not available, trying openssl CLI")

    # Fallback: use openssl CLI
    try:
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(keyfile), "-out", str(certfile),
            "-days", "3650", "-nodes",
            "-subj", "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"
        ], check=True, capture_output=True, timeout=30)
        mcp_log(f"[SSL] Generated self-signed cert via openssl: {certfile}")
        return str(certfile), str(keyfile)
    except Exception as e:
        mcp_log(f"[SSL] Failed to generate cert: {e}")
        # Clean up partial files
        for f in (certfile, keyfile):
            if f.exists():
                f.unlink()
        return None, None


if __name__ == "__main__":
    import argparse

    # Parse command line arguments (more reliable than env vars)
    parser = argparse.ArgumentParser(description="Anonymization Proxy MCP Server")
    parser.add_argument("--session", type=str, help="Session ID for this agent run")
    parser.add_argument("--filter", type=str, help="MCP server filter pattern (regex)")
    # HTTP/SSE Transport options (for Claude SDK integration)
    parser.add_argument("--transport", type=str, default="stdio", choices=["stdio", "sse", "streamable-http"],
                        help="Transport protocol: stdio (default), streamable-http (recommended), or sse (deprecated)")
    parser.add_argument("--host", type=str, default="localhost",
                        help="Host to bind SSE server (default: localhost)")
    parser.add_argument("--port", type=int, default=8766,
                        help="Port for SSE server (default: 8766)")
    parser.add_argument("--ssl", action="store_true",
                        help="Enable HTTPS with self-signed cert (for remote access only)")
    args = parser.parse_args()

    transport_info = f"transport={args.transport}"
    if args.transport in ("sse", "streamable-http"):
        transport_info += f", host={args.host}, port={args.port}"
    mcp_log(f"[Anonymization Proxy] Starting dynamic proxy ({transport_info})...")
    mcp_log(f"[Anonymization Proxy] Anonymizer available: {is_anonymizer_available()}")

    # Set session ID from args (preferred) or env (fallback) or generate new
    if args.session:
        _session_id = args.session
        mcp_log(f"[Proxy] Session ID from args: {_session_id}")
    else:
        _session_id = os.environ.get("ANON_SESSION_ID", str(uuid.uuid4()))
        mcp_log(f"[Proxy] Session ID from env/generated: {_session_id}")

    # Set MCP filter from args (preferred) or env (fallback)
    mcp_filter = None
    if args.filter:
        mcp_filter = args.filter
        os.environ["ALLOWED_MCP_PATTERN"] = args.filter
        mcp_log(f"[Proxy] MCP filter from args: {args.filter}")

    # Try fast path (cache) first, fall back to slow path (full module import)
    cached_count = _load_from_cache(mcp_filter)
    if cached_count == 0:
        # No cache or cache load failed - use slow path
        discover_and_register_all_tools()

    # Register knowledge files as MCP resources (for Claude Desktop context)
    try:
        _register_knowledge_resources()
    except Exception as e:
        mcp_log(f"[Proxy] Knowledge resource registration failed: {e}")

    # Register agents as MCP prompts (slash commands in Claude Desktop)
    try:
        _register_agent_prompts()
    except Exception as e:
        mcp_log(f"[Proxy] Agent prompt registration failed: {e}")

    # Register agent/skill files as MCP resources (agent://<name>, skill://<name>)
    try:
        _register_agent_resources()
    except Exception as e:
        mcp_log(f"[Proxy] Agent/skill resource registration failed: {e}")

    mcp_log("[Anonymization Proxy] Ready!")

    # Run with appropriate transport
    if args.transport == "streamable-http":
        # HTTP transport with tool filtering middleware
        # We wrap FastMCP's Starlette app with our filtering middleware
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp_log(f"[Anonymization Proxy] Starting HTTP server on {args.host}:{args.port}/mcp")

        # Get FastMCP's Starlette app and wrap with middleware
        try:
            import uvicorn

            # Try different methods to get the ASGI app from FastMCP
            mcp_app = None

            # Method 1: streamable_http_app() (FastMCP >= 2.0)
            if hasattr(mcp, 'streamable_http_app'):
                mcp_app = mcp.streamable_http_app()

            # Method 2: http_app() (some versions)
            elif hasattr(mcp, 'http_app'):
                mcp_app = mcp.http_app()

            # Method 3: sse_app() for SSE transport
            elif hasattr(mcp, 'sse_app'):
                mcp_app = mcp.sse_app()

            # Method 4: Direct app access
            elif hasattr(mcp, '_app'):
                mcp_app = mcp._app

            if mcp_app:
                # Wrap with our filtering middleware
                wrapped_app = ToolFilterMiddleware(mcp_app)
                mcp_log(f"[Anonymization Proxy] Tool filtering middleware enabled")

                # SSL only when explicitly requested (--ssl flag)
                ssl_kwargs = {}
                if args.ssl:
                    try:
                        ssl_certfile, ssl_keyfile = _ensure_ssl_cert()
                        if ssl_certfile and ssl_keyfile:
                            ssl_kwargs["ssl_certfile"] = ssl_certfile
                            ssl_kwargs["ssl_keyfile"] = ssl_keyfile
                            mcp_log(f"[Anonymization Proxy] HTTPS enabled (self-signed cert)")
                    except Exception as ssl_err:
                        mcp_log(f"[Anonymization Proxy] SSL setup failed, using HTTP: {ssl_err}")

                # Run with uvicorn
                uvicorn.run(
                    wrapped_app,
                    host=args.host,
                    port=args.port,
                    log_level="warning",
                    **ssl_kwargs
                )
            else:
                mcp_log("[Anonymization Proxy] Could not get ASGI app, using standard run (no filtering)")
                mcp.run(transport="streamable-http")

        except Exception as e:
            mcp_log(f"[Anonymization Proxy] Middleware setup failed: {e}, falling back to standard run")
            mcp.run(transport="streamable-http")

    elif args.transport == "sse":
        # SSE transport only (deprecated, use streamable-http instead)
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp_log(f"[Anonymization Proxy] Starting SSE server on {args.host}:{args.port}")
        mcp.run(transport="sse")
    else:
        # Default stdio transport
        mcp.run()
