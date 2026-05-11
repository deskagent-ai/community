# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Claude CLI Agent
================
Calls Claude Code CLI for AI tasks with optional MCP tool access.
"""

import shutil
import subprocess
from pathlib import Path
from paths import PROJECT_DIR
from .agent_logging import AgentResponse
from .logging import log


def check_configured(config: dict) -> tuple:
    """
    Check if this backend is properly configured (CLI installed).

    Args:
        config: Backend configuration dict

    Returns:
        Tuple of (is_configured: bool, issue: str or None)
    """
    # First check custom path in config
    custom_path = config.get("path")
    if custom_path:
        if Path(custom_path).exists():
            return True, None
        return False, f"CLI not found at {custom_path}"

    # Check if 'claude' command is available in PATH
    if shutil.which("claude"):
        return True, None

    return False, "Claude CLI not installed"


def call_claude_cli(
    prompt: str,
    config: dict,
    agent_config: dict,
    use_tools: bool = False,
    continue_conversation: bool = False
) -> AgentResponse:
    """
    Calls Claude Code CLI.

    Args:
        prompt: The prompt
        config: Main configuration
        agent_config: Agent-specific configuration
        use_tools: If True, use -p flag for MCP tool access
        continue_conversation: If True, continue last conversation
    """
    claude_path = agent_config.get("path") or config.get("claude_path", "claude")
    timeout = agent_config.get("timeout") or config.get("timeout", 120)

    # Log context summary
    log(f"[Claude CLI] === Context Summary ===")
    log(f"[Claude CLI]   Path: {claude_path}")
    log(f"[Claude CLI]   Timeout: {timeout}s")
    log(f"[Claude CLI]   Tools enabled: {use_tools}")
    log(f"[Claude CLI]   Continue conversation: {continue_conversation}")
    log(f"[Claude CLI]   Prompt length: {len(prompt)} chars")
    log(f"[Claude CLI] =========================")

    try:
        if use_tools:
            # With tool access: Claude can use MCP tools
            # --dangerously-skip-permissions: No interactive confirmation
            # --allowedTools: Explicitly allowed MCP tools
            # --mcp-config: Explicit path to MCP configuration
            allowed_tools = "mcp__outlook__*,mcp__billomat__*"
            mcp_config = str(PROJECT_DIR / ".mcp.json")

            log(f"[Claude CLI] MCP Config: {mcp_config}")

            # Send prompt via stdin (avoids escaping issues)
            cmd = [
                claude_path,
                "--output-format", "text",
                "--dangerously-skip-permissions",
                "--allowedTools", allowed_tools,
                "--mcp-config", mcp_config
            ]
            if continue_conversation:
                cmd.append("--continue")
            log(f"[Claude CLI] Command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                input=prompt,
                cwd=str(PROJECT_DIR),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                shell=True
            )
        else:
            # Without tools: stdin only, text processing
            cmd = [claude_path]
            if continue_conversation:
                cmd.append("--continue")
            result = subprocess.run(
                cmd,
                input=prompt,
                cwd=str(PROJECT_DIR),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                shell=True
            )

        log(f"[Claude CLI] Return code: {result.returncode}")
        log(f"[Claude CLI] Stdout length: {len(result.stdout) if result.stdout else 0}")

        if result.stderr:
            log(f"[Claude CLI] Stderr: {result.stderr[:200]}")

        if result.returncode != 0:
            return AgentResponse(
                success=False,
                content="",
                error=result.stderr[:200] if result.stderr else "Non-zero return code",
                raw_output=result.stdout
            )

        if not result.stdout or not result.stdout.strip():
            return AgentResponse(
                success=False,
                content="",
                error="Empty response from agent"
            )

        return AgentResponse(
            success=True,
            content=result.stdout.strip(),
            raw_output=result.stdout
        )

    except subprocess.TimeoutExpired:
        return AgentResponse(
            success=False,
            content="",
            error=f"Timeout after {timeout}s"
        )
    except Exception as e:
        return AgentResponse(
            success=False,
            content="",
            error=str(e)
        )
