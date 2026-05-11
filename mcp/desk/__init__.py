#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
DeskAgent MCP Server
====================
MCP server for DeskAgent system operations and agent control.

Tools:
- desk_restart - Restart the DeskAgent application
- desk_get_status - Get current DeskAgent status and version
- desk_get_agent_log - Read the last agent execution log
- desk_get_mcp_log - Read the last N lines of the system log
- desk_list_agents - List all available agents
- desk_run_agent - Start an agent with optional inputs
- desk_add_agent_config - Add a new agent entry to agents.json
- desk_remove_agent_config - Remove an agent entry from agents.json
- desk_debug_discovery_paths - Debug tool for agent-tool discovery
- desk_list_agent_tools - List all auto-discovered agent tools
- desk_setup_claude_desktop - Configure Claude Desktop to use DeskAgent as MCP Hub
- desk_check_claude_desktop - Check if DeskAgent is configured in Claude Desktop
- desk_remove_claude_desktop - Remove DeskAgent from Claude Desktop config
- desk_setup_claude_code - Register DeskAgent MCP in Claude Code
- <agent_name> - Auto-discovered agent tools (e.g., process_invoices, classify_emails)

Agent-as-Tool Architecture:
---------------------------
Agents with a `tool` definition in their frontmatter are automatically registered
as MCP tools with structured parameters. See docs/agent-as-tool-architecture.md
"""

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests
from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config, mcp_log, get_logs_dir, get_task_context

# Claude Desktop / Claude Code integration
try:
    from desk.claude_desktop import (
        desk_setup_claude_desktop as _desk_setup_claude_desktop,
        desk_check_claude_desktop as _desk_check_claude_desktop,
        desk_remove_claude_desktop as _desk_remove_claude_desktop,
        desk_setup_claude_code as _desk_setup_claude_code,
    )
except ImportError as e:
    mcp_log(f"[desk] Claude Desktop integration not available: {e}")

    async def _desk_setup_claude_desktop(**kwargs):
        return f"Claude Desktop integration not available: {e}"

    async def _desk_check_claude_desktop(**kwargs):
        return f"Claude Desktop integration not available: {e}"

    async def _desk_remove_claude_desktop(**kwargs):
        return f"Claude Desktop integration not available: {e}"

    async def _desk_setup_claude_code(**kwargs):
        return f"Claude Desktop integration not available: {e}"

# Project paths
# __file__ = deskagent/mcp/desk/__init__.py
# .parent = deskagent/mcp/desk/
# .parent.parent = deskagent/mcp/
# .parent.parent.parent = deskagent/
DESKAGENT_DIR = Path(__file__).parent.parent.parent  # deskagent/
PROJECT_DIR = DESKAGENT_DIR.parent  # User-Space (aiassistant/)

# DeskAgent API base URL
DESKAGENT_API = "http://localhost:8765"

# Read-only tools that only retrieve data (for tool_mode: "read_only")
READ_ONLY_TOOLS = {
    "desk_get_status",
    "desk_get_agent_log",
    "desk_get_mcp_log",
    "desk_get_history",
    "desk_get_session",
    "desk_get_last_session",
    "desk_get_history_stats",
    "desk_list_agents",
    "desk_list_agent_tools",
    "desk_debug_discovery_paths",
    "desk_check_claude_desktop",
}

# Destructive tools that perform system actions
DESTRUCTIVE_TOOLS = {
    "desk_restart",
    "desk_run_agent",
    "desk_run_agent_sync",
    "desk_add_agent_config",
    "desk_remove_agent_config",
    "desk_setup_claude_desktop",
    "desk_remove_claude_desktop",
    "desk_setup_claude_code",
}


def _debug_log(msg: str):
    """Write debug message directly to file for MCP subprocess debugging."""
    try:
        # Use paths module to get correct workspace directory (respects CLI overrides)
        log_file = get_logs_dir() / "mcp_discovery.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            f.write(f"[{timestamp}] {msg}\n")
    except Exception as e:
        # Write error to fallback location
        try:
            fallback = Path(__file__).parent / "discovery_error.txt"
            with open(fallback, "a") as f:
                f.write(f"ERROR: {e}\n")
        except Exception:
            pass


# Immediately log on module load to verify the function works
_debug_log("=== MCP Module Loaded ===")

# Initialize FastMCP server
mcp = FastMCP("deskagent")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "smart_toy",
    "color": "#2196F3"
}

# Integration schema for Settings UI
INTEGRATION_SCHEMA = {
    "name": "DeskAgent",
    "icon": "smart_toy",
    "color": "#2196F3",
    "config_key": None,  # Keine Config noetig
    "auth_type": "none",
}

def is_configured() -> bool:
    """DeskAgent MCP is always available."""
    config = load_config()
    mcp_config = config.get("deskagent", {})

    if mcp_config.get("enabled") is False:
        return False

    return True


@mcp.tool()
def desk_restart() -> str:
    """
    Restart the DeskAgent application.

    This will stop the current instance and start a new one.
    The response will be sent before the restart happens.

    Returns:
        Success message or error description
    """
    try:
        mcp_log("[deskagent_mcp] Requesting DeskAgent restart...")

        response = requests.post(
            f"{DESKAGENT_API}/restart",
            timeout=5
        )

        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                mcp_log("[deskagent_mcp] Restart request accepted")
                return "SUCCESS: DeskAgent wird neu gestartet. Die Anwendung startet in wenigen Sekunden automatisch neu."
            else:
                return f"ERROR: Restart fehlgeschlagen - {result.get('message', 'Unknown error')}"
        else:
            return f"ERROR: HTTP {response.status_code} - {response.text}"

    except requests.exceptions.ConnectionError:
        return "ERROR: Keine Verbindung zu DeskAgent. Ist die Anwendung gestartet?"
    except requests.exceptions.Timeout:
        return "ERROR: Timeout bei der Verbindung zu DeskAgent."
    except Exception as e:
        mcp_log(f"[deskagent_mcp] Restart error: {e}")
        return f"ERROR: {str(e)}"


@mcp.tool()
def desk_get_status() -> str:
    """
    Get the current DeskAgent status and version information.

    Returns:
        Status text with version, build and running state
    """
    try:
        response = requests.get(
            f"{DESKAGENT_API}/version",
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()
            return (
                f"DeskAgent Status:\n"
                f"- Version: {data.get('version', 'unknown')}\n"
                f"- Build: {data.get('build', 'unknown')}\n"
                f"- Status: Running"
            )
        else:
            return f"ERROR: HTTP {response.status_code}"

    except requests.exceptions.ConnectionError:
        return "ERROR: DeskAgent ist nicht erreichbar. Ist die Anwendung gestartet?"
    except Exception as e:
        return f"ERROR: {str(e)}"


# === Log Reading Tools ===
# Use get_logs_dir() which respects workspace configuration and env vars
LOGS_DIR = get_logs_dir()


@mcp.tool()
def desk_get_agent_log() -> str:
    """
    Read the last agent execution log.

    Returns the content of agent_latest.txt which contains:
    - Agent name, task, model, success/error status
    - Token usage and cost
    - Tool calls made during execution
    - Full prompt and response

    Returns:
        Log content or error message
    """
    log_file = LOGS_DIR / "agent_latest.txt"

    if not log_file.exists():
        return "ERROR: No agent log found. Run an agent first."

    try:
        content = log_file.read_text(encoding="utf-8")
        # Truncate if too long (max 50KB for MCP response)
        if len(content) > 50000:
            content = content[:50000] + "\n\n... (truncated, file too large)"
        return content
    except Exception as e:
        return f"ERROR: Could not read agent log: {e}"


@mcp.tool()
def desk_get_mcp_log(lines: int = 100) -> str:
    """
    Read the last N lines of the system log.

    The system log contains:
    - HTTP requests and responses
    - Agent startup and completion
    - Error messages and stack traces
    - MCP tool calls

    Args:
        lines: Number of lines to return (default: 100, max: 1000)

    Returns:
        Last N lines of system.log or error message
    """
    log_file = LOGS_DIR / "system.log"

    if not log_file.exists():
        return "ERROR: No system log found. Is DeskAgent running?"

    # Clamp lines to reasonable range
    lines = max(10, min(lines, 1000))

    try:
        content = log_file.read_text(encoding="utf-8")
        all_lines = content.splitlines()

        if len(all_lines) <= lines:
            return content

        # Return last N lines
        result_lines = all_lines[-lines:]
        return f"... (showing last {lines} of {len(all_lines)} lines)\n\n" + "\n".join(result_lines)
    except Exception as e:
        return f"ERROR: Could not read system log: {e}"


# === History Tools (SQLite Database) ===

@mcp.tool()
def desk_get_history(limit: int = 20, agent: str = "") -> str:
    """
    Get agent execution history from database.

    Returns structured session data including:
    - Session ID, agent name, backend, model
    - Status (active/completed)
    - Token usage and cost
    - Preview of the conversation
    - Timestamps

    Args:
        limit: Maximum number of sessions to return (default: 20, max: 100)
        agent: Filter by agent name (optional). Example: "reply_email", "daily_check"

    Returns:
        JSON list of sessions or error message
    """
    try:
        # Clamp limit
        limit = max(1, min(limit, 100))

        # Build URL with params
        url = f"{DESKAGENT_API}/history/sessions?limit={limit}"
        if agent and agent.strip():
            url += f"&agent={agent.strip()}"

        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            sessions = data.get("sessions", [])

            if not sessions:
                if agent:
                    return f"Keine Sessions für Agent '{agent}' gefunden."
                return "Keine Sessions in der History."

            return json.dumps({
                "count": len(sessions),
                "total": data.get("total", len(sessions)),
                "sessions": sessions
            }, ensure_ascii=False, indent=2)
        else:
            return f"ERROR: HTTP {response.status_code}"

    except requests.exceptions.ConnectionError:
        return "ERROR: DeskAgent ist nicht erreichbar."
    except Exception as e:
        return f"ERROR: {str(e)}"


@mcp.tool()
def desk_get_session(session_id: str) -> str:
    """
    Get a specific session with all conversation turns.

    Returns full session details including:
    - All user/assistant message turns
    - Token usage per turn
    - Cost per turn
    - Timestamps

    Args:
        session_id: The session ID (e.g., "s_20260112_143025_001")

    Returns:
        JSON with session and turns or error message
    """
    try:
        response = requests.get(
            f"{DESKAGENT_API}/history/sessions/{session_id}",
            timeout=10
        )

        if response.status_code == 200:
            session = response.json()
            return json.dumps(session, ensure_ascii=False, indent=2)
        elif response.status_code == 404:
            return f"ERROR: Session '{session_id}' nicht gefunden."
        else:
            return f"ERROR: HTTP {response.status_code}"

    except requests.exceptions.ConnectionError:
        return "ERROR: DeskAgent ist nicht erreichbar."
    except Exception as e:
        return f"ERROR: {str(e)}"


@mcp.tool()
def desk_get_last_session(agent: str) -> str:
    """
    Get the last session of a specific agent with all turns.

    Convenience function that combines desk_get_history + desk_get_session
    to quickly get the most recent execution of an agent.

    Args:
        agent: Agent name (e.g., "reply_email", "daily_check", "create_offer")

    Returns:
        JSON with full session and turns or error message
    """
    try:
        # First get the last session ID for this agent
        url = f"{DESKAGENT_API}/history/sessions?limit=1&agent={agent.strip()}"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            return f"ERROR: HTTP {response.status_code}"

        data = response.json()
        sessions = data.get("sessions", [])

        if not sessions:
            return f"Keine Sessions für Agent '{agent}' gefunden."

        # Now get the full session with turns
        session_id = sessions[0]["id"]
        return desk_get_session(session_id)

    except requests.exceptions.ConnectionError:
        return "ERROR: DeskAgent ist nicht erreichbar."
    except Exception as e:
        return f"ERROR: {str(e)}"


@mcp.tool()
def desk_get_history_stats() -> str:
    """
    Get overall history statistics.

    Returns:
    - Total number of sessions
    - Active vs completed sessions
    - Total turns (messages)
    - Total tokens used
    - Total cost in USD

    Returns:
        JSON with statistics or error message
    """
    try:
        response = requests.get(
            f"{DESKAGENT_API}/history/stats",
            timeout=10
        )

        if response.status_code == 200:
            stats = response.json()
            return json.dumps(stats, ensure_ascii=False, indent=2)
        else:
            return f"ERROR: HTTP {response.status_code}"

    except requests.exceptions.ConnectionError:
        return "ERROR: DeskAgent ist nicht erreichbar."
    except Exception as e:
        return f"ERROR: {str(e)}"


@mcp.tool()
def desk_list_agents() -> str:
    """
    List all available agents in DeskAgent.

    Returns:
        JSON list of agents with name and description
    """
    try:
        response = requests.get(
            f"{DESKAGENT_API}/agents",
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            agents = data.get("agents", [])

            if not agents:
                return "Keine Agents gefunden."

            result_lines = ["Verfügbare Agents:", ""]
            for agent in agents:
                name = agent.get("name", "unknown")
                desc = agent.get("description", "")
                has_inputs = agent.get("has_inputs", False)
                input_marker = " [mit Inputs]" if has_inputs else ""
                result_lines.append(f"- {name}: {desc}{input_marker}")

            return "\n".join(result_lines)
        else:
            return f"ERROR: HTTP {response.status_code}"

    except requests.exceptions.ConnectionError:
        return "ERROR: DeskAgent ist nicht erreichbar."
    except Exception as e:
        return f"ERROR: {str(e)}"


@mcp.tool()
def desk_run_agent(agent_name: str, inputs: str = "", initial_prompt: str = "") -> str:
    """
    Start an agent task in DeskAgent.

    Args:
        agent_name: Name of the agent to run (e.g. "daily_check", "create_offer")
        inputs: Optional JSON string with input parameters.
                Example: '{"customer_name": "Firma XY", "amount": 1500}'
                Leave empty if agent has no inputs.
        initial_prompt: Optional description of what triggered this agent.
                This will be shown in the History panel as the user input.
                Example: "Reply to email from customer about pricing"
                If empty, the agent name will be used.

    Returns:
        Task ID for tracking or error message
    """
    try:
        mcp_log(f"[deskagent_mcp] Starting agent: {agent_name}")

        # Get parent task_id from current TaskContext (if running inside another agent)
        parent_task_id = None
        ctx = get_task_context()
        if ctx and ctx.get("task_id"):
            parent_task_id = ctx["task_id"]
            mcp_log(f"[deskagent_mcp] Parent task: {parent_task_id}")

        # Parse inputs if provided
        input_data = {}
        if inputs and inputs.strip():
            try:
                input_data = json.loads(inputs)
            except json.JSONDecodeError as e:
                return f"ERROR: Invalid JSON in inputs parameter: {e}"

        # Build initial prompt for History display
        # If not provided, generate from agent name and inputs
        display_prompt = initial_prompt.strip() if initial_prompt else ""
        if not display_prompt:
            # Auto-generate from agent name
            display_prompt = f"Workflow: {agent_name}"
            if input_data:
                # Add brief input summary
                input_summary = ", ".join(f"{k}={v}" for k, v in list(input_data.items())[:3])
                if len(input_data) > 3:
                    input_summary += ", ..."
                display_prompt += f" ({input_summary})"

        # Build request payload
        payload = {
            "inputs": input_data,
            "triggered_by": "api",  # Mark as API-triggered (MCP remote control)
            "initial_prompt": display_prompt  # For History display
        }
        if parent_task_id:
            payload["parent_task_id"] = parent_task_id

        response = requests.post(
            f"{DESKAGENT_API}/agent/{agent_name}",
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            task_id = data.get("task_id")
            if task_id:
                mcp_log(f"[deskagent_mcp] Agent started with task_id: {task_id}")
                return (
                    f"SUCCESS: Agent '{agent_name}' gestartet.\n"
                    f"Task-ID: {task_id}\n"
                    f"Der Agent läuft jetzt im Hintergrund."
                )
            else:
                return f"ERROR: Keine Task-ID erhalten - {data}"
        elif response.status_code == 404:
            return f"ERROR: Agent '{agent_name}' nicht gefunden."
        else:
            return f"ERROR: HTTP {response.status_code} - {response.text}"

    except requests.exceptions.ConnectionError:
        return "ERROR: DeskAgent ist nicht erreichbar."
    except requests.exceptions.Timeout:
        return "ERROR: Timeout beim Starten des Agents."
    except Exception as e:
        mcp_log(f"[deskagent_mcp] Error starting agent: {e}")
        return f"ERROR: {str(e)}"


def _resolve_session_id(session: str) -> str:
    """Resolve a session identifier to a session ID.

    Accepts:
    - A session ID directly (starts with "s_")
    - An agent name (looks up the last session)
    - Empty string (falls back to most recent active session)

    Args:
        session: Agent name, session ID, or empty string

    Returns:
        Session ID string, or empty string if not found
    """
    if session and session.startswith("s_"):
        return session

    # Agent name → get last session
    if session:
        try:
            resp = requests.get(
                f"{DESKAGENT_API}/history/sessions",
                params={"limit": 1, "agent": session},
                timeout=10
            )
            if resp.status_code == 200:
                sessions = resp.json().get("sessions", [])
                if sessions:
                    return sessions[0]["id"]
        except Exception:
            pass

    # Fall back to most recent active session
    try:
        resp = requests.get(
            f"{DESKAGENT_API}/history/sessions",
            params={"limit": 1, "status": "active"},
            timeout=10
        )
        if resp.status_code == 200:
            sessions = resp.json().get("sessions", [])
            if sessions:
                return sessions[0]["id"]
    except Exception:
        pass

    return ""


@mcp.tool()
def desk_send_prompt(prompt: str, backend: str = "", session: str = "") -> str:
    """
    Send a follow-up prompt to an existing agent session and wait for the result.

    Use this after desk_run_agent_sync() to send follow-up messages in the same
    conversation context. The AI will have access to the same tools and history.

    Args:
        prompt: The prompt text to send (e.g. "zeig mir die letzten 10 Rechnungen als Chart")
        backend: AI backend to use (e.g. "gemini", "claude_sdk"). If empty, uses session's backend.
        session: Agent name (gets last session) or session ID (e.g. "s_20260212_...").
                 If empty, continues the most recent session.

    Returns:
        AI response text or error message
    """
    # Resolve session ID using shared helper
    session_id = _resolve_session_id(session)

    if not session_id:
        return "ERROR: Keine aktive Session gefunden."

    # Send prompt to session
    payload = {
        "prompt": prompt,
        "continue_context": True,
        "resume_session_id": session_id,
        "triggered_by": "api"
    }
    if backend:
        payload["backend"] = backend

    try:
        response = requests.post(
            f"{DESKAGENT_API}/prompt",
            json=payload,
            timeout=10
        )

        if response.status_code != 200:
            return f"ERROR: HTTP {response.status_code}: {response.text[:300]}"

        data = response.json()
        task_id = data.get("task_id")
        if not task_id:
            return "ERROR: No task_id in response"

        mcp_log(f"[deskagent_mcp] Prompt sent to session {session_id}, task: {task_id}")

    except requests.RequestException as e:
        return f"ERROR: {e}"

    # Poll for result (shared polling function)
    return _poll_for_result(task_id, timeout=120, label=f"Prompt (session: {session_id})")


@mcp.tool()
def desk_run_agent_sync(agent_name: str, inputs: str = "", initial_prompt: str = "",
                        session_name: str = "") -> str:
    """
    Run an agent SYNCHRONOUSLY and wait for the result.

    Unlike desk_run_agent() which starts async and returns task_id,
    this function blocks until the agent completes and returns the actual result.

    Use this in workflows where you need the agent's output before proceeding.

    Args:
        agent_name: Name of the agent to run (e.g. "deskagent_support_reply")
        inputs: Optional JSON string with input parameters.
                Example: '{"message_id": "abc123", "sender": "user@example.com"}'
        initial_prompt: Optional description of what triggered this agent.
                This will be shown in the History panel as the user input.
                If empty, "Workflow: agent_name" will be used.
        session_name: Optional custom name for the History tile.
                If empty, agent_name will be used.
                Example: "Email Auto-Reply" for a workflow.

    Returns:
        Agent result (the AI's response) or error message
    """
    return _run_agent_sync(agent_name, inputs, initial_prompt=initial_prompt,
                           session_name=session_name)


# === Agent Config Management ===

def _get_config_dir() -> Path:
    """Get config directory (user-space preferred, fallback to deskagent)."""
    user_config = PROJECT_DIR / "config"
    if user_config.exists():
        return user_config
    return DESKAGENT_DIR / "config"


@mcp.tool()
def desk_add_agent_config(
    name: str,
    category: str,
    description: str,
    input_desc: str,
    output_desc: str,
    icon: str,
    allowed_mcp: str,
    order: int = 50
) -> str:
    """Fuegt einen neuen Agent-Eintrag zu agents.json hinzu.

    Sicheres Hinzufuegen ohne Encoding-Probleme - die bestehende Datei
    wird gelesen, der neue Eintrag hinzugefuegt und mit korrektem UTF-8 gespeichert.

    Args:
        name: Agent ID in snake_case (z.B. "my_new_agent")
        category: Kategorie (kommunikation, finance, sales, system)
        description: Kurze Beschreibung (1 Satz)
        input_desc: Was der Agent erwartet (z.B. "E-Mail oder Clipboard")
        output_desc: Was der Agent produziert (z.B. "PDF in .temp/")
        icon: Material Icon Name (z.B. "search", "email", "receipt")
        allowed_mcp: MCP-Server Pattern (z.B. "outlook|billomat")
        order: Sortierreihenfolge (default: 50)

    Returns:
        Bestaetigung oder Fehlermeldung
    """
    config_dir = _get_config_dir()
    agents_file = config_dir / "agents.json"

    if not agents_file.exists():
        return f"Error: agents.json not found in {config_dir}"

    try:
        # Read existing config with UTF-8
        content = agents_file.read_text(encoding="utf-8")
        config = json.loads(content)

        # Check if agent already exists
        if name in config.get("agents", {}):
            return f"Error: Agent '{name}' already exists in agents.json"

        # Validate category
        valid_categories = list(config.get("categories", {}).keys())
        if category not in valid_categories:
            return f"Error: Invalid category '{category}'. Valid: {', '.join(valid_categories)}"

        # Create new agent entry
        new_agent = {
            "category": category,
            "description": description,
            "input": input_desc,
            "output": output_desc,
            "ai": "gemini",
            "enabled": True,
            "icon": icon,
            "allowed_mcp": allowed_mcp,
            "order": order
        }

        # Add to agents section
        if "agents" not in config:
            config["agents"] = {}
        config["agents"][name] = new_agent

        # Write back with UTF-8 and ensure_ascii=False to preserve emojis
        new_content = json.dumps(config, indent=2, ensure_ascii=False)
        agents_file.write_text(new_content, encoding="utf-8")

        mcp_log(f"[deskagent_mcp] Added agent '{name}' to agents.json")
        return f"OK: Agent '{name}' added to agents.json\n  Category: {category}\n  Icon: {icon}\n  MCP: {allowed_mcp}"

    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in agents.json: {e}"
    except Exception as e:
        return f"Error adding agent config: {e}"


@mcp.tool()
def desk_remove_agent_config(name: str) -> str:
    """Entfernt einen Agent-Eintrag aus agents.json.

    Sicheres Entfernen ohne Encoding-Probleme - die bestehende Datei
    wird gelesen, der Eintrag entfernt und mit korrektem UTF-8 gespeichert.

    WICHTIG: Loescht NUR den Eintrag in agents.json, NICHT die Agent-Datei selbst!
    Die Agent-Datei muss separat mit delete_file() geloescht werden.

    Args:
        name: Agent ID (z.B. "my_agent" - ohne .md Endung)

    Returns:
        Bestaetigung oder Fehlermeldung
    """
    config_dir = _get_config_dir()
    agents_file = config_dir / "agents.json"

    if not agents_file.exists():
        return f"Error: agents.json not found in {config_dir}"

    try:
        # Read existing config with UTF-8
        content = agents_file.read_text(encoding="utf-8")
        config = json.loads(content)

        # Check if agent exists
        if name not in config.get("agents", {}):
            # Maybe it's a skill?
            if name in config.get("skills", {}):
                del config["skills"][name]
                new_content = json.dumps(config, indent=2, ensure_ascii=False)
                agents_file.write_text(new_content, encoding="utf-8")
                mcp_log(f"[deskagent_mcp] Removed skill '{name}' from agents.json")
                return f"OK: Skill '{name}' removed from agents.json"
            return f"Error: Agent '{name}' not found in agents.json"

        # Remove the agent entry
        del config["agents"][name]

        # Write back with UTF-8 and ensure_ascii=False to preserve emojis
        new_content = json.dumps(config, indent=2, ensure_ascii=False)
        agents_file.write_text(new_content, encoding="utf-8")

        mcp_log(f"[deskagent_mcp] Removed agent '{name}' from agents.json")
        return f"OK: Agent '{name}' removed from agents.json\n\nHinweis: Die Agent-Datei ({name}.md) muss separat geloescht werden!"

    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in agents.json: {e}"
    except Exception as e:
        return f"Error removing agent config: {e}"


# === Claude Desktop / Claude Code Integration ===

@mcp.tool()
def desk_setup_claude_desktop(transport: str = "stdio") -> str:
    """
    Configure Claude Desktop to use DeskAgent as MCP Hub.

    This writes the DeskAgent MCP entry into Claude Desktop's config file.
    Only MCPs with configured API keys (in apis.json) will be available.

    Args:
        transport: "stdio" (standalone, no running DeskAgent needed) or
                   "http" (requires running DeskAgent on port 19001)

    Returns:
        Summary of configuration or error message
    """
    return _desk_setup_claude_desktop(transport)


@mcp.tool()
def desk_check_claude_desktop() -> str:
    """
    Check if DeskAgent is configured in Claude Desktop.

    Reads the Claude Desktop config and reports the current status,
    including transport type, paths, and configured MCPs.

    Returns:
        Status information (configured/not configured, transport, paths)
    """
    return _desk_check_claude_desktop()


@mcp.tool()
def desk_remove_claude_desktop() -> str:
    """
    Remove DeskAgent from Claude Desktop configuration.

    Removes the 'deskagent' entry from mcpServers in the Claude Desktop
    config file. Other MCP servers are not affected.

    Returns:
        Confirmation or error message
    """
    return _desk_remove_claude_desktop()


@mcp.tool()
def desk_setup_claude_code(scope: str = "user") -> str:
    """
    Register DeskAgent MCP in Claude Code.

    Writes the MCP entry to ~/.claude.json (user scope) or
    .mcp.json in the current directory (project scope).

    Args:
        scope: "user" for global config (~/.claude.json) or
               "project" for project-level config (.mcp.json in CWD)

    Returns:
        Summary of configuration or error message
    """
    return _desk_setup_claude_code(scope)


# === Agent-as-Tool Discovery ===

# Store registered agent tools for introspection
REGISTERED_AGENT_TOOLS: Dict[str, Dict[str, Any]] = {}


def _parse_frontmatter(md_file: Path) -> dict:
    """
    Extract JSON frontmatter from markdown file.

    Args:
        md_file: Path to agent markdown file

    Returns:
        Parsed JSON metadata or empty dict
    """
    try:
        content = md_file.read_text(encoding='utf-8')
        match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        mcp_log(f"[deskagent_mcp] JSON error in frontmatter: {md_file.name} - {e}")
    except Exception as e:
        mcp_log(f"[deskagent_mcp] Error parsing frontmatter: {md_file.name} - {e}")
    return {}


def _build_tool_docstring(tool_def: dict) -> str:
    """
    Build a docstring from tool definition for better LLM prompts.

    IMPORTANT: The function signature uses a single 'kwargs' string parameter.
    The docstring must document 'kwargs' as the parameter and explain the JSON format.

    Args:
        tool_def: Tool definition from frontmatter

    Returns:
        Formatted docstring with description and parameters
    """
    lines = [tool_def.get("description", "Run agent")]

    params = tool_def.get("parameters", {})
    if params:
        # Build JSON example showing all parameters
        json_example_parts = []
        for param_name, param_def in params.items():
            param_type = param_def.get("type", "any")
            required = " (required)" if param_def.get("required", False) else ""
            param_desc = param_def.get("description", "")

            # Generate example value based on type
            if param_type == "array":
                json_example_parts.append(f'"{param_name}": [...]')
            elif param_type == "object":
                json_example_parts.append(f'"{param_name}": {{...}}')
            elif param_type == "string":
                json_example_parts.append(f'"{param_name}": "..."')
            elif param_type in ("integer", "number"):
                json_example_parts.append(f'"{param_name}": 0')
            elif param_type == "boolean":
                json_example_parts.append(f'"{param_name}": true')
            else:
                json_example_parts.append(f'"{param_name}": ...')

        # Document the actual kwargs parameter with JSON format
        lines.append("")
        lines.append("Args:")
        json_example = "{" + ", ".join(json_example_parts) + "}"
        lines.append(f"    kwargs: JSON string with parameters (required) [string]")
        lines.append(f"            Format: '{json_example}'")

        # List the logical parameters inside kwargs
        lines.append("")
        lines.append("Parameters in kwargs:")
        for param_name, param_def in params.items():
            param_type = param_def.get("type", "any")
            param_desc = param_def.get("description", "")
            required = " (required)" if param_def.get("required", False) else ""
            lines.append(f"    {param_name}: {param_desc}{required} [{param_type}]")

    returns = tool_def.get("returns", {})
    if returns:
        lines.append("")
        lines.append("Returns:")
        return_type = returns.get("type", "string")
        return_props = returns.get("properties", {})
        if return_props:
            prop_names = ", ".join(return_props.keys())
            lines.append(f"    {return_type} with: {prop_names}")
        else:
            lines.append(f"    {return_type}")

    return "\n".join(lines)


def _parse_kwargs_string(kwargs_str: str) -> dict:
    """
    Parse a kwargs string like "emails=[{...}]" into proper dict.

    Gemini sometimes passes parameters as a single 'kwargs' string instead of
    proper structured parameters. This function handles that case.

    Args:
        kwargs_str: String like "param_name=[...]" or "param_name={...}"

    Returns:
        Parsed dict with actual parameter name and value
    """
    import ast

    # Try to find pattern like "param_name=value"
    match = re.match(r'^(\w+)=(.+)$', kwargs_str.strip(), re.DOTALL)
    if match:
        param_name = match.group(1)
        value_str = match.group(2)

        # Try to parse the value
        try:
            # First try JSON
            value = json.loads(value_str)
            return {param_name: value}
        except json.JSONDecodeError:
            pass

        try:
            # Then try Python literal (for single quotes, tuples, etc.)
            value = ast.literal_eval(value_str)
            return {param_name: value}
        except (ValueError, SyntaxError):
            pass

    # If all else fails, try to parse the whole string as JSON
    try:
        result = json.loads(kwargs_str)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Last resort: try ast.literal_eval on the whole string
    try:
        result = ast.literal_eval(kwargs_str)
        if isinstance(result, dict):
            return result
    except (ValueError, SyntaxError):
        pass

    return {}


def _poll_for_result(task_id: str, timeout: int = 120, label: str = "Task") -> str:
    """
    Poll for task completion with exponential backoff.

    Shared polling logic for desk_run_agent_sync and desk_send_prompt.
    Handles done, error, cancelled, and pending_input statuses.

    Args:
        task_id: The task ID to poll
        timeout: Max wait time in seconds (default: 120)
        label: Label for log messages (e.g., "Agent 'daily_check'")

    Returns:
        Result string on success, JSON error on failure,
        or JSON with pending_input info when dialog is waiting
    """
    import time

    start_time = time.time()
    poll_interval = 0.5  # Start with 500ms

    while time.time() - start_time < timeout:
        try:
            status_response = requests.get(
                f"{DESKAGENT_API}/task/{task_id}/status",
                timeout=5
            )

            if status_response.status_code == 200:
                status_data = status_response.json()
                task_status = status_data.get("status")

                if task_status == "done":
                    result = status_data.get("result", "")
                    mcp_log(f"[deskagent_mcp] {label} completed (task: {task_id})")
                    return result

                elif task_status == "error":
                    error = status_data.get("error", "Unknown error")
                    mcp_log(f"[deskagent_mcp] {label} failed: {error}")
                    return json.dumps({"error": error}, ensure_ascii=False)

                elif task_status == "cancelled":
                    return json.dumps({"error": f"{label} was cancelled"}, ensure_ascii=False)

                elif task_status == "pending_input":
                    # FIX [051]: Agent is waiting for user input (QUESTION_NEEDED dialog)
                    # Return structured info so the caller can handle it
                    greeting = status_data.get("greeting", "")
                    pending = status_data.get("pending_input", {})
                    mcp_log(f"[deskagent_mcp] {label} waiting for user input (task: {task_id})")
                    return json.dumps({
                        "status": "pending_input",
                        "greeting": greeting,
                        "question": pending.get("question", ""),
                        "options": pending.get("options", []),
                        "task_id": task_id
                    }, ensure_ascii=False)

                # Still running - wait and poll again
                time.sleep(poll_interval)
                # Increase poll interval up to 2 seconds
                poll_interval = min(poll_interval * 1.5, 2.0)

            elif status_response.status_code == 404:
                return json.dumps({"error": f"Task {task_id} not found"}, ensure_ascii=False)

        except requests.RequestException as e:
            mcp_log(f"[deskagent_mcp] Polling error: {e}")
            time.sleep(1)

    # Timeout reached
    return json.dumps({
        "error": f"{label} timed out after {timeout}s",
        "task_id": task_id
    }, ensure_ascii=False)


def _run_agent_sync(agent_name: str, inputs_json: str, timeout: int = 300,
                     initial_prompt: str = "", session_name: str = "") -> str:
    """
    Run an agent SYNCHRONOUSLY and wait for the result.

    Unlike run_agent() which starts async and returns task_id,
    this function blocks until the agent completes and returns the actual result.

    Args:
        agent_name: Agent to run
        inputs_json: JSON string with input parameters
        timeout: Max wait time in seconds (default: 5 minutes)
        initial_prompt: Optional description for History display
        session_name: Optional custom name for History tile (instead of agent_name)

    Returns:
        Agent result or error message
    """
    # Get parent task_id from current TaskContext (if running inside another agent)
    parent_task_id = None
    ctx = get_task_context()
    if ctx and ctx.get("task_id"):
        parent_task_id = ctx["task_id"]

    # Parse inputs
    input_data = {}
    if inputs_json and inputs_json.strip():
        try:
            input_data = json.loads(inputs_json)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"}, ensure_ascii=False)

    # Build initial prompt for History display
    display_prompt = initial_prompt.strip() if initial_prompt else ""
    if not display_prompt:
        display_prompt = f"Workflow: {agent_name}"
        if input_data:
            input_summary = ", ".join(f"{k}={v}" for k, v in list(input_data.items())[:3])
            if len(input_data) > 3:
                input_summary += ", ..."
            display_prompt += f" ({input_summary})"

    # Build request payload
    payload = {
        "inputs": input_data,
        "triggered_by": "api",  # MCP remote control
        "initial_prompt": display_prompt
    }
    if parent_task_id:
        payload["parent_task_id"] = parent_task_id
    if session_name:
        payload["session_name"] = session_name

    # Start the agent
    try:
        response = requests.post(
            f"{DESKAGENT_API}/agent/{agent_name}",
            json=payload,
            timeout=10
        )

        if response.status_code != 200:
            return json.dumps({
                "error": f"Failed to start agent: HTTP {response.status_code}",
                "detail": response.text[:500]
            }, ensure_ascii=False)

        data = response.json()
        task_id = data.get("task_id")
        if not task_id:
            return json.dumps({"error": "No task_id in response"}, ensure_ascii=False)

        mcp_log(f"[deskagent_mcp] Agent '{agent_name}' started, waiting for result (task: {task_id})")

    except requests.RequestException as e:
        return json.dumps({"error": f"Request failed: {e}"}, ensure_ascii=False)

    # Poll for result
    return _poll_for_result(task_id, timeout, label=f"Agent '{agent_name}'")


def _create_agent_tool(agent_name: str, tool_def: dict) -> Callable:
    """
    Create a wrapper function for an agent that can be registered as MCP tool.

    The wrapper uses a single 'kwargs' string parameter that contains all
    tool parameters as JSON. This ensures a proper tool schema that Gemini
    can call correctly (avoiding MALFORMED_FUNCTION_CALL errors).

    IMPORTANT: Agent tools run SYNCHRONOUSLY - they block until the sub-agent
    completes and return the actual result (not just a task ID).

    Args:
        agent_name: Internal agent name (file stem)
        tool_def: Tool definition from frontmatter

    Returns:
        Callable function with proper signature and docstring
    """
    params = tool_def.get("parameters", {})
    tool_name = tool_def.get("name", agent_name)

    # Use explicit kwargs: str parameter instead of **kwargs
    # This creates a proper tool schema with one required parameter
    def agent_wrapper(kwargs: str) -> str:
        """Dynamically generated agent wrapper."""

        # Parse JSON kwargs string
        try:
            parsed_kwargs = json.loads(kwargs)
            if not isinstance(parsed_kwargs, dict):
                return json.dumps({
                    "error": "kwargs must be a JSON object",
                    "received": type(parsed_kwargs).__name__,
                    "hint": "Pass as JSON object: {\"param\": value}"
                }, ensure_ascii=False)
        except json.JSONDecodeError as e:
            # Try legacy format: param_name=[...] or param_name={...}
            mcp_log(f"[deskagent_mcp] JSON parse failed, trying legacy format: {kwargs[:100]}...")
            parsed_kwargs = _parse_kwargs_string(kwargs)
            if not parsed_kwargs:
                return json.dumps({
                    "error": f"Failed to parse kwargs: {str(e)}",
                    "received": kwargs[:200],
                    "hint": "Pass as JSON: {\"emails\": [...], \"param\": value}"
                }, ensure_ascii=False)
            mcp_log(f"[deskagent_mcp] Legacy format parsed: {list(parsed_kwargs.keys())}")

        # Validate required parameters
        missing = []
        for param_name, param_def in params.items():
            if param_def.get("required", False) and param_name not in parsed_kwargs:
                missing.append(param_name)

        if missing:
            return json.dumps({
                "error": f"Missing required parameter(s): {', '.join(missing)}",
                "tool": tool_name,
                "agent": agent_name,
                "received_params": list(parsed_kwargs.keys()),
                "required_params": [p for p, d in params.items() if d.get("required")]
            }, ensure_ascii=False)

        # Convert kwargs to JSON inputs
        inputs_json = json.dumps(parsed_kwargs, ensure_ascii=False)

        mcp_log(f"[deskagent_mcp] Agent tool '{tool_name}' -> running '{agent_name}' SYNC...")

        # Run agent SYNCHRONOUSLY and return actual result
        return _run_agent_sync(agent_name, inputs_json)

    # Set function metadata for MCP
    agent_wrapper.__name__ = tool_name
    agent_wrapper.__doc__ = _build_tool_docstring(tool_def)

    return agent_wrapper


def _register_agent_tools() -> int:
    """
    Scan agents/ folders and register agents with tool definitions as MCP tools.

    Scans both:
    - DESKAGENT_DIR/agents/ (system agents - distribution)
    - PROJECT_DIR/agents/ (user agents - customizations)

    This runs on module load and dynamically creates MCP tools from agent frontmatter.

    Returns:
        Number of registered agent tools
    """
    global REGISTERED_AGENT_TOOLS

    _debug_log("=== Agent Tool Discovery Started ===")
    _debug_log(f"DESKAGENT_DIR: {DESKAGENT_DIR}")
    _debug_log(f"PROJECT_DIR: {PROJECT_DIR}")

    # Scan both system and user agents folders
    agents_dirs = [
        DESKAGENT_DIR / "agents",  # System agents (distribution)
        PROJECT_DIR / "agents",     # User agents (customizations)
    ]

    registered_count = 0

    for agents_dir in agents_dirs:
        _debug_log(f"Scanning: {agents_dir}")
        mcp_log(f"[deskagent_mcp] Scanning: {agents_dir}")
        if not agents_dir.exists():
            _debug_log(f"  Directory does not exist, skipping")
            mcp_log(f"[deskagent_mcp]   Directory does not exist, skipping")
            continue

        agent_files = list(agents_dir.glob("*.md"))
        _debug_log(f"  Found {len(agent_files)} .md files")
        mcp_log(f"[deskagent_mcp]   Found {len(agent_files)} .md files")

        for agent_file in sorted(agent_files):
            try:
                _debug_log(f"  Checking: {agent_file.name}")
                metadata = _parse_frontmatter(agent_file)
                _debug_log(f"    Frontmatter keys: {list(metadata.keys()) if metadata else 'EMPTY'}")

                # Skip agents without tool definition
                if "tool" not in metadata:
                    _debug_log(f"    No tool definition, skipping")
                    continue

                _debug_log(f"    FOUND tool definition!")
                mcp_log(f"[deskagent_mcp]   Found tool definition in: {agent_file.name}")

                tool_def = metadata["tool"]
                agent_name = agent_file.stem

                # Validate tool definition
                if not tool_def.get("name"):
                    mcp_log(f"[deskagent_mcp] Skipping {agent_name}: tool.name missing")
                    continue

                if not tool_def.get("description"):
                    mcp_log(f"[deskagent_mcp] Skipping {agent_name}: tool.description missing")
                    continue

                # Create and register wrapper function
                wrapper_func = _create_agent_tool(agent_name, tool_def)

                # Register as MCP tool
                mcp.tool()(wrapper_func)

                # Store for introspection
                REGISTERED_AGENT_TOOLS[tool_def["name"]] = {
                    "agent": agent_name,
                    "tool_def": tool_def,
                    "file": str(agent_file)
                }

                registered_count += 1
                _debug_log(f"    ✓ Registered: {tool_def['name']} -> {agent_name}")
                mcp_log(f"[deskagent_mcp] ✓ Registered agent tool: {tool_def['name']} -> {agent_name}")

            except Exception as e:
                _debug_log(f"    ERROR: {e}")
                mcp_log(f"[deskagent_mcp] Error registering agent {agent_file.name}: {e}")

    _debug_log(f"=== Discovery Complete: {registered_count} tools registered ===")
    if registered_count > 0:
        mcp_log(f"[deskagent_mcp] Registered {registered_count} agent tool(s)")

    return registered_count


@mcp.tool()
def desk_debug_discovery_paths() -> str:
    """Debug tool to show discovery paths and diagnose agent-tool issues."""
    from pathlib import Path
    this_file = Path(__file__)
    info = {
        "this_file": str(this_file),
        "DESKAGENT_DIR": str(DESKAGENT_DIR),
        "PROJECT_DIR": str(PROJECT_DIR),
        "system_agents_dir": str(DESKAGENT_DIR / "agents"),
        "system_agents_exists": (DESKAGENT_DIR / "agents").exists(),
        "user_agents_dir": str(PROJECT_DIR / "agents"),
        "user_agents_exists": (PROJECT_DIR / "agents").exists(),
    }

    # List files in system agents dir
    sys_agents = DESKAGENT_DIR / "agents"
    if sys_agents.exists():
        info["system_agent_files"] = [f.name for f in sys_agents.glob("*.md")]

    # List files in user agents dir
    usr_agents = PROJECT_DIR / "agents"
    if usr_agents.exists():
        info["user_agent_files"] = [f.name for f in usr_agents.glob("*.md")]

    info["registered_tools"] = list(REGISTERED_AGENT_TOOLS.keys())

    return json.dumps(info, indent=2)


@mcp.tool()
def desk_list_agent_tools() -> str:
    """
    List all auto-discovered agent tools.

    Returns:
        JSON list of registered agent tools with their definitions
    """
    if not REGISTERED_AGENT_TOOLS:
        return json.dumps({
            "message": "No agent tools registered",
            "hint": "Add 'tool' definition to agent frontmatter"
        }, ensure_ascii=False)

    tools = []
    for tool_name, info in REGISTERED_AGENT_TOOLS.items():
        tool_def = info["tool_def"]
        tools.append({
            "name": tool_name,
            "agent": info["agent"],
            "description": tool_def.get("description", ""),
            "parameters": list(tool_def.get("parameters", {}).keys())
        })

    return json.dumps({
        "count": len(tools),
        "tools": tools
    }, ensure_ascii=False, indent=2)


# === Auto-Discovery on Module Load ===
_register_agent_tools()


# === Main Entry Point ===

if __name__ == "__main__":
    mcp.run()
