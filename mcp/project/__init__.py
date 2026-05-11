# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Project MCP - Run Claude Code CLI in other projects.

Allows agents to leverage Claude Code's capabilities in external projects,
each with their own CLAUDE.md context and knowledge base.
"""

import subprocess
import os
import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config

mcp = FastMCP("project")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "terminal",
    "color": "#673ab7"
}

# Integration schema for Settings UI
INTEGRATION_SCHEMA = {
    "name": "Projekt",
    "icon": "terminal",
    "color": "#673ab7",
    "config_key": None,  # Keine Config noetig
    "auth_type": "none",
}


def is_configured() -> bool:
    """Prüft ob Project-MCP verfügbar ist.

    Project benötigt Claude CLI, ist aber lokal.
    Kann über project.enabled deaktiviert werden.
    """
    config = load_config()
    mcp_config = config.get("project", {})

    if mcp_config.get("enabled") is False:
        return False

    return True


@mcp.tool()
def project_ask(prompt: str, project_path: str, timeout: int = 180) -> str:
    """
    Run Claude Code CLI in another project and return the response.

    The target project should have its own CLAUDE.md with instructions.
    Claude Code will use that project's context, knowledge, and tools.

    Args:
        prompt: The question or task for Claude Code
        project_path: Full path to the project directory (e.g. "E:/support-docs")
        timeout: Max seconds to wait (default: 180)

    Returns:
        Claude Code's response text
    """
    # Validate path exists
    if not os.path.isdir(project_path):
        return f"Error: Project path does not exist: {project_path}"

    # Check for CLAUDE.md (optional but recommended)
    claude_md = os.path.join(project_path, "CLAUDE.md")
    has_claude_md = os.path.isfile(claude_md)

    # Log for debugging
    import shutil
    claude_path = shutil.which("claude")
    if not claude_path:
        return "Error: 'claude' CLI not found in PATH. Check that Claude Code is installed and PATH is set."

    try:
        result = subprocess.run(
            [
                claude_path,  # Use full path instead of just "claude"
                "-p", prompt,
                "--output-format", "text",
                "--verbose"
            ],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace"
        )

        output = result.stdout.strip()

        # Include stderr if there were issues
        if result.returncode != 0 and result.stderr:
            output += f"\n\n[stderr]: {result.stderr.strip()}"

        if not output:
            return f"Claude Code returned empty response (exit code: {result.returncode})"

        return output

    except subprocess.TimeoutExpired:
        return f"Error: Claude Code timed out after {timeout} seconds"
    except FileNotFoundError as e:
        return f"Error: 'claude' CLI not found at '{claude_path}': {str(e)}"
    except Exception as e:
        return f"Error running Claude Code: {type(e).__name__}: {str(e)}"


@mcp.tool()
def project_ask_with_context(
    prompt: str,
    project_path: str,
    context: str = "",
    timeout: int = 180
) -> str:
    """
    Run Claude Code with additional context prepended to the prompt.

    Useful for passing email content, ticket details, or other context
    that should be considered alongside the project's knowledge.

    Args:
        prompt: The question or task for Claude Code
        project_path: Full path to the project directory
        context: Additional context to include (e.g. email content)
        timeout: Max seconds to wait (default: 180)

    Returns:
        Claude Code's response text
    """
    full_prompt = prompt
    if context:
        full_prompt = f"""Context:
{context}

Task:
{prompt}"""

    return project_ask(full_prompt, project_path, timeout)


@mcp.tool()
def project_list_knowledge(project_path: str) -> str:
    """
    List the knowledge files available in another project.

    Args:
        project_path: Full path to the project directory

    Returns:
        List of knowledge files or error message
    """
    if not os.path.isdir(project_path):
        return f"Error: Project path does not exist: {project_path}"

    knowledge_dir = os.path.join(project_path, "knowledge")

    if not os.path.isdir(knowledge_dir):
        return f"No knowledge/ directory found in {project_path}"

    files = []
    for f in os.listdir(knowledge_dir):
        if f.endswith(".md"):
            filepath = os.path.join(knowledge_dir, f)
            size = os.path.getsize(filepath)
            files.append(f"- {f} ({size:,} bytes)")

    if not files:
        return "No .md files found in knowledge/"

    return f"Knowledge files in {project_path}:\n" + "\n".join(files)


@mcp.tool()
def project_check(project_path: str) -> str:
    """
    Check if a project is set up for Claude Code.

    Args:
        project_path: Full path to the project directory

    Returns:
        Project status and available resources
    """
    if not os.path.isdir(project_path):
        return f"Error: Path does not exist: {project_path}"

    status = [f"Project: {project_path}"]

    # Check CLAUDE.md
    claude_md = os.path.join(project_path, "CLAUDE.md")
    if os.path.isfile(claude_md):
        size = os.path.getsize(claude_md)
        status.append(f"✓ CLAUDE.md ({size:,} bytes)")
    else:
        status.append("✗ No CLAUDE.md found")

    # Check knowledge/
    knowledge_dir = os.path.join(project_path, "knowledge")
    if os.path.isdir(knowledge_dir):
        md_files = [f for f in os.listdir(knowledge_dir) if f.endswith(".md")]
        status.append(f"✓ knowledge/ ({len(md_files)} .md files)")
    else:
        status.append("✗ No knowledge/ directory")

    # Check for MCP servers
    mcp_dir = os.path.join(project_path, "mcp")
    if os.path.isdir(mcp_dir):
        mcp_files = [f for f in os.listdir(mcp_dir) if f.endswith("_mcp.py")]
        status.append(f"✓ mcp/ ({len(mcp_files)} servers)")

    # Check for agents
    agents_dir = os.path.join(project_path, "agents")
    if os.path.isdir(agents_dir):
        agent_files = [f for f in os.listdir(agents_dir) if f.endswith(".md")]
        status.append(f"✓ agents/ ({len(agent_files)} agents)")

    return "\n".join(status)


if __name__ == "__main__":
    mcp.run()
