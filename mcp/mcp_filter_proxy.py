#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP Filter Proxy
================
HTTP Proxy Layer for dynamic per-session tool filtering.

Architecture:
    Claude SDK -> Filter Proxy (Port PROXY_PORT) -> FastMCP (Port FASTMCP_PORT)
                       |
                  Filters tools/list response
                  based on session-specific filter

The proxy intercepts HTTP requests and:
1. Extracts session_id and filter pattern from URL query params
2. Stores filter pattern per session
3. Forwards all requests to FastMCP
4. Filters tools/list responses based on session filter

Usage:
    # Start proxy (automatically started by mcp_proxy_manager.py)
    python mcp_filter_proxy.py --proxy-port 19000 --fastmcp-port 19001

    # Client connects with filter in URL:
    http://localhost:19000/mcp?session=abc123&filter=outlook|billomat
"""

import argparse
import asyncio
import json
import re
import sys
import threading
import time
from pathlib import Path

# Add MCP_DIR to path for _mcp_api import
MCP_DIR = Path(__file__).parent
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

try:
    from _mcp_api import mcp_log
except ImportError:
    def mcp_log(msg: str, level: str = "info") -> None:
        print(f"[FilterProxy] {msg}")


# =============================================================================
# Configuration
# =============================================================================

# Default ports (can be overridden via CLI args)
DEFAULT_PROXY_PORT = 19000    # External port (Claude SDK connects here)
DEFAULT_FASTMCP_PORT = 19001  # Internal port (FastMCP runs here)


# =============================================================================
# Session Filter Storage (thread-safe)
# =============================================================================

_session_filters: dict[str, str] = {}  # session_id -> filter_pattern
_session_filters_lock = threading.Lock()
_session_last_access: dict[str, float] = {}  # session_id -> timestamp
SESSION_TTL_SECONDS = 3600  # 1 hour TTL for stale sessions


def register_session_filter(session_id: str, filter_pattern: str) -> None:
    """Register or update MCP filter for a session.

    Args:
        session_id: Unique session identifier
        filter_pattern: Regex pattern for allowed MCPs (e.g., "outlook|billomat")
    """
    with _session_filters_lock:
        old_filter = _session_filters.get(session_id)
        if old_filter != filter_pattern:
            _session_filters[session_id] = filter_pattern
            _session_last_access[session_id] = time.time()
            mcp_log(f"[Filter] Session {session_id}: filter={filter_pattern}")
        else:
            # Just update last access time
            _session_last_access[session_id] = time.time()


def get_session_filter(session_id: str) -> str | None:
    """Get filter pattern for a session.

    Args:
        session_id: Session identifier

    Returns:
        Filter pattern string or None if no filter set
    """
    with _session_filters_lock:
        if session_id in _session_filters:
            _session_last_access[session_id] = time.time()
        return _session_filters.get(session_id)


def clear_session_filter(session_id: str) -> None:
    """Remove filter for a session (called when agent ends).

    Args:
        session_id: Session to clean up
    """
    with _session_filters_lock:
        _session_filters.pop(session_id, None)
        _session_last_access.pop(session_id, None)
        mcp_log(f"[Filter] Session {session_id}: cleared")


def cleanup_stale_sessions() -> int:
    """Remove sessions that haven't been accessed in SESSION_TTL_SECONDS.

    Returns:
        Number of sessions cleaned up
    """
    now = time.time()
    to_remove = []

    with _session_filters_lock:
        for session_id, last_access in _session_last_access.items():
            if now - last_access > SESSION_TTL_SECONDS:
                to_remove.append(session_id)

        for session_id in to_remove:
            _session_filters.pop(session_id, None)
            _session_last_access.pop(session_id, None)

    if to_remove:
        mcp_log(f"[Filter] Cleaned up {len(to_remove)} stale sessions")

    return len(to_remove)


# =============================================================================
# Tool Filtering Logic
# =============================================================================

def parse_sse_response(response_body: bytes) -> tuple[dict | None, str | None]:
    """Parse SSE (Server-Sent Events) response format.

    SSE format from FastMCP with stateless_http=True:
        event: message
        data: {"jsonrpc":"2.0","result":{"tools":[...]}}

    Args:
        response_body: Raw response bytes

    Returns:
        Tuple of (parsed_json_data, sse_event_type) or (None, None) if not SSE
    """
    try:
        text = response_body.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None, None

    # Check if this looks like SSE format
    if not (text.startswith("event:") or text.startswith("data:") or "\ndata:" in text):
        return None, None

    # Parse SSE lines
    event_type = None
    data_lines = []

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())

    if not data_lines:
        return None, event_type

    # Join data lines and parse as JSON
    data_str = "\n".join(data_lines)
    try:
        return json.loads(data_str), event_type
    except json.JSONDecodeError:
        return None, event_type


def rebuild_sse_response(data: dict, event_type: str | None = "message") -> bytes:
    """Rebuild SSE response from JSON data.

    Args:
        data: JSON data to include
        event_type: SSE event type (default: "message")

    Returns:
        SSE-formatted response bytes
    """
    lines = []
    if event_type:
        lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data)}")
    lines.append("")  # Empty line to end SSE message
    return "\n".join(lines).encode("utf-8")


def filter_tools_response(session_id: str, response_body: bytes) -> bytes:
    """Filter tools/list response based on session filter.

    Handles both plain JSON and SSE (Server-Sent Events) response formats.
    SSE is returned by FastMCP when using stateless_http=True.

    Args:
        session_id: Session identifier
        response_body: Raw JSON-RPC response from FastMCP (JSON or SSE format)

    Returns:
        Filtered response (or original if no filter or error)
    """
    filter_pattern = get_session_filter(session_id)
    if not filter_pattern:
        return response_body  # No filter -> return unchanged

    # Try SSE format first (FastMCP with stateless_http=True)
    sse_data, sse_event = parse_sse_response(response_body)
    is_sse = sse_data is not None

    try:
        if is_sse:
            data = sse_data
            mcp_log(f"[Filter] Parsing SSE response (event: {sse_event})")
        else:
            data = json.loads(response_body)

        # Check for JSON-RPC result with tools
        if "result" not in data:
            return response_body

        result = data["result"]
        if "tools" not in result:
            return response_body

        # Compile filter regex
        try:
            filter_re = re.compile(filter_pattern, re.IGNORECASE)
        except re.error as e:
            mcp_log(f"[Filter] Invalid regex '{filter_pattern}': {e}")
            return response_body

        original_count = len(result["tools"])

        # Filter tools by MCP name (extracted from tool name prefix)
        # Tool names are like "outlook_get_email" -> MCP name is "outlook"
        # Special case: "proxy_*" tools are always allowed
        filtered_tools = []
        for tool in result["tools"]:
            tool_name = tool.get("name", "")

            # Extract MCP name from tool name (first part before "_")
            if "_" in tool_name:
                mcp_name = tool_name.split("_")[0]
            else:
                mcp_name = tool_name

            # Map common prefixes to MCP names
            # "graph_get_email" -> "msgraph" (Graph API tools start with "graph_")
            prefix_to_mcp = {
                "graph": "msgraph",
                "teams": "msgraph",
            }
            mcp_name = prefix_to_mcp.get(mcp_name, mcp_name)

            # Always allow proxy system tools (F5 requirement)
            if mcp_name == "proxy":
                filtered_tools.append(tool)
            # Check if MCP matches filter pattern
            elif filter_re.search(mcp_name):
                filtered_tools.append(tool)

        result["tools"] = filtered_tools
        filtered_count = len(filtered_tools)

        mcp_log(f"[Filter] Session {session_id}: {filtered_count}/{original_count} tools (filter: {filter_pattern})")

        # Rebuild response in original format (SSE or plain JSON)
        if is_sse:
            return rebuild_sse_response(data, sse_event)
        else:
            return json.dumps(data).encode("utf-8")

    except json.JSONDecodeError as e:
        mcp_log(f"[Filter] JSON decode error: {e}")
        return response_body
    except Exception as e:
        mcp_log(f"[Filter] Unexpected error: {e}")
        return response_body


def is_tools_list_request(body: bytes) -> bool:
    """Check if request body contains a tools/list JSON-RPC method call.

    Args:
        body: Request body bytes

    Returns:
        True if this is a tools/list request
    """
    # Quick byte-level check first (fast path)
    if b'"tools/list"' not in body and b"'tools/list'" not in body:
        return False

    # Parse JSON to be sure
    try:
        data = json.loads(body)
        return data.get("method") == "tools/list"
    except (json.JSONDecodeError, AttributeError):
        return False


# =============================================================================
# HTTP Proxy using aiohttp
# =============================================================================

async def run_proxy(proxy_port: int, fastmcp_port: int) -> None:
    """Run the filter proxy server.

    Args:
        proxy_port: Port for external connections (Claude SDK)
        fastmcp_port: Port where FastMCP is running
    """
    from aiohttp import web, ClientSession, ClientTimeout

    # Target URL for FastMCP
    fastmcp_base = f"http://localhost:{fastmcp_port}"

    # Client session with timeout
    timeout = ClientTimeout(total=300)  # 5 min timeout for long operations

    async def proxy_handler(request: web.Request) -> web.Response:
        """Handle incoming requests: extract filter, forward, and filter response."""

        # Extract session and filter from query params
        session_id = request.query.get("session", "default")
        filter_pattern = request.query.get("filter")

        # Register filter for this session (idempotent)
        if filter_pattern:
            register_session_filter(session_id, filter_pattern)

        # Read request body
        body = await request.read()

        # Check if this is a tools/list request
        is_list_tools = is_tools_list_request(body)

        # Build target URL (strip our query params, keep path)
        target_url = f"{fastmcp_base}{request.path}"

        # Forward request to FastMCP
        async with ClientSession(timeout=timeout) as client:
            # Copy headers (exclude host and content-length which will be recomputed)
            headers = {
                k: v for k, v in request.headers.items()
                if k.lower() not in ("host", "content-length", "transfer-encoding")
            }

            try:
                async with client.request(
                    method=request.method,
                    url=target_url,
                    data=body,
                    headers=headers
                ) as resp:
                    response_body = await resp.read()

                    # Filter tools/list response if this session has a filter
                    if is_list_tools and get_session_filter(session_id):
                        response_body = filter_tools_response(session_id, response_body)

                    # Return response with same status and content type
                    return web.Response(
                        body=response_body,
                        status=resp.status,
                        content_type=resp.content_type or "application/json"
                    )

            except Exception as e:
                mcp_log(f"[Proxy] Error forwarding to FastMCP: {e}")
                return web.Response(
                    body=json.dumps({"error": str(e)}).encode(),
                    status=502,
                    content_type="application/json"
                )

    # Periodic cleanup task
    async def cleanup_task():
        """Periodically clean up stale sessions."""
        while True:
            await asyncio.sleep(600)  # Every 10 minutes
            cleanup_stale_sessions()

    # Create and start app
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", proxy_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", proxy_port)
    await site.start()

    mcp_log(f"[Proxy] Filter Proxy running on port {proxy_port} -> FastMCP:{fastmcp_port}")

    # Start cleanup task
    cleanup = asyncio.create_task(cleanup_task())

    try:
        # Run forever
        await asyncio.Event().wait()
    finally:
        cleanup.cancel()
        await runner.cleanup()


# =============================================================================
# API for external access (used by mcp_proxy_manager)
# =============================================================================

def get_active_sessions() -> dict:
    """Get info about active sessions with filters.

    Returns:
        Dict mapping session_id to filter pattern
    """
    with _session_filters_lock:
        return dict(_session_filters)


def get_session_count() -> int:
    """Get number of active sessions.

    Returns:
        Count of sessions with registered filters
    """
    with _session_filters_lock:
        return len(_session_filters)


# =============================================================================
# Main
# =============================================================================

def main():
    """Run the filter proxy from command line."""
    parser = argparse.ArgumentParser(description="MCP Filter Proxy")
    parser.add_argument("--proxy-port", type=int, default=DEFAULT_PROXY_PORT,
                        help=f"External port for Claude SDK (default: {DEFAULT_PROXY_PORT})")
    parser.add_argument("--fastmcp-port", type=int, default=DEFAULT_FASTMCP_PORT,
                        help=f"Internal port for FastMCP (default: {DEFAULT_FASTMCP_PORT})")
    args = parser.parse_args()

    mcp_log(f"[Proxy] Starting MCP Filter Proxy...")
    mcp_log(f"[Proxy] External: localhost:{args.proxy_port}")
    mcp_log(f"[Proxy] Internal: localhost:{args.fastmcp_port}")

    asyncio.run(run_proxy(args.proxy_port, args.fastmcp_port))


if __name__ == "__main__":
    main()
