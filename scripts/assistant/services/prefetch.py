# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Pre-fetch service for agent data requirements.

This service allows agents to declare data dependencies in their frontmatter
that are fetched BEFORE the agent starts, reducing perceived latency.

Example agent frontmatter:
    {
        "prefetch": ["selected_email"]
    }

The email will be fetched and injected into {{PREFETCH.email}} placeholder
before the AI processes the agent prompt.
"""

import asyncio
from typing import Any
from ai_agent import log

# System logging for debugging
try:
    import ai_agent
    system_log = ai_agent.system_log
except (ImportError, AttributeError):
    system_log = lambda msg: print(msg)


# =============================================================================
# Prefetch Registry
# =============================================================================
# Maps prefetch type names to (mcp_server, tool_name, result_key)

PREFETCH_REGISTRY = {
    # Outlook COM (local)
    "selected_email": ("outlook", "outlook_get_selected_email", "email"),
    "selected_emails": ("outlook", "outlook_get_selected_emails", "emails"),

    # Microsoft Graph (server-side)
    "graph_selected_email": ("msgraph", "graph_get_email", "email"),

    # Clipboard
    "clipboard": ("clipboard", "clipboard_get_clipboard", "clipboard"),
}


# =============================================================================
# Formatters
# =============================================================================
# Convert raw tool results into readable text for prompt injection

def _format_email(result: Any) -> str:
    """Format email result as readable text."""
    if not result:
        return "[Keine E-Mail ausgewählt]"

    if isinstance(result, str):
        # Already formatted or error message
        return result

    if isinstance(result, dict):
        parts = []

        # Header fields
        if result.get("subject"):
            parts.append(f"**Betreff:** {result['subject']}")
        if result.get("sender") or result.get("from"):
            sender = result.get("sender") or result.get("from")
            parts.append(f"**Von:** {sender}")
        if result.get("to"):
            parts.append(f"**An:** {result['to']}")
        if result.get("received") or result.get("date"):
            date = result.get("received") or result.get("date")
            parts.append(f"**Datum:** {date}")
        if result.get("cc"):
            parts.append(f"**CC:** {result['cc']}")

        # Add separator before body
        if parts:
            parts.append("")

        # Body content
        body = result.get("body") or result.get("content") or ""
        if body:
            parts.append(body)

        # Attachments
        attachments = result.get("attachments") or []
        if attachments:
            parts.append("")
            parts.append(f"**Anhänge:** {len(attachments)}")
            for att in attachments[:5]:  # Limit to first 5
                if isinstance(att, dict):
                    parts.append(f"- {att.get('name', 'unbekannt')}")
                else:
                    parts.append(f"- {att}")

        return "\n".join(parts)

    return str(result)


def _format_emails(results: Any) -> str:
    """Format multiple emails as readable text."""
    if not results:
        return "[Keine E-Mails ausgewählt]"

    if isinstance(results, str):
        return results

    if isinstance(results, list):
        formatted = []
        for i, email in enumerate(results, 1):
            formatted.append(f"### E-Mail {i}")
            formatted.append(_format_email(email))
            formatted.append("")
        return "\n".join(formatted)

    return str(results)


def _format_result(key: str, result: Any) -> str:
    """Format prefetch result based on type."""
    if key == "email":
        return _format_email(result)
    elif key == "emails":
        return _format_emails(result)
    elif key == "clipboard":
        if not result:
            return "[Zwischenablage leer]"
        return str(result)
    else:
        # Default: convert to string
        if isinstance(result, dict):
            import json
            return json.dumps(result, ensure_ascii=False, indent=2)
        return str(result) if result else f"[{key} ist leer]"


# =============================================================================
# Prefetch Execution
# =============================================================================

async def _fetch_one(mcp: str, tool: str, key: str) -> dict:
    """Fetch single item directly from MCP tool (bypasses AI).

    Args:
        mcp: MCP server name (for logging)
        tool: Full tool name (e.g., "outlook_get_selected_email")
        key: Result key for the returned dict

    Returns:
        Dict with {key: formatted_result}
    """
    try:
        from ai_agent.tool_bridge import execute_tool

        log(f"[Prefetch] Fetching {key} via {tool}...")
        start = asyncio.get_event_loop().time()

        # Execute tool in thread pool to not block
        result = await asyncio.to_thread(execute_tool, tool, {}, True)  # skip_logging=True

        elapsed = (asyncio.get_event_loop().time() - start) * 1000
        log(f"[Prefetch] {key} fetched in {elapsed:.0f}ms")

        # Format result for prompt injection
        formatted = _format_result(key, result)
        return {key: formatted}

    except Exception as e:
        system_log(f"[Prefetch] Error fetching {key}: {e}")
        log(f"[Prefetch] Error fetching {key}: {e}")
        return {key: f"[Fehler beim Laden: {e}]"}


async def execute_prefetch(prefetch_types: list[str]) -> dict[str, Any]:
    """Execute prefetch operations in parallel.

    Args:
        prefetch_types: List of prefetch type names (e.g., ["selected_email"])

    Returns:
        Dict mapping result keys to formatted values
        Example: {"email": "Subject: ...\nFrom: ..."}
    """
    if not prefetch_types:
        return {}

    log(f"[Prefetch] Starting prefetch for: {prefetch_types}")
    start = asyncio.get_event_loop().time()

    results = {}
    tasks = []

    for ptype in prefetch_types:
        if ptype in PREFETCH_REGISTRY:
            mcp, tool, key = PREFETCH_REGISTRY[ptype]
            tasks.append(_fetch_one(mcp, tool, key))
        else:
            log(f"[Prefetch] Unknown prefetch type: {ptype}")
            results[ptype] = f"[Unbekannter Prefetch-Typ: {ptype}]"

    if tasks:
        # Execute all fetches in parallel
        fetched = await asyncio.gather(*tasks, return_exceptions=True)

        for item in fetched:
            if isinstance(item, dict):
                results.update(item)
            elif isinstance(item, Exception):
                system_log(f"[Prefetch] Task failed: {item}")

    elapsed = (asyncio.get_event_loop().time() - start) * 1000
    log(f"[Prefetch] Completed {len(results)} item(s) in {elapsed:.0f}ms")

    return results


def execute_prefetch_sync(prefetch_types: list[str]) -> dict[str, Any]:
    """Synchronous wrapper for execute_prefetch.

    Use this when not in an async context.
    """
    if not prefetch_types:
        return {}

    try:
        # Try to get existing event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in async context - create new loop in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, execute_prefetch(prefetch_types))
                return future.result(timeout=30)
        else:
            return loop.run_until_complete(execute_prefetch(prefetch_types))
    except RuntimeError:
        # No event loop - create new one
        return asyncio.run(execute_prefetch(prefetch_types))
