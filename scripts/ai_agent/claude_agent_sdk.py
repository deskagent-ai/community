# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Claude Agent SDK Backend
=========================
Uses the official Claude Agent SDK for multi-step workflows
with user confirmation at each step.

Requires: pip install "deskagent[claude-sdk]"

NOTE (AGPL / Community Edition):
    `claude-agent-sdk` is an OPTIONAL dependency. It bundles a proprietary
    `claude` binary under Anthropic Commercial Terms and is therefore not
    a hard dependency of the AGPL build. This module imports the SDK
    lazily; if it is missing, ``_SDK_AVAILABLE`` is False and any backend
    function that requires the SDK will raise / log a helpful error.

    The lazy guard below ensures `import claude_agent_sdk` never crashes
    the assistant at startup just because the optional SDK is missing.
"""

# =============================================================================
# CRITICAL: Set environment variables BEFORE any imports
# These must be set before claude_agent_sdk module is loaded
# =============================================================================
import os

# Increase stream close timeout to prevent "Stream closed" errors during parallel tool calls
# Issue: https://github.com/anthropics/claude-agent-sdk-typescript/issues/41
# Default is 60s, we use 10 minutes for complex agent workflows
os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "600000")

# Lazy availability probe for the optional `claude-agent-sdk` package.
# We do NOT import its symbols at module top-level - existing code paths
# already use lazy `from claude_agent_sdk import ...` inside functions.
# The flag below is the single source of truth for "is the SDK installed".
try:
    import claude_agent_sdk as _claude_agent_sdk_pkg  # noqa: F401
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False

import asyncio
import base64
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Callable
from paths import PROJECT_DIR
from .agent_logging import AgentResponse, write_prompt_log
from .dev_context import add_dev_tool_result, capture_dev_context, get_dev_context, update_dev_iteration
from .event_publishing import publish_context_event, publish_tool_event
from .logging import log
from .prompt_builder import build_system_prompt
from .token_utils import calculate_cost, estimate_tokens, format_tokens, get_context_limit
from .tool_bridge import get_read_only_tools
from assistant.platform import get_mcp_python_executable


# =============================================================================
# SDK Mode
# =============================================================================
# sdk_mode: "extended" (default) = Sessions, AskUserQuestion, Structured Outputs
# sdk_mode: "legacy" = old behavior, no new features

def _get_sdk_mode(agent_config: dict, backend_config: dict) -> str:
    """
    Get SDK mode with frontmatter override.

    Priority: agent_config (frontmatter) > backend_config (backends.json) > default

    Returns:
        "extended" (default) or "legacy"
    """
    return agent_config.get("sdk_mode") or backend_config.get("sdk_mode", "extended")


# =============================================================================
# Tool-to-MCP Mapping (for allowed_mcp enforcement)
# =============================================================================

def load_tool_mcp_mapping() -> dict:
    """Load tool → MCP mapping from proxy cache.

    The proxy_tool_cache.json contains module info for each tool.
    We extract the MCP name from the module (e.g., "msgraph.auth" → "msgraph").

    Returns:
        dict: {"graph_get_email": "msgraph", "billomat_create": "billomat", ...}
    """
    tool_to_mcp = {}

    # Find cache file
    workspace_dir = os.environ.get("DESKAGENT_WORKSPACE_DIR", "")
    if workspace_dir:
        cache_file = Path(workspace_dir) / ".temp" / "proxy_tool_cache.json"
    else:
        cache_file = Path(__file__).parent.parent.parent.parent / "workspace" / ".temp" / "proxy_tool_cache.json"

    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text(encoding='utf-8'))
            for tool in cache.get("tools", []):
                tool_name = tool.get("name", "")
                module = tool.get("module", "")
                # Extract MCP name: "msgraph.auth" → "msgraph"
                mcp_name = module.split(".")[0] if module else ""
                if tool_name and mcp_name:
                    tool_to_mcp[tool_name] = mcp_name
            log(f"[Agent SDK] Loaded {len(tool_to_mcp)} tool→MCP mappings from cache")
        except Exception as e:
            log(f"[Agent SDK] Failed to load tool cache: {e}")

    return tool_to_mcp


def get_mcp_name_for_tool(tool_name: str, tool_to_mcp: dict) -> str:
    """Get MCP name for a tool from cache mapping.

    Args:
        tool_name: Short tool name (e.g., "graph_get_email", "outlook_send")
        tool_to_mcp: Mapping dict from load_tool_mcp_mapping()

    Returns:
        MCP name (e.g., "msgraph", "outlook")
    """
    # 1. From cache mapping (module → first part before ".")
    if tool_name in tool_to_mcp:
        return tool_to_mcp[tool_name]

    # 2. Fallback: prefix (first part before "_")
    return tool_name.split("_")[0] if "_" in tool_name else tool_name


# =============================================================================
# Windows Fixes
# =============================================================================
# 1. Command line limit of ~8191 chars - use temp file for long system prompts
# 2. Console window appearing - use CREATE_NO_WINDOW flag

_WINDOWS_CMD_LIMIT = 7500  # Leave margin below 8191
_temp_system_prompt_files = []  # Track temp files for cleanup

# Windows creationflags to hide console window
import subprocess
CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0

# =============================================================================
# Windows ~/.claude.json Workaround (ONLY for non-proxy stdio MCPs)
# =============================================================================
# The --mcp-config CLI flag is broken on Windows for stdio MCPs.
# Workaround: Inject into ~/.claude.json -> projects.{cwd}.mcpServers
#
# NOTE: This is NOT needed for SSE MCPs (proxy mode), which are handled
# directly by the SDK's SSE transport without going through the CLI.
# The _patched_build_command checks for SSE configs and skips injection.

_original_claude_json = None
_claude_json_path = None
_injected_cwd = None  # Track which project path we injected into


def _get_claude_json_path() -> Path:
    """Get path to ~/.claude.json (user-level Claude config)."""
    return Path.home() / ".claude.json"


def _has_stdio_mcp_servers(mcp_servers: dict) -> bool:
    """
    Check if any MCP servers use stdio transport.

    SSE servers (proxy mode) don't need the ~/.claude.json workaround
    because they're handled directly by the SDK.

    Args:
        mcp_servers: Dict of MCP server configs

    Returns:
        True if any server uses stdio transport
    """
    if not mcp_servers:
        return False
    for server_config in mcp_servers.values():
        if isinstance(server_config, dict):
            # stdio is default if no type specified
            server_type = server_config.get("type", "stdio")
            if server_type == "stdio":
                return True
    return False


def _has_sdk_mcp_servers(mcp_servers: dict) -> bool:
    """
    Check if any MCP servers use SDK transport (in-process).

    SDK-type servers contain Server objects that can't be JSON serialized.
    They're handled directly by ClaudeSDKClient, not through CLI args.

    Args:
        mcp_servers: Dict of MCP server configs

    Returns:
        True if any server uses SDK transport
    """
    if not mcp_servers:
        return False
    for server_config in mcp_servers.values():
        if isinstance(server_config, dict):
            if server_config.get("type") == "sdk":
                return True
    return False


def _inject_mcp_to_user_config(mcp_servers: dict, cwd: str = None) -> bool:
    """
    Windows workaround: Inject stdio MCP servers into ~/.claude.json.

    The --mcp-config CLI flag is broken on Windows (known bug).
    User-level config in ~/.claude.json -> projects.{cwd}.mcpServers works.

    NOTE: Only needed for stdio MCPs. SSE MCPs are handled directly by SDK.

    Args:
        mcp_servers: Dict of MCP server configs (should be stdio only)
        cwd: Current working directory (project path)

    Returns:
        True if injection succeeded, False otherwise
    """
    global _original_claude_json, _claude_json_path, _injected_cwd

    try:
        _claude_json_path = _get_claude_json_path()

        # Determine cwd (project path)
        if cwd is None:
            cwd = os.getcwd()
        # Normalize path separators for consistency
        cwd_normalized = cwd.replace("/", "\\")
        _injected_cwd = cwd_normalized  # Track for restoration

        # Read existing config (or create empty)
        if _claude_json_path.exists():
            _original_claude_json = _claude_json_path.read_text(encoding='utf-8')
            config = json.loads(_original_claude_json)
        else:
            _original_claude_json = None
            config = {}

        # Ensure projects structure exists
        if "projects" not in config:
            config["projects"] = {}

        # Ensure project entry exists
        if cwd_normalized not in config["projects"]:
            config["projects"][cwd_normalized] = {
                "allowedTools": [],
                "mcpContextUris": [],
                "enabledMcpjsonServers": [],
                "disabledMcpjsonServers": [],
                "hasTrustDialogAccepted": True
            }

        # Populate mcpContextUris with key knowledge resources for automatic context
        project_entry = config["projects"][cwd_normalized]
        if not project_entry.get("mcpContextUris"):
            project_entry["mcpContextUris"] = [
                "knowledge://user/doc-company",
                "knowledge://user/doc-products",
                "knowledge://user/doc-pricing"
            ]

        # Inject our MCP servers into the project-specific config
        config["projects"][cwd_normalized]["mcpServers"] = mcp_servers

        # Write updated config
        _claude_json_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
        log(f"[Agent SDK] Windows workaround: Injected {len(mcp_servers)} stdio MCP servers into ~/.claude.json")
        log(f"[Agent SDK] Project path: {cwd_normalized}")
        return True

    except Exception as e:
        log(f"[Agent SDK] Failed to inject MCP config: {e}")
        return False


def _restore_user_config() -> None:
    """
    Restore original ~/.claude.json after agent run.

    Called automatically after agent completes or on error.
    Only does work if we previously injected stdio MCP configs.
    """
    global _original_claude_json, _claude_json_path, _injected_cwd

    if _claude_json_path is None:
        return  # Nothing was injected

    try:
        if _original_claude_json is not None:
            # Restore original content
            _claude_json_path.write_text(_original_claude_json, encoding='utf-8')
            log("[Agent SDK] Restored original ~/.claude.json")
        elif _injected_cwd and _claude_json_path.exists():
            # File didn't exist before OR we need to clean up project-specific mcpServers
            config = json.loads(_claude_json_path.read_text(encoding='utf-8'))
            # Remove mcpServers from the specific project
            if "projects" in config and _injected_cwd in config["projects"]:
                if "mcpServers" in config["projects"][_injected_cwd]:
                    del config["projects"][_injected_cwd]["mcpServers"]
                    _claude_json_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
                    log(f"[Agent SDK] Removed mcpServers from project {_injected_cwd}")

    except Exception as e:
        log(f"[Agent SDK] Failed to restore ~/.claude.json: {e}")

    finally:
        _original_claude_json = None
        _claude_json_path = None
        _injected_cwd = None


def _cleanup_orphan_mcp_processes():
    """
    Clean up orphan MCP server processes from previous agent runs.

    Claude Code CLI starts MCP servers as subprocesses but doesn't always
    terminate them when the agent finishes (especially on cancel/error).
    This function kills all MCP processes matching our pattern before
    starting new ones to prevent accumulation.

    Works on Windows, Linux, and macOS.
    """
    try:
        import subprocess

        if sys.platform == 'win32':
            # Windows: Use WMI to find processes with our MCP path pattern
            # Note: Windows paths use backslashes, so search for both patterns
            # Use % wildcard between deskagent and mcp to match both / and \
            result = subprocess.run(
                ['powershell', '-Command',
                 'Get-WmiObject Win32_Process -Filter "CommandLine LIKE \'%deskagent%mcp%\'" | '
                 'Select-Object -ExpandProperty ProcessId'],
                capture_output=True, text=True, timeout=10,
                creationflags=CREATE_NO_WINDOW
            )

            if result.returncode != 0 or not result.stdout.strip():
                return 0

            # Parse PIDs and kill them
            pids = [int(pid.strip()) for pid in result.stdout.strip().split('\n') if pid.strip().isdigit()]
            killed = 0

            for pid in pids:
                try:
                    subprocess.run(
                        ['taskkill', '/PID', str(pid), '/F'],
                        capture_output=True, timeout=5,
                        creationflags=CREATE_NO_WINDOW
                    )
                    killed += 1
                except (subprocess.TimeoutExpired, OSError):
                    pass

        else:
            # Linux/macOS: Use pgrep and kill
            result = subprocess.run(
                ['pgrep', '-f', 'deskagent/mcp'],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode != 0 or not result.stdout.strip():
                return 0

            pids = [int(pid.strip()) for pid in result.stdout.strip().split('\n') if pid.strip().isdigit()]
            killed = 0

            for pid in pids:
                try:
                    subprocess.run(['kill', '-9', str(pid)], capture_output=True, timeout=5)
                    killed += 1
                except (subprocess.TimeoutExpired, OSError):
                    pass

        if killed > 0:
            log(f"[Agent SDK] Cleaned up {killed} orphan MCP processes")
        return killed

    except Exception as e:
        log(f"[Agent SDK] MCP cleanup failed: {e}")
        return 0


def _cleanup_orphan_claude_cli_processes():
    """
    Kill orphan Claude CLI Node processes from previous agent runs.

    Claude CLI runs as a Node.js process (via claude.CMD). After
    timeout/error, these processes may remain running and accumulate,
    eventually causing resource exhaustion and timeout errors.

    Detection: node.exe with 'claude' in CommandLine
    Exclusion: VSCode extension hosts, Electron processes
    """
    try:
        import subprocess

        if sys.platform != 'win32':
            # Linux/macOS: pkill approach
            # Target only Claude CLI processes (have --output-format flag)
            subprocess.run(
                ['pkill', '-f', 'claude.*--output-format'],
                capture_output=True, timeout=5
            )
            return 0

        # Windows: Use WMI to find Claude CLI processes
        # Filter: node.exe with 'claude' but NOT extensionHost/electron
        query = (
            "Get-WmiObject Win32_Process -Filter "
            "\"Name='node.exe' AND CommandLine LIKE '%claude%'\" | "
            "Where-Object { $_.CommandLine -notlike '*extensionHost*' -and "
            "$_.CommandLine -notlike '*electron*' } | "
            "Select-Object -ExpandProperty ProcessId"
        )

        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', query],
            capture_output=True, text=True, timeout=10,
            creationflags=CREATE_NO_WINDOW
        )

        if result.returncode != 0 or not result.stdout.strip():
            return 0

        pids = [int(pid.strip()) for pid in result.stdout.strip().split('\n')
                if pid.strip().isdigit()]
        killed = 0

        for pid in pids:
            try:
                subprocess.run(
                    ['taskkill', '/PID', str(pid), '/F'],
                    capture_output=True, timeout=5,
                    creationflags=CREATE_NO_WINDOW
                )
                killed += 1
            except (subprocess.TimeoutExpired, OSError):
                pass

        if killed > 0:
            log(f"[Agent SDK] Cleaned up {killed} orphan Claude CLI processes")
        return killed

    except Exception as e:
        log(f"[Agent SDK] Claude CLI cleanup failed: {e}")
        return 0


def _cleanup_temp_files():
    """Clean up temporary system prompt files."""
    global _temp_system_prompt_files
    for f in _temp_system_prompt_files:
        try:
            if os.path.exists(f):
                os.remove(f)
        except (OSError, PermissionError):
            pass  # Temp file cleanup failed - not critical
    _temp_system_prompt_files = []


def _cleanup_session_filter():
    """Clean up session filter in Filter Proxy after agent completes.

    Reads session ID from ANON_SESSION_ID environment variable and calls
    the Filter Proxy to remove the session's filter pattern.

    This is Phase 4 of planfeature-008: Session Cleanup.
    """
    session_id = os.environ.get("ANON_SESSION_ID")
    if not session_id:
        return

    try:
        from assistant.services.mcp_proxy_manager import clear_session_filter
        clear_session_filter(session_id)
        log(f"[Agent SDK] Cleared filter for session {session_id}")
    except ImportError:
        pass  # Filter Proxy not available - session will timeout via TTL
    except Exception as e:
        log(f"[Agent SDK] Failed to clear session filter: {e}")


def _apply_windows_cmdline_fix():
    """
    Monkey-patch SubprocessCLITransport for Windows:
    1. Handle long system prompts via temp file
    2. Hide console window with CREATE_NO_WINDOW flag

    The SDK uses anyio.open_process which supports creationflags parameter.
    We patch the connect() method to add this flag on Windows.
    """
    if sys.platform != 'win32':
        return  # Only needed on Windows

    try:
        from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
    except ImportError:
        log("[Agent SDK] Could not import SubprocessCLITransport for Windows fix")
        return

    # Check if already patched
    if hasattr(SubprocessCLITransport, '_original_build_command'):
        return

    # Store original methods
    original_build_command = SubprocessCLITransport._build_command
    SubprocessCLITransport._original_build_command = original_build_command

    original_connect = SubprocessCLITransport.connect
    SubprocessCLITransport._original_connect = original_connect

    def _patched_build_command(self) -> list:
        """Patched _build_command that uses temp files for long content on Windows."""
        import json as json_module

        # Track what we need to handle manually
        system_prompt = getattr(self._options, 'system_prompt', None)
        mcp_servers = getattr(self._options, 'mcp_servers', None)

        # Store originals for restoration
        original_system_prompt = self._options.system_prompt
        original_mcp_servers = self._options.mcp_servers

        # Temp files for manual addition
        system_prompt_file = None
        mcp_config_file = None

        try:
            # Use workspace .temp/ directory instead of system temp for easier debugging
            from paths import get_logs_dir
            workspace_temp = get_logs_dir().parent / ".temp"
            workspace_temp.mkdir(exist_ok=True)

            # Handle long system prompt
            if isinstance(system_prompt, str) and len(system_prompt) > _WINDOWS_CMD_LIMIT:
                log(f"[Agent SDK] System prompt too long ({len(system_prompt)} chars), using temp file")
                temp_path = workspace_temp / f"claude_system_prompt_{int(time.time())}.txt"
                temp_path.write_text(system_prompt, encoding='utf-8')
                _temp_system_prompt_files.append(str(temp_path))
                log(f"[Agent SDK] Wrote system prompt to: {temp_path}")
                system_prompt_file = str(temp_path)
                self._options.system_prompt = None  # Skip in original method

            # Handle MCP servers config (dict with potentially long JSON)
            # Windows workaround: The --mcp-config CLI flag is BROKEN on Windows for stdio MCPs.
            # See: https://github.com/anthropics/claude-code/issues/15215
            # Always use temp file with --mcp-config (like CherryPick)
            # The ~/.claude.json injection caused file bloat (1.8MB!) and was unreliable
            if isinstance(mcp_servers, dict) and mcp_servers:
                # SDK-type servers (in-process) contain non-serializable Server objects
                # They're handled by ClaudeSDKClient, not through CLI args
                has_sdk = _has_sdk_mcp_servers(mcp_servers)
                if has_sdk:
                    # Extract stdio servers (have "command" key) for temp file serialization
                    # SDK-type servers are handled in-process by ClaudeSDKClient
                    stdio_servers = {k: v for k, v in mcp_servers.items()
                                     if isinstance(v, dict) and "command" in v}
                    if stdio_servers:
                        mcp_json = json_module.dumps({"mcpServers": stdio_servers}, indent=2)
                        temp_path = workspace_temp / f"claude_mcp_config_{int(time.time())}.json"
                        temp_path.write_text(mcp_json, encoding='utf-8')
                        _temp_system_prompt_files.append(str(temp_path))
                        mcp_config_file = str(temp_path)
                        log(f"[Agent SDK] Mixed mode: {len(stdio_servers)} stdio + SDK servers, temp file written")
                        self._options.mcp_servers = None  # Prevent SDK from serializing stdio objects
                    else:
                        log("[Agent SDK] SDK-only MCP servers, letting SDK handle CLI serialization")
                        # Don't null out! SDK's _build_command strips instance field and passes
                        # {"type": "sdk", "name": "..."} to CLI via --mcp-config.
                        # This is needed for the CLI to know about SDK servers and bridge
                        # tool calls through the control protocol.
                else:
                    # Check if we have stdio MCPs that need the Windows workaround
                    has_stdio = _has_stdio_mcp_servers(mcp_servers)

                    if has_stdio:
                        mcp_json = json_module.dumps({"mcpServers": mcp_servers}, indent=2)
                        log(f"[Agent SDK] stdio MCP config ({len(mcp_json)} chars):")
                        log(f"[Agent SDK] {mcp_json[:1500]}...")  # Log first 1500 chars

                        # Use temp file with --mcp-config (like CherryPick)
                        # This is more reliable than ~/.claude.json injection which bloated the file
                        temp_path = workspace_temp / f"claude_mcp_config_{int(time.time())}.json"
                        temp_path.write_text(mcp_json, encoding='utf-8')
                        _temp_system_prompt_files.append(str(temp_path))
                        log(f"[Agent SDK] MCP config too long ({len(mcp_json)} chars), using temp file")
                        log(f"[Agent SDK] Wrote MCP config to: {temp_path}")
                        mcp_config_file = str(temp_path)

                        self._options.mcp_servers = None  # Skip in original method
                    else:
                        # HTTP/SSE config (proxy mode) - ALSO needs temp file!
                        # The SDK passes mcp_servers as raw JSON to --mcp-config, but CLI expects a file path
                        mcp_json = json_module.dumps({"mcpServers": mcp_servers}, indent=2)
                        temp_path = workspace_temp / f"claude_mcp_config_{int(time.time())}.json"
                        temp_path.write_text(mcp_json, encoding='utf-8')
                        _temp_system_prompt_files.append(str(temp_path))
                        mcp_config_file = str(temp_path)
                        log(f"[Agent SDK] HTTP MCP config written to: {temp_path}")
                    self._options.mcp_servers = None  # Prevent SDK from adding raw JSON

            # Call original method (with cleared options if needed)
            cmd = original_build_command(self)

            # Remove --system-prompt with empty value if we're using a temp file
            # The SDK adds --system-prompt "" when system_prompt is None
            if system_prompt_file:
                # Find and remove --system-prompt and its (empty) argument
                try:
                    idx = cmd.index("--system-prompt")
                    # Remove --system-prompt and the next argument (empty string)
                    if idx + 1 < len(cmd):
                        cmd.pop(idx + 1)  # Remove empty argument first
                    cmd.pop(idx)  # Then remove --system-prompt
                except ValueError:
                    pass  # --system-prompt not found, that's fine

            # Add our temp file arguments
            if system_prompt_file:
                cmd.extend(["--system-prompt-file", system_prompt_file])

            # MCP config handling - always use --mcp-config with temp file
            if mcp_config_file:
                cmd.extend(["--mcp-config", mcp_config_file])

            return cmd

        except Exception as e:
            log(f"[Agent SDK] Failed to write temp file: {e}")
            # Restore and fall through to original method
            self._options.system_prompt = original_system_prompt
            self._options.mcp_servers = original_mcp_servers
            return original_build_command(self)

        finally:
            # Always restore originals
            self._options.system_prompt = original_system_prompt
            self._options.mcp_servers = original_mcp_servers

    # Apply command line patch
    SubprocessCLITransport._build_command = _patched_build_command
    log("[Agent SDK] Applied Windows command line length fix")

    # Patch connect() to add CREATE_NO_WINDOW flag
    # The SDK uses anyio.open_process which supports creationflags parameter
    async def _patched_connect(self) -> None:
        """Patched connect that adds CREATE_NO_WINDOW on Windows."""
        import anyio
        from anyio.abc import Process
        from anyio.streams.text import TextReceiveStream, TextSendStream
        from subprocess import PIPE

        if self._process:
            return

        if not os.environ.get("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK"):
            await self._check_claude_version()

        cmd = self._build_command()
        try:
            # Merge environment variables: system -> user -> SDK required
            from claude_agent_sdk._internal.transport.subprocess_cli import __version__
            process_env = {
                **os.environ,
                **self._options.env,  # User-provided env vars
                "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
                "CLAUDE_AGENT_SDK_VERSION": __version__,
            }

            # Enable file checkpointing if requested
            if self._options.enable_file_checkpointing:
                process_env["CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING"] = "true"

            if self._cwd:
                process_env["PWD"] = self._cwd

            # Pipe stderr if we have a callback OR debug mode is enabled
            should_pipe_stderr = (
                self._options.stderr is not None
                or "debug-to-stderr" in self._options.extra_args
            )

            # For backward compat: use debug_stderr file object if no callback and debug is on
            stderr_dest = PIPE if should_pipe_stderr else None

            # === WINDOWS FIX: Hide console window completely ===
            # Need BOTH creationflags AND startupinfo to fully prevent window flash
            # See: https://github.com/agronholm/anyio/issues/742
            win_kwargs = {}
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                win_kwargs['startupinfo'] = startupinfo
                win_kwargs['creationflags'] = CREATE_NO_WINDOW
                log("[Agent SDK] Starting subprocess with STARTUPINFO + CREATE_NO_WINDOW")
            else:
                log("[Agent SDK] Starting subprocess (non-Windows)")

            # Log the actual command line being executed
            cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
            log(f"[Agent SDK] Command line: {cmd_str[:500]}...")
            # Log if --mcp-config is present
            if "--mcp-config" in cmd:
                mcp_idx = cmd.index("--mcp-config")
                if mcp_idx + 1 < len(cmd):
                    log(f"[Agent SDK] MCP config file: {cmd[mcp_idx + 1]}")

            self._process = await anyio.open_process(
                cmd,
                stdin=PIPE,
                stdout=PIPE,
                stderr=stderr_dest,
                cwd=self._cwd,
                env=process_env,
                user=self._options.user,
                **win_kwargs,
            )

            if self._process.stdout:
                self._stdout_stream = TextReceiveStream(self._process.stdout)

            # Setup stderr stream if piped
            if should_pipe_stderr and self._process.stderr:
                self._stderr_stream = TextReceiveStream(self._process.stderr)
                # Start async task to read stderr
                self._stderr_task_group = anyio.create_task_group()
                await self._stderr_task_group.__aenter__()
                self._stderr_task_group.start_soon(self._handle_stderr)

            # Setup stdin for streaming mode
            if self._is_streaming and self._process.stdin:
                self._stdin_stream = TextSendStream(self._process.stdin)
            elif not self._is_streaming and self._process.stdin:
                # String mode: close stdin immediately
                await self._process.stdin.aclose()

            self._ready = True

        except FileNotFoundError as e:
            from claude_agent_sdk._internal.transport.subprocess_cli import CLIConnectionError, CLINotFoundError
            # Terminate subprocess if it was created (#10 - zombie process fix)
            if self._process:
                try:
                    self._process.terminate()
                except OSError:
                    pass  # Process already terminated or inaccessible
            # Check if the error comes from the working directory or the CLI
            if self._cwd and not Path(self._cwd).exists():
                error = CLIConnectionError(
                    f"Working directory does not exist: {self._cwd}"
                )
                self._exit_error = error
                raise error from e
            error = CLINotFoundError(f"Claude Code not found at: {self._cli_path}")
            self._exit_error = error
            raise error from e
        except Exception as e:
            from claude_agent_sdk._internal.transport.subprocess_cli import CLIConnectionError
            # Terminate subprocess if it was created (#10 - zombie process fix)
            if self._process:
                try:
                    self._process.terminate()
                except OSError:
                    pass  # Process already terminated or inaccessible
            error = CLIConnectionError(f"Failed to start Claude Code: {e}")
            self._exit_error = error
            raise error from e

    SubprocessCLITransport.connect = _patched_connect
    log("[Agent SDK] Applied Windows console hiding fix (connect method)")

# Path is set up by ai_agent/__init__.py
from paths import DESKAGENT_DIR, get_mcp_dir

# Set CLAUDE_CODE_GIT_BASH_PATH for Windows (Claude Code CLI needs git-bash)
if sys.platform == 'win32':
    _git_bash_path = DESKAGENT_DIR / "git" / "bin" / "bash.exe"
    if _git_bash_path.exists():
        os.environ["CLAUDE_CODE_GIT_BASH_PATH"] = str(_git_bash_path)
        # Also add git to PATH for any git commands
        _git_bin_path = str(DESKAGENT_DIR / "git" / "bin")
        _git_cmd_path = str(DESKAGENT_DIR / "git" / "cmd")
        os.environ["PATH"] = f"{_git_cmd_path};{_git_bin_path};" + os.environ.get("PATH", "")


# =============================================================================
# MCP Environment Whitelist
# =============================================================================
# Minimal set of env vars needed by MCP server subprocesses.
# Avoids serializing the full os.environ (~100 vars, ~5000 char PATH)
# into MCP config JSON, which causes "Die Befehlszeile ist zu lang" on Windows.

_MCP_ENV_WHITELIST = [
    # System (Windows)
    "PATH", "SYSTEMROOT", "TEMP", "TMP", "COMSPEC",
    # User
    "USERNAME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    # Python
    "PYTHONPATH", "PYTHONUNBUFFERED",
    # DeskAgent Core
    "DESKAGENT_SCRIPTS_DIR", "DESKAGENT_PORT", "DESKAGENT_API_URL",
    "DESKAGENT_LOGS_DIR", "DESKAGENT_WORKSPACE_DIR",
    "DESKAGENT_SESSION_ID", "ANON_SESSION_ID",
    "USING_EMBEDDED", "STARTUP_MODE",
    # AI (when set via env)
    "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
]


def _build_mcp_env() -> dict:
    """Build minimal environment for MCP server subprocesses.

    Used by both proxy and direct MCP paths to avoid
    serializing the full os.environ into MCP config JSON.

    Returns:
        dict with whitelisted env vars that have values.
    """
    env = {}
    for key in _MCP_ENV_WHITELIST:
        val = os.environ.get(key)
        if val:
            env[key] = val
    # Always set scripts dir (even if not in os.environ)
    env["DESKAGENT_SCRIPTS_DIR"] = str(DESKAGENT_DIR / "scripts")
    return env


def _find_cli_path() -> str | None:
    """
    Find Claude CLI executable path.

    Checks:
    1. DeskAgent portable installation (node/ directory)
    2. System PATH (shutil.which)

    Returns:
        Path to claude CLI if found, None otherwise
    """
    import shutil

    # Check portable installation first (installed by Setup Wizard)
    try:
        from assistant.services.claude_cli_installer import get_claude_cli_path
        portable_cli = get_claude_cli_path()
        if portable_cli:
            log(f"[Agent SDK] Found portable CLI: {portable_cli}")
            return str(portable_cli)
    except ImportError:
        pass  # Installer module not available

    # Check system PATH
    system_cli = shutil.which("claude")
    if system_cli:
        log(f"[Agent SDK] Found system CLI: {system_cli}")
        return system_cli

    log("[Agent SDK] Claude CLI not found")
    return None


def _has_cli_auth() -> bool:
    """Check if Claude CLI authentication exists (~/.claude/ directory with credentials)."""
    import os
    from pathlib import Path

    # Check common auth locations
    home = Path.home()
    claude_dir = home / ".claude"

    # Check if .claude directory exists and has some config
    if claude_dir.exists() and claude_dir.is_dir():
        # Look for any auth-related files
        for f in claude_dir.iterdir():
            if f.is_file():
                return True

    # Also check ANTHROPIC_API_KEY environment variable
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True

    return False


def _validate_api_key(api_key: str) -> bool:
    """Validate that an API key looks valid (not empty, not placeholder)."""
    if not api_key:
        return False
    if api_key.startswith("YOUR_") or api_key == "sk-...":
        return False
    if len(api_key) < 10:
        return False
    return True


def check_configured(config: dict) -> tuple:
    """
    Check if this backend is properly configured.

    Claude Agent SDK can authenticate via:
    1. CLI authentication (claude login) - checks ~/.claude/ directory
    2. API key in config
    3. ANTHROPIC_API_KEY environment variable

    Args:
        config: Backend configuration dict

    Returns:
        Tuple of (is_configured: bool, issue: str or None)
    """
    # Check if SDK is installed
    if not is_available():
        return False, "Claude Agent SDK not installed (pip install claude-agent-sdk)"

    # Check for API key in config
    api_key = config.get("api_key", "")
    if _validate_api_key(api_key):
        return True, None

    # Check for CLI auth or environment variable
    if _has_cli_auth():
        return True, None

    return False, "No authentication: set api_key in config or run 'claude login'"


def parse_anon_metadata(text: str) -> dict | None:
    """
    Parse anonymization metadata from tool result.

    Format: <!--ANON:total|new|PERSON:2,EMAIL:1|base64_mappings-->

    Returns dict with:
        - total: total entities anonymized
        - new: new entities in this call
        - entity_summary: string like "PERSON:2,EMAIL:1"
        - mappings: dict {placeholder: original} for de-anonymization
    """
    # Try extended format first (with mappings)
    match = re.search(r'<!--ANON:(\d+)\|(\d+)\|([^|]*)\|([^>]+)-->', text)
    if match:
        total = int(match.group(1))
        new = int(match.group(2))
        entity_summary = match.group(3)
        mappings_b64 = match.group(4)

        # Decode mappings
        mappings = {}
        try:
            mappings_json = base64.b64decode(mappings_b64).decode('utf-8')
            mappings = json.loads(mappings_json)
        except Exception as e:
            log(f"[Agent SDK] Failed to decode mappings: {e}")

        return {
            "total": total,
            "new": new,
            "entity_summary": entity_summary,
            "mappings": mappings
        }

    # Fallback to old format (without mappings)
    match = re.search(r'<!--ANON:(\d+)\|(\d+)\|([^>]*)-->', text)
    if match:
        return {
            "total": int(match.group(1)),
            "new": int(match.group(2)),
            "entity_summary": match.group(3),
            "mappings": {}
        }

    return None

# Check if SDK is available
_sdk_available = None


def is_available() -> bool:
    """Check if Claude Agent SDK is installed."""
    global _sdk_available
    if _sdk_available is None:
        try:
            from claude_agent_sdk import query
            _sdk_available = True
            log("[Agent SDK] Claude Agent SDK available")
            # Apply Windows command line fix on first successful import
            _apply_windows_cmdline_fix()
        except ImportError:
            _sdk_available = False
            log("[Agent SDK] Claude Agent SDK not installed - run: pip install claude-agent-sdk")
    return _sdk_available


class CancelledException(Exception):
    """Raised when the agent task is cancelled by user."""
    pass


async def _run_with_cancel_watchdog(agent_gen, is_cancelled: Optional[Callable[[], bool]], interval: float = 0.5):
    """
    Wrap an async generator with a cancellation watchdog.

    The watchdog runs in parallel and checks is_cancelled() every interval seconds.
    If cancelled, raises CancelledException to interrupt the async for loop immediately,
    even if the generator is blocked waiting for a message.

    Args:
        agent_gen: The async generator from query()
        is_cancelled: Callback that returns True if cancelled
        interval: Check interval in seconds (default 0.5s)

    Yields:
        Messages from the original generator

    Raises:
        CancelledException: When is_cancelled() returns True
    """
    if not is_cancelled:
        # No cancellation callback - just yield from original
        async for message in agent_gen:
            yield message
        return

    # Event to signal cancellation to the main loop
    cancel_event = asyncio.Event()

    async def watchdog():
        """Background task that checks for cancellation."""
        while True:
            await asyncio.sleep(interval)
            if is_cancelled():
                log("[Agent SDK] Watchdog detected cancellation request")
                cancel_event.set()
                return

    # Start watchdog task
    watchdog_task = asyncio.create_task(watchdog())

    try:
        # Use asyncio.wait with FIRST_COMPLETED to race between next message and cancellation
        async for message in agent_gen:
            # Check if cancelled before yielding
            if cancel_event.is_set():
                raise CancelledException("Task cancelled by watchdog")
            yield message
            # Check again after yielding (in case cancelled during message processing)
            if cancel_event.is_set():
                raise CancelledException("Task cancelled by watchdog")
    except asyncio.CancelledError:
        # Task was cancelled externally
        raise CancelledException("Task cancelled")
    finally:
        # Always cancel the watchdog
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass


def _check_global_mcp_collision():
    """Warn if global mcpServers in ~/.claude.json could cause conflicts.

    Claude CLI reads ~/.claude.json and spawns MCPs defined there.
    If a global "proxy" entry exists, it conflicts with DeskAgent's proxy.

    See: planfeature-015 Section 8 for details.
    """
    try:
        claude_json = Path.home() / ".claude.json"
        if not claude_json.exists():
            return

        config = json.loads(claude_json.read_text(encoding='utf-8'))
        global_mcps = config.get("mcpServers", {})

        if global_mcps:
            mcp_names = list(global_mcps.keys())
            log(f"[Agent SDK] WARNING: Global mcpServers in ~/.claude.json: {mcp_names}")
            log("[Agent SDK] This may conflict with DeskAgent proxy!")
            log("[Agent SDK] Remove 'mcpServers' section from ~/.claude.json to fix.")

            # Special warning for "proxy" entry
            if "proxy" in global_mcps:
                log("[Agent SDK] CRITICAL: 'proxy' entry will spawn duplicate proxy!")
    except Exception as e:
        log(f"[Agent SDK] Could not check ~/.claude.json: {e}")


# =============================================================================
# ClaudeSDKClient Integration (planfeature-021)
# =============================================================================
# Uses ClaudeSDKClient for true in-process MCP execution without CLI subprocess.

from dataclasses import dataclass, field


@dataclass
class MessageHandlerContext:
    """
    Shared context for message handling in Agent SDK.

    Enables code reuse between query() and ClaudeSDKClient approaches.
    """
    # Response accumulation
    full_response: str = ""
    tool_calls: list = field(default_factory=list)

    # Token tracking
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cost_usd: float | None = None
    processed_message_ids: set = field(default_factory=set)
    model_name: str = "claude-sonnet-4"

    # Tool timing
    tool_timings: dict = field(default_factory=dict)
    tool_id_to_name: dict = field(default_factory=dict)
    tool_stats: list = field(default_factory=list)

    # Anonymization
    anon_stats: dict = field(default_factory=lambda: {
        "total_entities": 0,
        "entity_types": {},
        "tool_calls_anonymized": 0,
        "mappings": {}
    })

    # SDK Extended Mode
    sdk_session_id: str | None = None

    # Context tracking
    system_prompt_tokens: int = 0
    user_prompt_tokens: int = 0
    tool_result_tokens: int = 0

    # Token breakdown for UI
    token_breakdown: dict = field(default_factory=lambda: {
        "system": 0,
        "prompt": 0,
        "tools": 0
    })

    # Iteration limits
    max_iterations: int = 50
    max_iterations_reached: bool = False

    # Callbacks
    on_message: Callable | None = None
    use_extended_mode: bool = False

    # Session ID for anonymization
    session_id: str | None = None
    use_proxy: bool = False


async def _run_with_sdk_client(
    prompt: str,
    options,  # ClaudeAgentOptions
    ctx: MessageHandlerContext,
    is_cancelled: Optional[Callable[[], bool]] = None,
    pricing: dict = None
) -> AgentResponse:
    """
    Run agent using ClaudeSDKClient for true in-process MCP execution.

    Unlike query() which starts a CLI subprocess, ClaudeSDKClient runs
    entirely in the current Python process. This enables:
    - Direct Python tool calls (no IPC)
    - No subprocess overhead (~5-8s faster startup)
    - No "Stream closed" errors from network issues

    Args:
        prompt: The user prompt
        options: ClaudeAgentOptions with mcp_servers
        ctx: MessageHandlerContext for shared state
        is_cancelled: Callback returning True if task should cancel
        pricing: Pricing config for cost calculation

    Returns:
        AgentResponse with result
    """
    from claude_agent_sdk import ClaudeSDKClient

    log("[Agent SDK] Using ClaudeSDKClient for in-process MCP (planfeature-021)")

    # FIX [039]: Log resume session if present in options
    if hasattr(options, 'resume') and options.resume:
        log(f"[Agent SDK] In-process resume session: {options.resume}")

    client = ClaudeSDKClient(options=options)
    start_time = time.time()

    try:
        log("[Agent SDK] Connecting ClaudeSDKClient...")
        await client.connect()
        log("[Agent SDK] ClaudeSDKClient connected")

        # Check MCP status
        try:
            mcp_status = await client.get_mcp_status()
            if mcp_status:
                for server in mcp_status:
                    name = getattr(server, 'name', 'unknown')
                    status = getattr(server, 'status', 'unknown')
                    log(f"[Agent SDK] MCP {name}: {status}")
        except Exception as e:
            log(f"[Agent SDK] Could not get MCP status: {e}")

        log(f"[Agent SDK] Sending query: {prompt[:100]}...")
        await client.query(prompt)

        async for message in client.receive_response():
            if is_cancelled and is_cancelled():
                log("[Agent SDK] Cancellation detected - interrupting client")
                client.interrupt()
                raise CancelledException("Task cancelled by user")

            should_break = await _handle_sdk_client_message(message, ctx)
            if should_break:
                break

        # Success
        duration = time.time() - start_time
        log(f"[Agent SDK Client] === COMPLETED ===")
        log(f"[Agent SDK Client] Duration: {duration:.1f}s")
        log(f"[Agent SDK Client] Tool calls: {ctx.tool_calls}")
        log(f"[Agent SDK Client] Tokens: {ctx.total_input_tokens} in, {ctx.total_output_tokens} out")

        # Calculate cost
        calculated_cost = None
        if ctx.total_input_tokens > 0 or ctx.total_output_tokens > 0:
            calculated_cost = calculate_cost(
                ctx.total_input_tokens,
                ctx.total_output_tokens,
                pricing or {},
                cache_read_tokens=ctx.total_cache_read_tokens,
                cache_creation_tokens=ctx.total_cache_creation_tokens
            )

        # Build anonymization info
        anon_info = None
        if ctx.anon_stats["total_entities"] > 0:
            anon_info = {
                "total_entities": ctx.anon_stats["total_entities"],
                "entity_types": ctx.anon_stats["entity_types"],
                "tool_calls_anonymized": ctx.anon_stats["tool_calls_anonymized"],
                "mappings": ctx.anon_stats["mappings"]
            }

        # Fix 1B: Detect concurrency error in in-process path (planfeature-027)
        # The in-process path returns here directly, never reaching the subprocess
        # concurrency check. Without this, concurrency errors are returned as success=True.
        if ctx.full_response and "API Error: 400" in ctx.full_response and "concurrency" in ctx.full_response.lower():
            log(f"[Agent SDK Client] Detected concurrency error in response - returning as retryable failure")
            return AgentResponse(
                success=False,
                content=ctx.full_response,
                error="API 400: Tool concurrency error (transient)",
                model=ctx.model_name,
                duration_seconds=duration,
                sdk_session_id=ctx.sdk_session_id,
                can_resume=ctx.sdk_session_id is not None
            )

        return AgentResponse(
            success=True,
            content=ctx.full_response,
            raw_output=ctx.full_response,
            model=ctx.model_name,
            input_tokens=ctx.total_input_tokens if ctx.total_input_tokens > 0 else None,
            output_tokens=ctx.total_output_tokens if ctx.total_output_tokens > 0 else None,
            duration_seconds=duration,
            cost_usd=calculated_cost,
            anonymization=anon_info,
            sdk_session_id=ctx.sdk_session_id,
            can_resume=ctx.sdk_session_id is not None,
            anon_session_id=ctx.session_id if ctx.use_proxy else None
        )

    except CancelledException:
        duration = time.time() - start_time
        log(f"[Agent SDK Client] Task cancelled after {duration:.1f}s")
        anon_info = {"mappings": ctx.anon_stats["mappings"]} if ctx.anon_stats["mappings"] else None
        return AgentResponse(
            success=False,
            content=ctx.full_response,
            error="Cancelled by user",
            model=ctx.model_name,
            duration_seconds=duration,
            cancelled=True,
            anonymization=anon_info,
            sdk_session_id=ctx.sdk_session_id,
            can_resume=ctx.sdk_session_id is not None,
            anon_session_id=ctx.session_id if ctx.use_proxy else None
        )

    except Exception as e:
        duration = time.time() - start_time
        error_str = str(e)
        log(f"[Agent SDK Client] Error: {error_str}")
        import traceback
        log(f"[Agent SDK Client] Traceback: {traceback.format_exc()}")
        return AgentResponse(
            success=False,
            content=ctx.full_response or error_str,
            error=error_str,
            model=ctx.model_name,
            duration_seconds=duration
        )

    finally:
        # Clean up anonymization context for this session
        try:
            from .tool_bridge import _clear_sdk_anon_context
            _clear_sdk_anon_context(ctx.session_id)
        except Exception:
            pass  # Non-fatal - context will be GC'd eventually

        try:
            await client.disconnect()
            log("[Agent SDK Client] Disconnected")
        except Exception as e:
            log(f"[Agent SDK Client] Disconnect error (non-fatal): {e}")


async def _handle_sdk_client_message(message, ctx: MessageHandlerContext) -> bool:
    """
    Handle a message from ClaudeSDKClient.receive_response().

    Returns True if the message loop should break (success or error result).
    """
    msg_class = type(message).__name__
    log(f"[Agent SDK Client] Message type: {msg_class}")

    # Handle SystemMessage
    if msg_class == "SystemMessage":
        if hasattr(message, "subtype") and message.subtype == "init":
            if ctx.use_extended_mode and hasattr(message, "data"):
                data = message.data
                if isinstance(data, dict) and "session_id" in data:
                    ctx.sdk_session_id = data["session_id"]
                    log(f"[Agent SDK Client] Session: {ctx.sdk_session_id}")
                if isinstance(data, dict) and "mcp_servers" in data:
                    for server in (data.get("mcp_servers") or []):
                        if isinstance(server, dict):
                            name = server.get("name", "unknown")
                            status = server.get("status", "unknown")
                            log(f"[Agent SDK Client] MCP {name}: {status}")
        return False

    # Handle AssistantMessage
    if msg_class == "AssistantMessage":
        if hasattr(message, "usage") and hasattr(message, "id"):
            msg_id = message.id
            if msg_id and msg_id not in ctx.processed_message_ids:
                ctx.processed_message_ids.add(msg_id)
                usage = message.usage
                if hasattr(usage, "input_tokens"):
                    ctx.total_input_tokens += usage.input_tokens or 0
                    ctx.total_output_tokens += usage.output_tokens or 0
                    if hasattr(usage, "cache_read_input_tokens"):
                        ctx.total_cache_read_tokens += usage.cache_read_input_tokens or 0
                    if hasattr(usage, "cache_creation_input_tokens"):
                        ctx.total_cache_creation_tokens += usage.cache_creation_input_tokens or 0
                    log(f"[Agent SDK Client] Usage: {ctx.total_input_tokens} in, {ctx.total_output_tokens} out")

        if hasattr(message, "model") and message.model:
            ctx.model_name = message.model

        if hasattr(message, "content"):
            for block in message.content:
                if hasattr(block, "text"):
                    text = block.text
                    ctx.full_response += text
                    if ctx.on_message:
                        ctx.on_message(text, False, ctx.full_response, ctx.anon_stats.copy())
                    log(f"[Agent SDK Client] Text: {text[:200]}...")

                elif hasattr(block, "name"):
                    tool_name = block.name
                    ctx.tool_calls.append(tool_name)
                    if hasattr(block, "id"):
                        ctx.tool_id_to_name[block.id] = tool_name
                    update_dev_iteration(len(ctx.tool_calls), ctx.max_iterations)
                    publish_context_event(
                        iteration=len(ctx.tool_calls), max_iterations=ctx.max_iterations,
                        system_tokens=ctx.token_breakdown["system"],
                        prompt_tokens=ctx.token_breakdown["prompt"],
                        tool_tokens=ctx.token_breakdown["tools"]
                    )
                    ctx.tool_timings[tool_name] = time.time()
                    publish_tool_event(tool_name, "executing")
                    tool_input = getattr(block, "input", {})
                    input_str = str(tool_input)
                    input_preview = input_str[:60].replace('\n', ' ')
                    if len(input_str) > 60:
                        input_preview += "..."
                    tool_msg = f"\n[Tool: {tool_name} ...] `{input_preview}`\n"
                    ctx.full_response += tool_msg
                    if ctx.on_message:
                        ctx.on_message(tool_msg, True, ctx.full_response, ctx.anon_stats.copy())
                    log(f"[Agent SDK Client] Tool call: {tool_name}")
                    if len(ctx.tool_calls) >= ctx.max_iterations:
                        log(f"[Agent SDK Client] Max iterations ({ctx.max_iterations}) reached")
                        ctx.max_iterations_reached = True
        return False

    # Handle UserMessage - tool results
    if msg_class == "UserMessage" and hasattr(message, "content"):
        for block in message.content:
            if hasattr(block, "tool_use_id"):
                tool_use_id = getattr(block, "tool_use_id", "unknown")
                tool_content = getattr(block, "content", "")
                result_text = ""
                tool_anon_count = 0

                if isinstance(tool_content, str):
                    result_text = tool_content
                    anon_data = parse_anon_metadata(tool_content)
                    if anon_data:
                        tool_anon_count = anon_data['new']
                        ctx.anon_stats["total_entities"] = anon_data["total"]
                        ctx.anon_stats["tool_calls_anonymized"] += 1
                        ctx.anon_stats["mappings"].update(anon_data["mappings"])
                        if anon_data["entity_summary"]:
                            for part in anon_data["entity_summary"].split(","):
                                if ":" in part:
                                    etype, count = part.split(":")
                                    ctx.anon_stats["entity_types"][etype] = int(count)
                        result_text = re.sub(r'\n?<!--ANON:[^>]+-->', '', result_text)
                        log(f"[Agent SDK Client] Anonymized: {anon_data['new']} new")

                elif isinstance(tool_content, list):
                    parts = []
                    for sub in tool_content:
                        # SDK ToolResultBlock.content items can be:
                        # - objects with .text attribute (TextBlock)
                        # - dicts with "text" key ({"type": "text", "text": "..."})
                        sub_text = None
                        if hasattr(sub, "text"):
                            sub_text = sub.text
                        elif isinstance(sub, dict) and "text" in sub:
                            sub_text = sub["text"]
                        if sub_text:
                            parts.append(sub_text)
                            anon_data = parse_anon_metadata(sub_text)
                            if anon_data:
                                tool_anon_count += anon_data['new']
                                ctx.anon_stats["total_entities"] = anon_data["total"]
                                ctx.anon_stats["tool_calls_anonymized"] += 1
                                ctx.anon_stats["mappings"].update(anon_data["mappings"])
                                if anon_data["entity_summary"]:
                                    for part in anon_data["entity_summary"].split(","):
                                        if ":" in part:
                                            etype, count = part.split(":")
                                            ctx.anon_stats["entity_types"][etype] = int(count)
                                log(f"[Agent SDK Client] Anonymized: {anon_data['new']} new")
                    result_text = "\n".join(parts)
                    result_text = re.sub(r'\n?<!--ANON:[^>]+-->', '', result_text)

                tool_name = ctx.tool_id_to_name.get(tool_use_id) or (ctx.tool_calls[-1] if ctx.tool_calls else f"tool_{tool_use_id[:8]}")
                tool_duration = None
                if tool_name in ctx.tool_timings:
                    tool_duration = time.time() - ctx.tool_timings[tool_name]
                    ctx.tool_stats.append({"name": tool_name, "duration_s": tool_duration})
                    del ctx.tool_timings[tool_name]
                    log(f"[Agent SDK Client] Tool {tool_name} completed in {tool_duration:.2f}s")
                publish_tool_event(tool_name, "complete", tool_duration)
                result_tokens = estimate_tokens(result_text)
                ctx.tool_result_tokens += result_tokens
                ctx.token_breakdown["tools"] = ctx.tool_result_tokens
                add_dev_tool_result(tool_name, result_text, tool_anon_count)
                if tool_duration and tool_duration > 0:
                    old_pattern = re.escape(f"[Tool: {tool_name} ...]") + r"(\s*`[^`]*`)?"
                    new_marker = f"[Tool: {tool_name} | {tool_duration:.1f}s]"
                    ctx.full_response = re.sub(old_pattern, new_marker, ctx.full_response, count=1)
                    if ctx.on_message:
                        ctx.on_message("", False, ctx.full_response, ctx.anon_stats.copy())
        return False

    # Handle ResultMessage
    if msg_class == "ResultMessage":
        if hasattr(message, "total_cost_usd"):
            ctx.total_cost_usd = message.total_cost_usd
            log(f"[Agent SDK Client] Total cost: ${ctx.total_cost_usd:.4f}")
        if hasattr(message, "subtype"):
            if message.subtype == "success":
                if hasattr(message, "result") and message.result:
                    ctx.full_response = message.result
                log("[Agent SDK Client] Result: success")
                return True
            elif message.subtype in ("error", "error_during_execution"):
                error_msg = getattr(message, "error", "Unknown error")
                log(f"[Agent SDK Client] Result: error - {error_msg}")
                ctx.full_response = str(error_msg)
                return True
        return False

    if hasattr(message, "usage"):
        usage = message.usage
        if isinstance(usage, dict):
            ctx.total_input_tokens += usage.get("input_tokens", 0)
            ctx.total_output_tokens += usage.get("output_tokens", 0)

    return False


async def _run_agent_async(
    prompt: str,
    config: dict,
    agent_config: dict,
    on_tool_request: Optional[Callable] = None,
    on_message: Optional[Callable] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    anon_context: Optional[any] = None,
    resume_session_id: Optional[str] = None
) -> AgentResponse:
    """
    Run the Agent SDK asynchronously.

    Args:
        prompt: The task prompt
        config: Global config
        agent_config: Agent-specific config
        on_tool_request: Callback for tool approval (tool_name, input) -> bool
        on_message: Callback for streaming messages
        is_cancelled: Callback that returns True if task should be cancelled
        anon_context: Optional anonymization context with initial mappings

    Returns:
        AgentResponse with result
    """
    _ = config  # Reserved for future use

    # Check for ~/.claude.json collision (before proxy setup)
    _check_global_mcp_collision()

    if not is_available():
        return AgentResponse(
            success=False,
            content="",
            error="Claude Agent SDK not installed. Run: pip install claude-agent-sdk"
        )

    # Clean up orphan processes from previous runs before starting new ones
    # This prevents accumulation of zombie processes that cause timeout errors
    log("[Agent SDK] Cleaning up orphan processes...")
    _cleanup_orphan_claude_cli_processes()  # Claude CLI Node processes
    _cleanup_orphan_mcp_processes()         # MCP Server processes

    # Set API key from config as environment variable for API billing
    # Without this, the SDK uses Claude Code account/subscription
    api_key = agent_config.get("api_key", "")
    if api_key and not api_key.startswith("YOUR_") and len(api_key) > 10:
        os.environ["ANTHROPIC_API_KEY"] = api_key
        log("[Agent SDK] API-Key gesetzt - Abrechnung über Anthropic Console")
    else:
        # Remove API key to ensure SDK uses subscription
        os.environ.pop("ANTHROPIC_API_KEY", None)
        log("[Agent SDK] Kein API-Key - nutze Claude Code Account/Subscription")

    from claude_agent_sdk import query, ClaudeAgentOptions
    import sys

    # Build MCP servers config from our existing MCP files
    # Use absolute paths to ensure MCP servers can be found
    mcp_dir = get_mcp_dir()

    # Get the Python executable for MCP servers (handles compiled mode correctly)
    python_exe = get_mcp_python_executable()
    log(f"[Agent SDK] Python: {python_exe}")

    # Build mcpServers config (camelCase as per SDK docs)
    mcp_servers = {}

    # Get allowed_mcp pattern FIRST - needed for all transport modes
    # (regex like "outlook|billomat" to filter which MCPs are available)
    allowed_mcp_pattern = agent_config.get("allowed_mcp")
    if allowed_mcp_pattern:
        log(f"[Agent SDK] MCP filter: {allowed_mcp_pattern}")

    # Check MCP transport mode from backend config
    # Options: "inprocess" (in-process SDK MCP), "stdio" (subprocess), "sse"/"streamable-http" (proxy)
    from assistant.services.mcp_proxy_manager import get_mcp_transport
    mcp_transport = get_mcp_transport()

    # ==========================================================================
    # INPROCESS Transport (planfeature-018)
    # ==========================================================================
    # Tools run directly in the SDK process - no subprocess, no network, no proxy.
    # Eliminates all "MCP proxy: failed" errors completely.
    # Uses create_sdk_mcp_server() API from claude-agent-sdk.
    #
    # Benefits:
    # - No network connection issues
    # - Single process debugging
    # - Fastest startup (no subprocess spawn)
    # - Simplest architecture

    inprocess_server = None  # Will be set if using inprocess transport

    if mcp_transport == "inprocess":
        log("[Agent SDK] MCP transport: INPROCESS (no network, direct tool calls)")

        # Get session ID for anonymization
        from .task_context import get_task_context_or_none
        ctx = get_task_context_or_none()
        if ctx and ctx.session_id:
            session_id = ctx.session_id
        else:
            import uuid
            session_id = str(uuid.uuid4())[:8]

        os.environ["ANON_SESSION_ID"] = session_id
        log(f"[Agent SDK] Session ID: {session_id}")

        # Check if anonymization is enabled
        use_anonymize = agent_config.get("anonymize", False) or agent_config.get("use_anonymization_proxy", False)

        # Get allowed_tools and tool_mode from agent config
        allowed_tools_list = agent_config.get("allowed_tools")
        blocked_tools_list = agent_config.get("blocked_tools")
        tool_mode_config = agent_config.get("tool_mode", "full")

        # Discover and convert tools to SDK format
        from .tool_bridge import get_sdk_mcp_tools
        sdk_tools = get_sdk_mcp_tools(
            mcp_filter=allowed_mcp_pattern,
            allowed_tools=allowed_tools_list,
            blocked_tools=blocked_tools_list,
            tool_mode=tool_mode_config,
            use_anonymization=use_anonymize,
            session_id=session_id,
            config=config
        )

        if sdk_tools:
            # Create in-process MCP server
            from claude_agent_sdk import create_sdk_mcp_server
            inprocess_server = create_sdk_mcp_server(
                name="deskagent",
                version="1.0.0",
                tools=sdk_tools
            )

            # For inprocess, we pass the server directly - no mcp_servers dict needed
            # The server will be added to options later
            mcp_servers = {}  # Empty - inprocess_server is passed separately
            use_proxy = False

            log(f"[Agent SDK] Created in-process MCP server with {len(sdk_tools)} tools")
            if use_anonymize:
                log(f"[Agent SDK] Anonymization enabled for in-process tools")
                # Seed in-memory cache with prompt mappings (fix for plan-080)
                if anon_context and hasattr(anon_context, 'mappings') and anon_context.mappings:
                    from .tool_bridge import seed_sdk_anon_context
                    seed_sdk_anon_context(session_id, anon_context)
                    log(f"[Agent SDK] Seeded anon cache with {len(anon_context.mappings)} prompt mappings")
        else:
            log("[Agent SDK] Warning: No SDK tools discovered, falling back to stdio")
            mcp_transport = "stdio"  # Fallback

    # stdio = direct subprocess (old behavior before SDK 0.1.28)
    # With anonymize=true, we start the proxy as a subprocess instead of HTTP server
    if mcp_transport == "stdio":
        use_anonymize = agent_config.get("anonymize", False) or agent_config.get("use_anonymization_proxy", False)

        if use_anonymize:
            # Proxy as subprocess (like before Feb 2026)
            import uuid as _uuid
            proxy_mcp = mcp_dir / "anonymization_proxy_mcp.py"
            session_id = str(_uuid.uuid4())[:8]

            proxy_args = [str(proxy_mcp), "--session", session_id]
            if allowed_mcp_pattern:
                proxy_args.extend(["--filter", allowed_mcp_pattern])

            proxy_env = _build_mcp_env()

            # Direct Python call like CherryPick (no cmd /c wrapper, no type field)
            mcp_servers["proxy"] = {
                "command": python_exe,
                "args": proxy_args,
                "env": proxy_env
            }

            use_proxy = True
            log(f"[Agent SDK] MCP transport: STDIO + Anonymization Proxy (session: {session_id})")
        else:
            use_proxy = False
            log(f"[Agent SDK] MCP transport: STDIO (direct, no proxy)")
    elif mcp_transport == "inprocess":
        # Inprocess: use_proxy stays False (set at declaration)
        # Anonymization is handled in-process by tool_bridge._anonymize_sdk_result()
        pass
    else:
        # HTTP/SSE proxy mode - use proxy if anonymization is configured
        # The central decision was already made in __init__.py via resolve_anonymization_setting()
        use_proxy = agent_config.get("use_anonymization_proxy", False)
        log(f"[Agent SDK] MCP transport: {mcp_transport.upper()}")

    # Load tool→MCP mapping for allowed_mcp enforcement in can_use_tool callback
    tool_to_mcp_mapping = load_tool_mcp_mapping() if allowed_mcp_pattern else {}

    if use_proxy and mcp_transport not in ("stdio", "inprocess"):
        # HTTP/SSE Transport Approach: Start proxy as HTTP server and pass URL to SDK
        # Note: HTTP (Streamable HTTP) is recommended, SSE is deprecated
        # See: https://github.com/anthropics/claude-code/issues/15215
        #
        # IMPORTANT: Skip this for stdio/inprocess - they already set mcp_servers above!

        # Get session ID from TaskContext (for V2 Link Registry and anonymization)
        from .task_context import get_task_context_or_none
        ctx = get_task_context_or_none()
        if ctx and ctx.session_id:
            session_id = ctx.session_id
            log(f"[Agent SDK] Using DeskAgent session_id: {session_id}")
        else:
            # Fallback to UUID if no session context (shouldn't happen)
            import uuid
            session_id = str(uuid.uuid4())[:8]
            log(f"[Agent SDK] Fallback to UUID session: {session_id}")

        # Set ANON_SESSION_ID env var - proxy reads this at runtime
        # This enables per-session anonymization context
        os.environ["ANON_SESSION_ID"] = session_id
        log(f"[Agent SDK] Set ANON_SESSION_ID={session_id}")

        # Start HTTP proxy server (if not already running)
        from assistant.services.mcp_proxy_manager import ensure_proxy_running, get_proxy_url, get_mcp_transport
        if ensure_proxy_running():
            # Get configured transport and URL
            transport = get_mcp_transport()
            proxy_url = get_proxy_url(session_id=session_id, mcp_filter=allowed_mcp_pattern)

            # Configure MCP server based on transport
            if transport == "sse":
                # SSE transport - deprecated but stable (no 400 Bad Request bug)
                # SSE uses /sse endpoint instead of /mcp
                sse_url = proxy_url.replace("/mcp", "/sse")
                mcp_servers["proxy"] = {
                    "type": "sse",
                    "url": sse_url
                }
                transport_label = "SSE"
            else:
                # Streamable HTTP transport (default)
                mcp_servers["proxy"] = {
                    "type": "http",
                    "url": proxy_url
                }
                transport_label = "HTTP"

            if allowed_mcp_pattern:
                log(f"[Agent SDK] ✓ Using Anonymization Proxy ({transport_label}) with MCP filter: {allowed_mcp_pattern}")
            else:
                log(f"[Agent SDK] ✓ Using Anonymization Proxy ({transport_label}) - all tools")
            log(f"[Agent SDK] Proxy URL: {mcp_servers['proxy']['url']}")
        else:
            log(f"[Agent SDK] ✗ Failed to start HTTP proxy - falling back to no proxy")
            use_proxy = False

        # Write initial mappings to known path based on session ID
        # (deterministic path that proxy can find via session ID)
        if anon_context and hasattr(anon_context, 'mappings') and anon_context.mappings:
            from paths import get_logs_dir
            temp_dir = get_logs_dir().parent / ".temp"
            temp_dir.mkdir(exist_ok=True)
            init_file = temp_dir / f"anon_init_{session_id}.json"
            mappings_json = json.dumps(anon_context.mappings, ensure_ascii=False)
            init_file.write_text(mappings_json, encoding='utf-8')
            log(f"[Agent SDK] Wrote {len(anon_context.mappings)} mappings to {init_file.name}")

    if not use_proxy and mcp_transport != "inprocess":
        # Auto-discover MCP servers using centralized discovery
        # Skip for inprocess transport: tools are already registered via tool_bridge
        from .base import discover_mcp_servers

        # Build minimal environment for MCP servers (whitelist, not full os.environ)
        mcp_env = _build_mcp_env()

        for server in discover_mcp_servers(allowed_mcp_pattern):
            server_name = server['name']

            if server['type'] == 'file':
                # Legacy *_mcp.py file
                server_path = str(server['path'])
            else:
                # Package-based MCP: run __init__.py directly
                server_path = str(server['path'] / "__init__.py")

            # Direct Python call like CherryPick (no cmd /c wrapper, no type field)
            mcp_servers[server_name] = {
                "command": python_exe,
                "args": [server_path],
                "env": mcp_env
            }
            suffix = " (package)" if server['type'] != 'file' else ""
            log(f"[Agent SDK] MCP: {server_name}{suffix}")

        log(f"[Agent SDK] Discovered {len(mcp_servers)} MCP servers")
    elif mcp_transport == "inprocess" and not use_proxy:
        log(f"[Agent SDK] Inprocess transport: skipping stdio MCP discovery (tools already in-process)")

    # Permission mode - bypassPermissions avoids "Stream closed" errors
    # The "default" mode causes race conditions with parallel tool calls
    # See: https://github.com/anthropics/claude-agent-sdk-python/issues/265
    permission_mode = agent_config.get("permission_mode", "bypassPermissions")
    # Defense-in-depth: "default" mode is problematic in headless mode (causes Stream closed errors)
    if permission_mode == "default":
        log(f"[Agent SDK] WARNING: permission_mode 'default' overridden to 'bypassPermissions' for headless mode")
        permission_mode = "bypassPermissions"

    # SDK Mode - extended enables new features (sessions, AskUserQuestion, structured outputs)
    sdk_mode = _get_sdk_mode(agent_config, config)
    use_extended_mode = sdk_mode == "extended"
    if use_extended_mode:
        log(f"[Agent SDK] Mode: EXTENDED (sessions, AskUserQuestion, structured outputs enabled)")
    else:
        log(f"[Agent SDK] Mode: legacy")

    # Get allowed_tools whitelist for filtering (list like ["read_file", "search_documents"])
    allowed_tools = agent_config.get("allowed_tools")
    if allowed_tools:
        log(f"[Agent SDK] Tool whitelist: {allowed_tools}")

    # Get tool_mode for read-only restriction ("full" or "read_only")
    tool_mode = agent_config.get("tool_mode", "full")
    if tool_mode == "read_only":
        log(f"[Agent SDK] Tool mode: READ-ONLY (write operations blocked)")

    # Build system prompt (base prompt + security warning + templates + knowledge)
    system_prompt = build_system_prompt(agent_config, config=config)

    # Add Claude SDK specific tool execution rules to prevent concurrency errors
    # Issue: https://github.com/anthropics/claude-code/issues/8763
    system_prompt += """

## Tool Execution Rules

CRITICAL: Execute MCP tools SEQUENTIALLY to prevent API errors.
- Complete one tool call and wait for its result before starting the next
- Do NOT batch multiple tool calls in a single response when they depend on external services
- Exception: Claude built-in tools (Read, Glob, Grep) can run in parallel safely
- This prevents "tool_use ids without tool_result blocks" API validation errors"""

    # Layer 3: System-Prompt instruction to prevent Bash fallback (Defense-in-Depth)
    if inprocess_server is not None:
        system_prompt += """

IMPORTANT: Use ONLY the available MCP tools (mcp__deskagent__*).
Do NOT use Bash, Task, Write, Edit or other built-in tools as fallback.
If a required tool is not available, inform the user instead of working around it."""
        log("[Agent SDK] Added MCP-only instruction to system prompt")

    # Read-only mode: SDK tools that are always allowed in read-only mode
    READ_ONLY_SDK_TOOLS = ["Read", "Grep", "Glob", "WebFetch", "WebSearch"]
    # MCP read-only tools are loaded dynamically from tool_bridge

    # SDK tools that require interactive terminal (not available in headless mode)
    BLOCKED_INTERACTIVE_TOOLS = ["AskUserQuestion"]

    # Tool approval callback - filter by tool_mode and allowed_tools whitelist
    async def can_use_tool(tool_name: str, tool_input: dict, _context):
        """Handle tool approval - filter by tool_mode and allowed_tools whitelist."""

        is_mcp_tool = tool_name.startswith("mcp__")
        short_name = tool_name.split("__")[-1] if is_mcp_tool else tool_name

        # === CHECK 0: Block interactive SDK tools (only in legacy mode) ===
        # In extended mode, AskUserQuestion is handled via SSE dialog
        if tool_name in BLOCKED_INTERACTIVE_TOOLS:
            if not use_extended_mode:
                log(f"[Agent SDK] ✗ Blocked interactive tool: {tool_name} (use QUESTION_NEEDED instead)")
                return {
                    "behavior": "deny",
                    "message": f"Tool {tool_name} is not available in DeskAgent (headless mode). "
                               f"Use QUESTION_NEEDED or CONFIRMATION_NEEDED markers in your response instead. "
                               f"Example: QUESTION_NEEDED: {{\"question\": \"...\", \"options\": [...]}}"
                }
            # Extended mode: AskUserQuestion will be handled in Phase 2
            # For now, allow it to pass through (SDK will handle it)
            log(f"[Agent SDK] ✓ Extended mode: allowing {tool_name}")

        # === CHECK 0.5: Block built-in tools in MCP-only mode ===
        # When running with in-process MCP, agents should ONLY use MCP tools
        # This prevents Bash fallback when MCP tools are missing
        if inprocess_server is not None and not is_mcp_tool:
            ALLOWED_SDK_TOOLS_MCP_MODE = {"TodoWrite", "AskUserQuestion"}
            if tool_name not in ALLOWED_SDK_TOOLS_MCP_MODE:
                log(f"[Agent SDK] ✗ Blocked built-in tool in MCP-only mode: {tool_name}")
                return {
                    "behavior": "deny",
                    "message": f"Tool {tool_name} is not available in MCP-only mode. "
                               f"Use only MCP tools (mcp__deskagent__*). "
                               f"If a required tool is missing, inform the user instead of working around it."
                }

        # === CHECK 1: tool_mode (read_only blocks write operations) ===
        if tool_mode == "read_only":
            if is_mcp_tool:
                # Check against explicit READ_ONLY_TOOLS sets from MCPs
                # This is SAFE - no prefix guessing, explicit whitelist only
                read_only_tools = get_read_only_tools()
                if short_name not in read_only_tools:
                    log(f"[Agent SDK] ✗ Blocked write tool (read_only mode): {tool_name} (not in READ_ONLY_TOOLS)")
                    return {"behavior": "deny", "message": f"Tool {short_name} blocked in read_only mode (not in READ_ONLY_TOOLS)"}
            else:
                # SDK built-in tools (Bash, Read, Write, etc.)
                if tool_name not in READ_ONLY_SDK_TOOLS:
                    log(f"[Agent SDK] ✗ Blocked SDK tool (read_only mode): {tool_name}")
                    return {"behavior": "deny", "message": f"Tool {tool_name} blocked in read_only mode"}

        # === CHECK 2: allowed_tools whitelist (explicit tool list) ===
        if allowed_tools:
            if is_mcp_tool:
                if short_name not in allowed_tools and tool_name not in allowed_tools:
                    log(f"[Agent SDK] ✗ Blocked MCP tool: {tool_name} (not in allowed_tools)")
                    return {"behavior": "deny", "message": f"Tool {short_name} not in allowed_tools"}
            else:
                # SDK built-in tools (case-insensitive match)
                tool_lower = tool_name.lower()
                allowed_lower = [t.lower() for t in allowed_tools]
                if tool_lower not in allowed_lower and tool_name not in allowed_tools:
                    log(f"[Agent SDK] ✗ Blocked SDK tool: {tool_name} (not in allowed_tools)")
                    return {"behavior": "deny", "message": f"Tool {tool_name} not in allowed_tools"}

        # === CHECK 3: allowed_mcp pattern (MCP server filter) ===
        # Defense in Depth: Check in BOTH proxy and stdio mode
        if allowed_mcp_pattern and is_mcp_tool:
            # Get MCP name from cache mapping (or fallback to prefix)
            mcp_name = get_mcp_name_for_tool(short_name, tool_to_mcp_mapping)

            # System tools (proxy_*) are always allowed - F5 requirement
            # These are internal proxy management tools, not actual MCP server tools
            if mcp_name == "proxy":
                pass  # Allow proxy system tools
            # Check against allowed_mcp pattern (regex match)
            elif not re.search(allowed_mcp_pattern, mcp_name, re.IGNORECASE):
                log(f"[Agent SDK] ✗ Blocked: {tool_name} (MCP '{mcp_name}' not in '{allowed_mcp_pattern}')")
                return {
                    "behavior": "deny",
                    "message": f"MCP '{mcp_name}' nicht erlaubt. Erlaubt: {allowed_mcp_pattern}. "
                               f"Nutze Tools von erlaubten MCP-Servern."
                }

        # === APPROVED ===
        log(f"[Agent SDK] ✓ Approved: {tool_name}")
        if tool_input:
            # Log input summary (truncated)
            input_str = str(tool_input)[:100]
            log(f"[Agent SDK]   Input: {input_str}...")
        return {"behavior": "allow", "updatedInput": tool_input}

    full_response = ""
    tool_calls = []
    start_time = time.time()
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read_tokens = 0
    total_cache_creation_tokens = 0
    total_cost_usd = None
    processed_message_ids = set()  # Deduplicate usage by message ID
    # Default to claude-sonnet-4 for cost calculation (typical model used by Claude Code)
    model_name = "claude-sonnet-4"

    # Track anonymization stats across all tool calls
    anon_stats = {
        "total_entities": 0,
        "entity_types": {},  # {type: count}
        "tool_calls_anonymized": 0,
        "mappings": {}  # {placeholder: original} for de-anonymization
    }

    # SDK Extended Mode: Track session ID for resume capability
    sdk_session_id = None

    # Track tool execution times
    tool_timings = {}  # {tool_name: start_time}
    tool_id_to_name = {}  # {tool_use_id: tool_name} for matching results to calls
    tool_stats = []  # List of {name, duration_s} for summary

    # === PROXY MODE: Rewrite MCP tool names in prompt ===
    # When proxy is active, replace mcp__X__tool with mcp__proxy__tool
    # This ensures agents use the proxy for de-anonymization
    if use_proxy and allowed_mcp_pattern:
        # Note: re is imported at module level (line 14)
        # Pattern: mcp__<server>__<tool> where server matches allowed_mcp_pattern
        # Replace with mcp__proxy__<tool>
        pattern = rf'mcp__({allowed_mcp_pattern})__(\w+)'
        replacement = r'mcp__proxy__\2'
        original_prompt = prompt
        prompt = re.sub(pattern, replacement, prompt, flags=re.IGNORECASE)
        if prompt != original_prompt:
            # Count replacements
            replacements = len(re.findall(pattern, original_prompt, flags=re.IGNORECASE))
            log(f"[Agent SDK] Rewrote {replacements} MCP tool references to use proxy")

    # === CONTEXT TRACKING ===
    # Estimate initial context size
    system_prompt_tokens = estimate_tokens(system_prompt)
    user_prompt_tokens = estimate_tokens(prompt)
    tool_result_tokens = 0  # Accumulated from tool results

    log(f"[Agent SDK] CONTEXT ESTIMATE:")
    log(f"[Agent SDK]    System prompt: {format_tokens(system_prompt_tokens)} tokens ({len(system_prompt)} chars)")
    log(f"[Agent SDK]    User prompt: {format_tokens(user_prompt_tokens)} tokens ({len(prompt)} chars)")
    log(f"[Agent SDK]    Initial total: {format_tokens(system_prompt_tokens + user_prompt_tokens)} tokens")

    # Capture context for Developer Mode debugging
    capture_dev_context(system_prompt=system_prompt, user_prompt=prompt, model=model_name)

    # Write complete prompt to log file (overwritten each time)
    # For SDK, we pass MCP server names since individual tools are loaded dynamically
    if use_proxy:
        mcp_tool_list = [{"name": "MCP:proxy (HTTP)"}]
    else:
        mcp_tool_list = [{"name": f"MCP:{name}"} for name in sorted(mcp_servers.keys())]
    write_prompt_log(system_prompt, prompt, agent_name="claude_sdk", model=model_name, tools=mcp_tool_list)

    # Get max_iterations from agent config (default: 50, higher than Gemini since SDK is more efficient)
    max_iterations = agent_config.get("max_iterations", 50)
    max_iterations_reached = False

    # Token breakdown for UI display (like Gemini)
    token_breakdown = {
        "system": system_prompt_tokens,
        "prompt": user_prompt_tokens,
        "tools": 0  # Will be updated as tools execute
    }

    # Send initial context breakdown to UI
    publish_context_event(
        iteration=0, max_iterations=max_iterations,
        system_tokens=system_prompt_tokens, prompt_tokens=user_prompt_tokens, tool_tokens=0
    )

    # Create async generator for streaming mode (required for can_use_tool)
    async def prompt_stream():
        """Yield the prompt as an async iterable for streaming mode."""
        # SDK expects {"type": "user", "message": {...}} format for streaming
        yield {
            "type": "user",
            "message": {
                "role": "user",
                "content": prompt
            }
        }

    try:
        # Get model from config (default to claude-opus-4-6 if not specified)
        configured_model = agent_config.get("model", "claude-opus-4-6")
        model_name = configured_model  # Use configured model for cost calculation
        log(f"[Agent SDK] Using model: {configured_model}")

        # Build options using ClaudeAgentOptions (snake_case parameters)
        # Handle in-process MCP server (planfeature-018)
        final_mcp_servers = mcp_servers.copy() if mcp_servers else {}
        if inprocess_server is not None:
            # In-process server is a dict with {type: "sdk", name: ..., instance: ...}
            # Add to mcp_servers dict with the server name as key
            final_mcp_servers["deskagent"] = inprocess_server
            log(f"[Agent SDK] Added in-process MCP server 'deskagent' to options")

        options_kwargs = {
            "mcp_servers": final_mcp_servers,
            "permission_mode": permission_mode,
            "system_prompt": system_prompt,
            "cwd": str(PROJECT_DIR),
            "can_use_tool": can_use_tool,
            "model": configured_model,
            # Load settings for permission_mode defaults (Bash allow/deny patterns)
            # When proxy is active: use "user" to load MCP from CLI registry (~/.claude.json)
            # Without --strict-mcp-config, CLI automatically reads user registry
            "setting_sources": ["user"] if use_proxy else ["project"],
            # Capture stderr output for debugging (stderr callback enables piping)
            "stderr": lambda line: log(f"[Agent SDK stderr] {line}")
        }

        # Block external MCP discovery for in-process mode (planfeature-031)
        # --strict-mcp-config tells CLI to only use MCPs from --mcp-config (none),
        # ignoring .mcp.json and all other MCP configurations
        if inprocess_server is not None:
            options_kwargs["extra_args"] = {"strict-mcp-config": None}
            log("[Agent SDK] Inprocess: --strict-mcp-config (no external MCPs)")

        # Find CLI path (portable installation or system PATH)
        cli_path = _find_cli_path()
        if cli_path:
            options_kwargs["cli_path"] = cli_path
            log(f"[Agent SDK] Using CLI: {cli_path}")

        # Block built-in tools based on tool_mode and proxy settings
        # This forces use of MCP tools and respects read_only mode
        disallowed = []

        # tool_mode: read_only - block all write operations
        if tool_mode == "read_only":
            disallowed.extend(["Write", "Edit", "Bash", "Task", "TodoWrite", "NotebookEdit"])
            log(f"[Agent SDK] read_only mode: blocking Write/Edit/Bash/Task/TodoWrite/NotebookEdit")

        # Proxy active - block built-in file tools to force MCP usage
        if use_proxy:
            if "Read" not in disallowed:
                disallowed.append("Read")
            if "Glob" not in disallowed:
                disallowed.append("Glob")
            if "Grep" not in disallowed:
                disallowed.append("Grep")
            log(f"[Agent SDK] Proxy active: blocking Read/Glob/Grep - use MCP tools instead")

        if disallowed:
            options_kwargs["disallowed_tools"] = disallowed
            log(f"[Agent SDK] disallowed_tools: {disallowed}")

        # Allow all MCP tools from our server
        # Without this, Claude sees the tools but can't use them (MCP permission requirement)
        if use_proxy:
            options_kwargs["allowed_tools"] = ["mcp__proxy__*"]
            log(f"[Agent SDK] allowed_tools: mcp__proxy__* (all proxy tools)")
        elif inprocess_server is not None:
            # In-process server uses "deskagent" as server name
            options_kwargs["allowed_tools"] = ["mcp__deskagent__*"]
            log(f"[Agent SDK] allowed_tools: mcp__deskagent__* (all in-process tools)")
            # Defense-in-Depth: Block built-in tools to prevent Bash fallback
            # Primary defense is can_use_tool() CHECK 0.5, this is backup
            builtin_blocked = ["Bash", "Task", "Write", "Edit", "NotebookEdit", "Read", "Glob", "Grep"]
            for tool in builtin_blocked:
                if tool not in disallowed:
                    disallowed.append(tool)
            log(f"[Agent SDK] MCP-only mode: blocking built-in tools: {builtin_blocked}")

        # Note: Proxy runs via SSE transport - session ID passed via URL parameter

        # SDK Extended Mode: Resume previous session
        if resume_session_id and use_extended_mode:
            options_kwargs["resume"] = resume_session_id
            log(f"[Agent SDK] Resuming session: {resume_session_id}")

        # SDK Extended Mode: Structured Outputs (output_schema in frontmatter)
        output_schema = agent_config.get("output_schema") if use_extended_mode else None
        if output_schema:
            log(f"[Agent SDK] Extended mode: using output_schema")
            # Note: output_format parameter depends on SDK version
            # Will be enabled when SDK supports it
            # options_kwargs["output_format"] = {"type": "json_schema", "schema": output_schema}

        options = ClaudeAgentOptions(**options_kwargs)

        log(f"[Agent SDK] Starting agent with prompt: {prompt[:100]}...")
        log(f"[Agent SDK] Permission mode: {permission_mode}")
        if use_proxy:
            log(f"[Agent SDK] MCP servers: proxy (HTTP transport)")
        elif inprocess_server is not None:
            log(f"[Agent SDK] MCP servers: deskagent (in-process via ClaudeSDKClient)")
        else:
            log(f"[Agent SDK] MCP servers: {list(mcp_servers.keys())}")

        # =============================================================
        # INPROCESS PATH: Use ClaudeSDKClient (planfeature-021)
        # =============================================================
        # When in-process MCP is configured, use ClaudeSDKClient for
        # true in-process tool execution without CLI subprocess.
        if mcp_transport == "inprocess" and inprocess_server is not None:
            log("[Agent SDK] Using ClaudeSDKClient path for in-process MCP")

            # Create message handler context
            # Note: session_id is always defined in inprocess block (lines 1464/1467)
            ctx = MessageHandlerContext(
                on_message=on_message,
                use_extended_mode=use_extended_mode,
                max_iterations=max_iterations,
                system_prompt_tokens=system_prompt_tokens,
                user_prompt_tokens=user_prompt_tokens,
                model_name=model_name,
                session_id=session_id,
                use_proxy=use_proxy
            )
            ctx.token_breakdown = {
                "system": system_prompt_tokens,
                "prompt": user_prompt_tokens,
                "tools": 0
            }

            # Get pricing from agent config
            pricing = agent_config.get("pricing", {})

            # Run with ClaudeSDKClient and return directly
            return await _run_with_sdk_client(
                prompt=prompt,
                options=options,
                ctx=ctx,
                is_cancelled=is_cancelled,
                pricing=pricing
            )

        # =============================================================
        # SUBPROCESS PATH: Use query() with CLI (existing behavior)
        # =============================================================
        # Use streaming mode (async generator) for can_use_tool support
        # Store generator reference for proper cleanup
        # Wrap with cancel watchdog for immediate cancellation response (checks every 500ms)
        agent_gen = query(prompt=prompt_stream(), options=options)
        try:
          async for message in _run_with_cancel_watchdog(agent_gen, is_cancelled):
            # Additional inline check for fast cancellation detection
            if is_cancelled and is_cancelled():
                log("[Agent SDK] Cancellation requested - stopping agent")
                raise CancelledException("Task cancelled by user")

            # Debug: Log message type
            msg_type = type(message).__name__
            log(f"[Agent SDK] Message type: {msg_type}")

            # Handle dictionary-style messages (as per docs)
            if isinstance(message, dict):
                m_type = message.get("type")
                m_subtype = message.get("subtype")

                # Debug: log all keys for unknown message types to discover usage data
                if m_type not in ("assistant", "tool_result", "system", "result"):
                    log(f"[Agent SDK] Message keys: {list(message.keys())}")

                if m_type == "system" and m_subtype == "init":
                    # SDK Extended Mode: Extract session_id for resume capability
                    if use_extended_mode:
                        session_id_from_sdk = message.get("session_id")
                        if session_id_from_sdk:
                            sdk_session_id = session_id_from_sdk
                            log(f"[Agent SDK] Extended mode session: {sdk_session_id}")

                    # Check MCP server status
                    mcp_status = message.get("mcp_servers", [])
                    for server in mcp_status:
                        status = server.get("status", "unknown")
                        name = server.get("name", "unknown")
                        log(f"[Agent SDK] MCP {name}: {status}")
                        if status != "connected":
                            log(f"[Agent SDK] WARNING: MCP server {name} not connected!")

                elif m_type == "assistant":
                    content = message.get("content", [])
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text = block.get("text", "")
                                # Detect API errors in real-time and provide user-friendly messages
                                if "API Error: 400" in text and "concurrency" in text.lower():
                                    log(f"[Agent SDK] Detected API 400 concurrency error in stream - replacing with user-friendly message")
                                    user_friendly_error = (
                                        "⚠️ **Temporärer API-Fehler**\n\n"
                                        "Die Claude API hatte ein Timing-Problem bei der Tool-Verarbeitung.\n\n"
                                        "**Bitte nochmal versuchen** - dieser Fehler ist temporär und tritt manchmal "
                                        "bei komplexen Aufgaben mit vielen Tool-Aufrufen auf.\n\n"
                                        "💡 *Tipp: Falls der Fehler wiederholt auftritt, die Aufgabe in kleinere Schritte aufteilen.*"
                                    )
                                    full_response = user_friendly_error
                                    if on_message:
                                        on_message(user_friendly_error, False, full_response, anon_stats.copy())
                                    continue
                                elif "API Error: 500" in text or ("500" in text and "Internal server error" in text):
                                    log(f"[Agent SDK] Detected API 500 server error in stream - replacing with user-friendly message")
                                    user_friendly_error = (
                                        "⚠️ **Server-Fehler bei Claude**\n\n"
                                        "Die Claude API meldet einen internen Server-Fehler (500).\n\n"
                                        "**Das ist ein Problem auf Anthropic's Seite** - nicht bei dir.\n\n"
                                        "**Bitte nochmal versuchen** - meist ist der Fehler nach wenigen Sekunden behoben.\n\n"
                                        "💡 *Tipp: Bei anhaltenden Problemen den [Anthropic Status](https://status.anthropic.com) prüfen.*"
                                    )
                                    full_response = user_friendly_error
                                    if on_message:
                                        on_message(user_friendly_error, False, full_response, anon_stats.copy())
                                    continue
                                full_response += text
                                if on_message:
                                    # Pass full anon_stats for real-time badge updates
                                    on_message(text, False, full_response, anon_stats.copy())
                                log(f"[Agent SDK] Text: {text[:200]}...")
                            elif block.get("type") == "tool_use":
                                tool_name = block.get("name", "unknown")
                                tool_input = block.get("input", {})
                                tool_calls.append(tool_name)
                                # Store tool_use_id -> tool_name mapping for matching results
                                if block.get("id"):
                                    tool_id_to_name[block["id"]] = tool_name
                                # Update iteration progress for UI
                                update_dev_iteration(len(tool_calls), max_iterations)
                                # Publish context event with current token breakdown
                                publish_context_event(
                                    iteration=len(tool_calls), max_iterations=max_iterations,
                                    system_tokens=token_breakdown["system"],
                                    prompt_tokens=token_breakdown["prompt"],
                                    tool_tokens=token_breakdown["tools"]
                                )
                                # Start timing for this tool
                                tool_timings[tool_name] = time.time()
                                # Send SSE event for UI spinner
                                publish_tool_event(tool_name, "executing")
                                # Show tool name with a short input preview
                                input_str = str(tool_input)
                                input_preview = input_str[:60].replace('\n', ' ')
                                if len(input_str) > 60:
                                    input_preview += "..."
                                # Include input preview in UI message
                                tool_msg = f"\n[Tool: {tool_name} ...] `{input_preview}`\n"
                                full_response += tool_msg
                                if on_message:
                                    on_message(tool_msg, True, full_response, anon_stats.copy())
                                log(f"[Agent SDK] Tool call: {tool_name}")
                                log(f"[Agent SDK] Tool input: {input_str[:200]}")

                                # Check max_iterations limit
                                if len(tool_calls) >= max_iterations:
                                    log(f"[Agent SDK] ⚠️ Max iterations ({max_iterations}) reached - stopping agent")
                                    max_iterations_reached = True
                                    # We can't break the SDK loop directly, but we'll add warning at the end
                                    # The SDK will continue until it gets a response, but we'll mark it

                elif m_type == "tool_result":
                    tool_name = message.get("tool_name", "unknown")
                    result = message.get("result", "")
                    result_str = str(result)

                    # Calculate tool execution time
                    tool_duration = 0
                    if tool_name in tool_timings:
                        tool_duration = time.time() - tool_timings[tool_name]
                        tool_stats.append({"name": tool_name, "duration_s": tool_duration})
                        del tool_timings[tool_name]
                        log(f"[Agent SDK] Tool {tool_name} completed in {tool_duration:.2f}s")
                    else:
                        # Tool wasn't in timings (e.g., parallel calls) - still mark complete
                        log(f"[Agent SDK] Tool {tool_name} completed (no timing data)")
                    # Always send SSE event for UI to stop spinner
                    publish_tool_event(tool_name, "complete", tool_duration if tool_duration > 0 else None)

                    # Parse anonymization metadata from proxy responses
                    anon_data = parse_anon_metadata(result_str)
                    if anon_data:
                        log(f"[Agent SDK] Anonymized: {anon_data['new']} new ({anon_data['total']} total) - {anon_data['entity_summary']}")
                        # Update anon_stats with mappings
                        anon_stats["total_entities"] = anon_data["total"]
                        # Count every tool call with anonymization (even if no new entities)
                        anon_stats["tool_calls_anonymized"] += 1
                        anon_stats["mappings"].update(anon_data["mappings"])
                        # Parse entity types
                        if anon_data["entity_summary"]:
                            for part in anon_data["entity_summary"].split(","):
                                if ":" in part:
                                    etype, count = part.split(":")
                                    anon_stats["entity_types"][etype] = int(count)
                        # Remove metadata from result for display
                        result_str = re.sub(r'\n?<!--ANON:[^>]+-->', '', result_str)

                        # LIVE UPDATE: Send anonymization stats immediately (not just at end)
                        # This ensures the badge counter updates during execution
                        if on_message and anon_stats["total_entities"] > 0:
                            on_message("", False, full_response, anon_stats.copy())

                    # Track tool result tokens
                    result_tokens = estimate_tokens(result_str)
                    tool_result_tokens += result_tokens
                    current_total = system_prompt_tokens + user_prompt_tokens + tool_result_tokens
                    context_limit = get_context_limit(model_name)
                    context_pct = current_total / context_limit * 100
                    log(f"[Agent SDK] Tool result for {tool_name}: {result_str[:200]}...")
                    log(f"[Agent SDK] +{format_tokens(result_tokens)} tokens -> Total: {format_tokens(current_total)} ({context_pct:.1f}% of {format_tokens(context_limit)} limit)")

                    # Context window warnings
                    if context_pct >= 95:
                        log(f"[Agent SDK] ⚠️ CRITICAL: Context {context_pct:.0f}% full! Agent may fail or truncate.")
                    elif context_pct >= 80:
                        log(f"[Agent SDK] ⚠️ WARNING: Context {context_pct:.0f}% full. Consider breaking task into smaller parts.")

                    # Update token breakdown and publish to UI
                    token_breakdown["tools"] = tool_result_tokens
                    publish_context_event(
                        iteration=len(tool_calls), max_iterations=max_iterations,
                        system_tokens=token_breakdown["system"],
                        prompt_tokens=token_breakdown["prompt"],
                        tool_tokens=token_breakdown["tools"]
                    )

                    # Capture for Developer Mode (with anon count from proxy metadata)
                    anon_count = anon_data['new'] if anon_data else 0
                    add_dev_tool_result(tool_name, result_str, anon_count)

                    # Update the tool marker in response with timing
                    # Use regex to match marker with optional input preview: [Tool: name ...] `preview`
                    if tool_duration > 0:
                        # Pattern matches: [Tool: tool_name ...] followed by optional ` backtick preview `
                        old_pattern = re.escape(f"[Tool: {tool_name} ...]") + r"(\s*`[^`]*`)?"
                        new_marker = f"[Tool: {tool_name} | {tool_duration:.1f}s]"
                        full_response = re.sub(old_pattern, new_marker, full_response, count=1)
                        if on_message:
                            on_message("", False, full_response, anon_stats.copy())

                    # Add tool result to response (shortened)
                    result_msg = f"[Result: {result_str[:100]}]\n"
                    full_response += result_msg

                elif m_type == "result":
                    log(f"[Agent SDK] Result: {m_subtype}")
                    log(f"[Agent SDK] Result keys: {list(message.keys())}")
                    # Extract usage stats if available
                    if "usage" in message:
                        usage = message.get("usage", {})
                        total_input_tokens += usage.get("input_tokens", 0)
                        total_output_tokens += usage.get("output_tokens", 0)
                        total_cache_read_tokens += usage.get("cache_read_input_tokens", 0)
                        total_cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)
                        log(f"[Agent SDK] Usage: {total_input_tokens} in, {total_output_tokens} out, cache: {total_cache_read_tokens} read, {total_cache_creation_tokens} write")
                    if "model" in message:
                        model_name = message.get("model", model_name)
                    # Also check for total_cost or session stats
                    if "total_cost" in message:
                        log(f"[Agent SDK] Total cost from SDK: {message.get('total_cost')}")
                    if m_subtype == "success":
                        result_text = message.get("result", "")
                        if result_text:
                            full_response = result_text
                        break
                    elif m_subtype == "error" or m_subtype == "error_during_execution":
                        error_msg = message.get("error", "Unknown error")
                        log(f"[Agent SDK] Error: {error_msg}")
                        duration = time.time() - start_time
                        return AgentResponse(
                            success=False,
                            content=full_response,
                            error=str(error_msg),
                            model=model_name,
                            duration_seconds=duration
                        )

                # Track usage from any message type
                if "usage" in message and m_type != "result":
                    usage = message.get("usage", {})
                    if isinstance(usage, dict):
                        inp = usage.get("input_tokens", 0)
                        out = usage.get("output_tokens", 0)
                        cache_read = usage.get("cache_read_input_tokens", 0)
                        cache_create = usage.get("cache_creation_input_tokens", 0)
                        if inp > 0 or out > 0 or cache_read > 0 or cache_create > 0:
                            total_input_tokens += inp
                            total_output_tokens += out
                            total_cache_read_tokens += cache_read
                            total_cache_creation_tokens += cache_create
                            log(f"[Agent SDK] Usage update: {total_input_tokens} in, {total_output_tokens} out, cache: {total_cache_read_tokens} read, {total_cache_creation_tokens} write")

                # Check for model info in any message
                if "model" in message and message.get("model"):
                    new_model = message.get("model")
                    if new_model and "claude" in new_model.lower():
                        model_name = new_model
                        log(f"[Agent SDK] Model: {model_name}")

            # Handle object-style messages (SDK returns typed objects)
            else:
                msg_class = type(message).__name__
                log(f"[Agent SDK] Object message: {msg_class}")

                # Debug: Log SystemMessage attributes to understand MCP status
                if msg_class == "SystemMessage":
                    # Log all attributes for debugging
                    attrs = [a for a in dir(message) if not a.startswith('_')]
                    log(f"[Agent SDK] SystemMessage attrs: {attrs}")
                    # Log subtype
                    if hasattr(message, "subtype"):
                        log(f"[Agent SDK] SystemMessage subtype: {message.subtype}")
                    # Log data content (may contain MCP info)
                    if hasattr(message, "data"):
                        data = message.data
                        if isinstance(data, dict):
                            log(f"[Agent SDK] SystemMessage data keys: {list(data.keys())}")

                            # SDK Extended Mode: Extract session_id from data for resume
                            if use_extended_mode and "session_id" in data:
                                session_id_from_sdk = data["session_id"]
                                if session_id_from_sdk:
                                    sdk_session_id = session_id_from_sdk
                                    log(f"[Agent SDK] Extended mode session: {sdk_session_id}")

                            # Check for tools in data
                            if "tools" in data:
                                tools_list = data["tools"]
                                log(f"[Agent SDK] Tools available: {len(tools_list)} tools")
                                # Log first few tool names to see what's available
                                tool_names = [t.get("name", "?") if isinstance(t, dict) else str(t) for t in (tools_list or [])[:10]]
                                log(f"[Agent SDK] First 10 tools: {tool_names}")

                            # Check for mcp_servers in data
                            if "mcp_servers" in data:
                                mcp_status = data["mcp_servers"]
                                log(f"[Agent SDK] MCP servers in data: {len(mcp_status)} servers")
                                for server in (mcp_status or []):
                                    if isinstance(server, dict):
                                        status = server.get("status", "unknown")
                                        name = server.get("name", "unknown")
                                        log(f"[Agent SDK] MCP {name}: {status}")
                                        if status != "connected":
                                            log(f"[Agent SDK] WARNING: MCP server {name} not connected!")
                        else:
                            log(f"[Agent SDK] SystemMessage data: {type(data).__name__} = {str(data)[:500]}")

                # Handle UserMessage - contains tool results from MCP servers
                if msg_class == "UserMessage" and hasattr(message, "content"):
                    for block in message.content:
                        # Tool result blocks have tool_use_id attribute
                        has_tool_use_id = hasattr(block, "tool_use_id")
                        if has_tool_use_id:
                            tool_use_id = getattr(block, "tool_use_id", "unknown")
                            tool_content = getattr(block, "content", "")
                            log(f"[Agent SDK] Tool result content type: {type(tool_content).__name__}, preview: {str(tool_content)[:200]}")

                            # Extract tool result text for dev context
                            result_text = ""
                            tool_anon_count = 0  # Track PII count for this tool
                            if isinstance(tool_content, str):
                                result_text = tool_content
                                # Parse anonymization metadata from proxy responses
                                anon_data = parse_anon_metadata(tool_content)
                                if anon_data:
                                    log(f"[Agent SDK] Anonymized: {anon_data['new']} new ({anon_data['total']} total) - {anon_data['entity_summary']}")
                                    tool_anon_count = anon_data['new']
                                    # Update anon_stats with mappings
                                    anon_stats["total_entities"] = anon_data["total"]
                                    # Count every tool call with anonymization (even if no new entities)
                                    anon_stats["tool_calls_anonymized"] += 1
                                    anon_stats["mappings"].update(anon_data["mappings"])
                                    if anon_data["entity_summary"]:
                                        for part in anon_data["entity_summary"].split(","):
                                            if ":" in part:
                                                etype, count = part.split(":")
                                                anon_stats["entity_types"][etype] = int(count)
                                    # Remove metadata for clean result
                                    result_text = re.sub(r'\n?<!--ANON:[^>]+-->', '', result_text)
                            elif isinstance(tool_content, list):
                                # Content can be a list of blocks (objects with .text or dicts with "text" key)
                                parts = []
                                for sub in tool_content:
                                    sub_text = None
                                    if hasattr(sub, "text"):
                                        sub_text = sub.text
                                    elif isinstance(sub, dict) and "text" in sub:
                                        sub_text = sub["text"]
                                    if sub_text:
                                        parts.append(sub_text)
                                        anon_data = parse_anon_metadata(sub_text)
                                        if anon_data:
                                            log(f"[Agent SDK] Anonymized: {anon_data['new']} new ({anon_data['total']} total) - {anon_data['entity_summary']}")
                                            tool_anon_count += anon_data['new']
                                            # Update anon_stats with mappings
                                            anon_stats["total_entities"] = anon_data["total"]
                                            # Count every tool call with anonymization (even if no new entities)
                                            anon_stats["tool_calls_anonymized"] += 1
                                            anon_stats["mappings"].update(anon_data["mappings"])
                                            if anon_data["entity_summary"]:
                                                for part in anon_data["entity_summary"].split(","):
                                                    if ":" in part:
                                                        etype, count = part.split(":")
                                                        anon_stats["entity_types"][etype] = int(count)
                                result_text = "\n".join(parts)
                                # Remove metadata for clean result
                                result_text = re.sub(r'\n?<!--ANON:[^>]+-->', '', result_text)

                            # LIVE UPDATE: Send anonymization stats immediately (not just at end)
                            # This ensures the badge counter updates during execution
                            if on_message and anon_stats["total_entities"] > 0:
                                on_message("", False, full_response, anon_stats.copy())

                            # Capture tool result for Developer Mode (use tool_use_id as tool name)
                            if result_text:
                                # Find matching tool name using id->name mapping, fallback to last call
                                tool_name = tool_id_to_name.get(tool_use_id) or (tool_calls[-1] if tool_calls else f"tool_{tool_use_id[:8]}")
                                # Calculate timing if we have it
                                tool_duration = None
                                if tool_name in tool_timings:
                                    tool_duration = time.time() - tool_timings[tool_name]
                                    del tool_timings[tool_name]
                                    log(f"[Agent SDK] Tool {tool_name} completed in {tool_duration:.2f}s")
                                else:
                                    log(f"[Agent SDK] Tool {tool_name} completed (no timing data)")
                                # Send SSE event for UI to stop spinner
                                publish_tool_event(tool_name, "complete", tool_duration)
                                add_dev_tool_result(tool_name, result_text, tool_anon_count)
                                # Track tokens
                                result_tokens = estimate_tokens(result_text)
                                tool_result_tokens += result_tokens
                                current_total = system_prompt_tokens + user_prompt_tokens + tool_result_tokens
                                context_limit = get_context_limit(model_name)
                                context_pct = current_total / context_limit * 100
                                log(f"[Agent SDK] +{format_tokens(result_tokens)} tokens -> Total: {format_tokens(current_total)} ({context_pct:.1f}% of {format_tokens(context_limit)} limit)")

                                # Context window warnings
                                if context_pct >= 95:
                                    log(f"[Agent SDK] ⚠️ CRITICAL: Context {context_pct:.0f}% full! Agent may fail or truncate.")
                                elif context_pct >= 80:
                                    log(f"[Agent SDK] ⚠️ WARNING: Context {context_pct:.0f}% full. Consider breaking task into smaller parts.")

                                # Update token breakdown and publish to UI
                                token_breakdown["tools"] = tool_result_tokens
                                publish_context_event(
                                    iteration=len(tool_calls), max_iterations=max_iterations,
                                    system_tokens=token_breakdown["system"],
                                    prompt_tokens=token_breakdown["prompt"],
                                    tool_tokens=token_breakdown["tools"]
                                )

                # Extract usage from AssistantMessage (deduplicate by ID)
                if hasattr(message, "usage") and hasattr(message, "id"):
                    msg_id = message.id
                    if msg_id and msg_id not in processed_message_ids:
                        processed_message_ids.add(msg_id)
                        usage = message.usage
                        if hasattr(usage, "input_tokens"):
                            total_input_tokens += usage.input_tokens or 0
                            total_output_tokens += usage.output_tokens or 0
                            # Extract cache tokens if available
                            if hasattr(usage, "cache_read_input_tokens"):
                                total_cache_read_tokens += usage.cache_read_input_tokens or 0
                            if hasattr(usage, "cache_creation_input_tokens"):
                                total_cache_creation_tokens += usage.cache_creation_input_tokens or 0
                            log(f"[Agent SDK] Usage from {msg_id}: {usage.input_tokens} in, {usage.output_tokens} out, cache: {total_cache_read_tokens} read, {total_cache_creation_tokens} write")
                        elif isinstance(usage, dict):
                            total_input_tokens += usage.get("input_tokens", 0)
                            total_output_tokens += usage.get("output_tokens", 0)
                            total_cache_read_tokens += usage.get("cache_read_input_tokens", 0)
                            total_cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)
                            log(f"[Agent SDK] Usage (dict) from {msg_id}: {usage}")

                # Extract model from message
                if hasattr(message, "model") and message.model:
                    model_name = message.model
                    log(f"[Agent SDK] Model: {model_name}")

                if hasattr(message, "content"):
                    for block in message.content:
                        if hasattr(block, "text"):
                            text = block.text
                            # Detect API errors in real-time and provide user-friendly messages
                            if "API Error: 400" in text and "concurrency" in text.lower():
                                log(f"[Agent SDK] Detected API 400 concurrency error in stream - replacing with user-friendly message")
                                user_friendly_error = (
                                    "⚠️ **Temporärer API-Fehler**\n\n"
                                    "Die Claude API hatte ein Timing-Problem bei der Tool-Verarbeitung.\n\n"
                                    "**Bitte nochmal versuchen** - dieser Fehler ist temporär und tritt manchmal "
                                    "bei komplexen Aufgaben mit vielen Tool-Aufrufen auf.\n\n"
                                    "💡 *Tipp: Falls der Fehler wiederholt auftritt, die Aufgabe in kleinere Schritte aufteilen.*"
                                )
                                full_response = user_friendly_error
                                if on_message:
                                    on_message(user_friendly_error, False, full_response, anon_stats.copy())
                                continue
                            elif "API Error: 500" in text or ("500" in text and "Internal server error" in text):
                                log(f"[Agent SDK] Detected API 500 server error in stream - replacing with user-friendly message")
                                user_friendly_error = (
                                    "⚠️ **Server-Fehler bei Claude**\n\n"
                                    "Die Claude API meldet einen internen Server-Fehler (500).\n\n"
                                    "**Das ist ein Problem auf Anthropic's Seite** - nicht bei dir.\n\n"
                                    "**Bitte nochmal versuchen** - meist ist der Fehler nach wenigen Sekunden behoben.\n\n"
                                    "💡 *Tipp: Bei anhaltenden Problemen den [Anthropic Status](https://status.anthropic.com) prüfen.*"
                                )
                                full_response = user_friendly_error
                                if on_message:
                                    on_message(user_friendly_error, False, full_response, anon_stats.copy())
                                continue
                            full_response += text
                            if on_message:
                                on_message(text, False, full_response, anon_stats.copy())
                            log(f"[Agent SDK] Text: {text[:200]}...")
                        elif hasattr(block, "name"):
                            tool_name = block.name
                            tool_calls.append(tool_name)
                            # Store tool_use_id -> tool_name mapping for matching results
                            if hasattr(block, "id"):
                                tool_id_to_name[block.id] = tool_name
                            # Update iteration progress for UI
                            update_dev_iteration(len(tool_calls), max_iterations)
                            # Publish context event with current token breakdown
                            publish_context_event(
                                iteration=len(tool_calls), max_iterations=max_iterations,
                                system_tokens=token_breakdown["system"],
                                prompt_tokens=token_breakdown["prompt"],
                                tool_tokens=token_breakdown["tools"]
                            )
                            # Start timing for this tool (like dict-message path)
                            tool_timings[tool_name] = time.time()
                            # Send SSE event for UI spinner
                            publish_tool_event(tool_name, "executing")
                            # Get input preview if available
                            tool_input = getattr(block, "input", {})
                            input_str = str(tool_input)
                            input_preview = input_str[:60].replace('\n', ' ')
                            if len(input_str) > 60:
                                input_preview += "..."
                            # Use same marker format as dict-message path for consistency
                            tool_msg = f"\n[Tool: {tool_name} ...] `{input_preview}`\n"
                            full_response += tool_msg
                            if on_message:
                                on_message(tool_msg, True, full_response, anon_stats.copy())
                            log(f"[Agent SDK] Tool call: {tool_name}")

                            # Check max_iterations limit
                            if len(tool_calls) >= max_iterations:
                                log(f"[Agent SDK] ⚠️ Max iterations ({max_iterations}) reached - stopping agent")
                                max_iterations_reached = True
                        elif hasattr(block, "tool_use_id") and hasattr(block, "content"):
                            # Tool result block - update timing
                            tool_use_id = block.tool_use_id
                            # Find the tool name using id->name mapping, fallback to last call
                            result_tool_name = tool_id_to_name.get(tool_use_id) or (tool_calls[-1] if tool_calls else None)
                            if result_tool_name:
                                tool_duration = None
                                if result_tool_name in tool_timings:
                                    tool_duration = time.time() - tool_timings[result_tool_name]
                                    del tool_timings[result_tool_name]
                                    log(f"[Agent SDK] Tool {result_tool_name} completed in {tool_duration:.2f}s")
                                else:
                                    log(f"[Agent SDK] Tool {result_tool_name} completed (no timing data)")
                                # Always send SSE event for UI to stop spinner
                                publish_tool_event(result_tool_name, "complete", tool_duration)
                                # Update marker with duration
                                if tool_duration and tool_duration > 0:
                                    old_marker = f"[Tool: {result_tool_name} ...]"
                                    new_marker = f"[Tool: {result_tool_name} | {tool_duration:.1f}s]"
                                    full_response = full_response.replace(old_marker, new_marker)
                                    if on_message:
                                        on_message("", False, full_response, anon_stats.copy())

                # Handle ResultMessage - contains total_cost_usd
                if hasattr(message, "total_cost_usd"):
                    total_cost_usd = message.total_cost_usd
                    log(f"[Agent SDK] Total cost from SDK: ${total_cost_usd:.4f}")

                if hasattr(message, "subtype"):
                    if message.subtype == "success":
                        if hasattr(message, "result") and message.result:
                            full_response = message.result
                        break
                    elif message.subtype in ("error", "error_during_execution"):
                        return AgentResponse(
                            success=False,
                            content=full_response,
                            error=f"Agent error: {message}"
                        )
        finally:
            # Properly close the async generator to avoid "Task was destroyed" warnings
            await agent_gen.aclose()

        duration = time.time() - start_time
        log(f"[Agent SDK] === COMPLETED ===")
        log(f"[Agent SDK] Response length: {len(full_response)}")
        log(f"[Agent SDK] Tool calls: {tool_calls}")
        log(f"[Agent SDK] Duration: {duration:.1f}s")
        log(f"[Agent SDK] Tokens: {total_input_tokens} in, {total_output_tokens} out")
        if total_cache_read_tokens > 0 or total_cache_creation_tokens > 0:
            log(f"[Agent SDK] Cache tokens: {total_cache_read_tokens} read (90% off), {total_cache_creation_tokens} write")

        # Calculate cost from tokens + configured pricing (more accurate than SDK's total_cost_usd)
        # Include cache tokens for accurate cost calculation
        pricing = agent_config.get("pricing", {})
        calculated_cost = None
        has_tokens = total_input_tokens > 0 or total_output_tokens > 0 or total_cache_read_tokens > 0 or total_cache_creation_tokens > 0
        if has_tokens:
            calculated_cost = calculate_cost(
                total_input_tokens,
                total_output_tokens,
                pricing,
                cache_read_tokens=total_cache_read_tokens,
                cache_creation_tokens=total_cache_creation_tokens
            )
            log(f"[Agent SDK] Calculated cost: ${calculated_cost:.6f} (from tokens + pricing)")
            if total_cost_usd:
                log(f"[Agent SDK] SDK reported cost: ${total_cost_usd:.4f} (for comparison)")
        elif total_cost_usd:
            # Fallback to SDK cost if no tokens available
            calculated_cost = total_cost_usd
            log(f"[Agent SDK] Using SDK cost: ${total_cost_usd:.4f} (no token data)")

        if anon_stats["total_entities"] > 0:
            log(f"[Agent SDK] Anonymization: {anon_stats['total_entities']} entities, {anon_stats['tool_calls_anonymized']} tool calls")

        # NOTE: De-anonymization is done CENTRALLY in __init__.py
        # We pass mappings through AgentResponse.anonymization
        if anon_stats["mappings"]:
            log(f"[Agent SDK] Passing {len(anon_stats['mappings'])} mappings to central de-anonymization")

        # Build anonymization info for response (used by __init__.py for de-anonymization)
        anon_info = None
        if anon_stats["total_entities"] > 0:
            anon_info = {
                "total_entities": anon_stats["total_entities"],
                "entity_types": anon_stats["entity_types"],
                "tool_calls_anonymized": anon_stats["tool_calls_anonymized"],
                "mappings": anon_stats["mappings"]  # For de-anonymization in confirmation dialogs
            }
            log(f"[Agent SDK] Mappings available: {len(anon_stats['mappings'])} entries")

        # Add warning if max iterations was reached
        if max_iterations_reached:
            iteration_warning = (
                f"\n\n---\n"
                f"⚠️ **Agent wurde nach {max_iterations} Tool-Aufrufen gestoppt**\n\n"
                f"Der Agent war noch nicht fertig, aber das Iterations-Limit wurde erreicht.\n\n"
                f"**Was du tun kannst:**\n"
                f"- Aufgabe in kleinere Teile aufteilen\n"
                f"- `max_iterations` in der Agent-Config erhöhen (z.B. auf 60 oder 80)\n"
                f"- Den Prompt präziser formulieren"
            )
            full_response += iteration_warning

        # NOTE: Chart extraction ([CHART:...] markers) is now handled CENTRALLY
        # in __init__.py after all backend calls. Do not duplicate here.

        # Check for known API errors - return as retryable failure
        if "API Error: 400" in full_response and "concurrency" in full_response.lower():
            log(f"[Agent SDK] Detected tool concurrency error - returning as retryable failure")
            return AgentResponse(
                success=False,
                content="",
                error="API 400: Tool concurrency error (transient)",
                model=model_name,
                duration_seconds=duration,
                sdk_session_id=sdk_session_id,
                can_resume=sdk_session_id is not None
            )

        # NOTE: Link placeholder replacement is handled centrally in __init__.py
        # after all backend-specific code returns. This ensures consistent
        # behavior across all backends (Claude SDK, Gemini, OpenAI, etc.)

        return AgentResponse(
            success=True,
            content=full_response,
            raw_output=full_response,
            model=model_name,
            input_tokens=total_input_tokens if total_input_tokens > 0 else None,
            output_tokens=total_output_tokens if total_output_tokens > 0 else None,
            duration_seconds=duration,
            cost_usd=calculated_cost,
            anonymization=anon_info,
            # SDK Extended Mode
            sdk_session_id=sdk_session_id,
            can_resume=sdk_session_id is not None,
            # Anonymization session for API-based de-anonymization
            anon_session_id=session_id if use_proxy else None
        )

    except CancelledException:
        duration = time.time() - start_time
        log(f"[Agent SDK] Task cancelled after {duration:.1f}s")
        # NOTE: De-anonymization done CENTRALLY in __init__.py
        # Pass mappings through anonymization field
        anon_info = {"mappings": anon_stats["mappings"]} if anon_stats["mappings"] else None
        if anon_info:
            log(f"[Agent SDK] Passing {len(anon_stats['mappings'])} mappings for cancelled output")
        return AgentResponse(
            success=False,
            content=full_response,
            error="Cancelled by user",
            model=model_name,
            duration_seconds=duration,
            cancelled=True,
            anonymization=anon_info,
            # SDK Extended Mode - session can be resumed even if cancelled
            sdk_session_id=sdk_session_id,
            can_resume=sdk_session_id is not None,
            # Anonymization session for API-based de-anonymization
            anon_session_id=session_id if use_proxy else None
        )

    except Exception as e:
        duration = time.time() - start_time
        error_str = str(e)
        log(f"[Agent SDK] Error: {error_str}")
        import traceback
        log(f"[Agent SDK] Traceback: {traceback.format_exc()}")

        # Provide user-friendly messages for known errors
        user_friendly_error = error_str
        if "400" in error_str and "concurrency" in error_str.lower():
            log("[Agent SDK] Detected API 400 concurrency error in exception - providing user-friendly message")
            user_friendly_error = (
                "⚠️ **Temporärer API-Fehler**\n\n"
                "Die Claude API hatte ein Timing-Problem bei der Tool-Verarbeitung.\n\n"
                "**Bitte nochmal versuchen** - dieser Fehler ist temporär und tritt manchmal "
                "bei komplexen Aufgaben mit vielen Tool-Aufrufen auf.\n\n"
                "💡 *Tipp: Falls der Fehler wiederholt auftritt, die Aufgabe in kleinere Schritte aufteilen.*"
            )
        elif "500" in error_str and ("Internal server error" in error_str or "api_error" in error_str):
            log("[Agent SDK] Detected API 500 server error in exception - providing user-friendly message")
            user_friendly_error = (
                "⚠️ **Server-Fehler bei Claude**\n\n"
                "Die Claude API meldet einen internen Server-Fehler (500).\n\n"
                "**Das ist ein Problem auf Anthropic's Seite** - nicht bei dir.\n\n"
                "**Bitte nochmal versuchen** - meist ist der Fehler nach wenigen Sekunden behoben.\n\n"
                "💡 *Tipp: Bei anhaltenden Problemen den [Anthropic Status](https://status.anthropic.com) prüfen.*"
            )
        elif "Control request timeout: initialize" in error_str:
            log("[Agent SDK] Detected initialize timeout - providing user-friendly message")
            user_friendly_error = (
                "⚠️ **Timeout beim Starten**\n\n"
                "Der Agent konnte nicht rechtzeitig gestartet werden. "
                "Das passiert manchmal wenn MCP-Server langsam laden.\n\n"
                "**Bitte nochmal versuchen** - beim zweiten Versuch sind die Server meist schon geladen."
            )
        elif "CLINotFoundError" in error_str or "Claude Code not found" in error_str:
            user_friendly_error = (
                "⚠️ **Claude Code nicht gefunden**\n\n"
                "Die Claude CLI ist nicht installiert oder nicht im PATH.\n\n"
                "**Lösung:** Installiere Claude Code mit `npm install -g @anthropic-ai/claude-code`"
            )

        # NOTE: De-anonymization done CENTRALLY in __init__.py
        # Pass mappings through anonymization field
        anon_info = {"mappings": anon_stats["mappings"]} if anon_stats["mappings"] else None
        if anon_info:
            log(f"[Agent SDK] Passing {len(anon_stats['mappings'])} mappings for error output")
        return AgentResponse(
            success=False,
            content=user_friendly_error,  # Show user-friendly message as content
            error=error_str,  # Keep original error for debugging
            model=model_name,
            duration_seconds=duration,
            anonymization=anon_info,
            # SDK Extended Mode - session might be resumable
            sdk_session_id=sdk_session_id,
            can_resume=sdk_session_id is not None
        )


def _is_retryable_error(result: AgentResponse) -> bool:
    """
    Check if an AgentResponse contains a transient error that should be retried.

    Retryable errors:
    - API 400 with "concurrency" (tool_use/tool_result ordering race condition)
    - API 500 / Internal server error (Anthropic-side transient failure)
    - Initialize timeout (MCP servers slow to start, usually works on retry)
    - "tool_use ids without tool_result blocks" (parallel tool call race condition)
    - Stream closed errors (connection dropped during long operations)
    """
    if result.success or result.cancelled:
        return False

    error = (result.error or "").lower()
    content = (result.content or "").lower()
    combined = f"{error} {content}"

    retryable_patterns = [
        ("400" in combined and "concurrency" in combined),
        ("tool_use" in combined and "tool_result" in combined),
        ("500" in combined and ("internal server error" in combined or "api_error" in combined)),
        ("502" in combined or "bad gateway" in combined),
        ("503" in combined or "service unavailable" in combined),
        ("overloaded" in combined),
        ("initialize" in combined and "timeout" in combined),
        ("stream closed" in combined),
        ("connection" in combined and ("reset" in combined or "refused" in combined or "timeout" in combined)),
    ]

    return any(retryable_patterns)


def call_claude_agent_sdk(
    prompt: str,
    config: dict,
    agent_config: dict,
    on_tool_request: Optional[Callable] = None,
    on_message: Optional[Callable] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    anon_context: Optional[any] = None,
    resume_session_id: Optional[str] = None
) -> AgentResponse:
    """
    Synchronous wrapper for Claude Agent SDK with automatic retry for transient errors.

    Retries up to max_retries times (default: 2, configurable via agent_config)
    with exponential backoff for transient API errors like:
    - 400 concurrency (tool_use/tool_result race condition)
    - 500 internal server errors
    - Initialize timeouts

    Args:
        prompt: The task prompt
        config: Global config
        agent_config: Agent-specific config
        on_tool_request: Callback (tool_name, input) -> bool for approval
        on_message: Callback (text, is_tool, full_response) for streaming
        is_cancelled: Callback that returns True if task should be cancelled
        anon_context: Optional anonymization context with initial mappings
        resume_session_id: Optional SDK session ID to resume (Extended Mode)

    Returns:
        AgentResponse with result
    """
    max_retries = agent_config.get("max_retries", 2)
    retry_backoff = [5, 15, 30]  # Seconds between retries

    last_result = None

    for attempt in range(1 + max_retries):
        if attempt > 0:
            # Check cancellation before retry
            if is_cancelled and is_cancelled():
                log(f"[Agent SDK] Retry cancelled by user before attempt {attempt + 1}")
                break

            wait_time = retry_backoff[min(attempt - 1, len(retry_backoff) - 1)]
            log(f"[Agent SDK] Retry {attempt}/{max_retries} after {wait_time}s backoff...")

            # Notify UI about retry
            if on_message:
                retry_msg = f"\n\u23f3 *Initialisiere Claude Agent... ({wait_time}s)*\n"
                on_message(retry_msg, False, retry_msg, {})

            # Backoff with cancellation check (1s granularity)
            for _ in range(wait_time):
                if is_cancelled and is_cancelled():
                    log(f"[Agent SDK] Retry cancelled during backoff")
                    break
                time.sleep(1)

            if is_cancelled and is_cancelled():
                break

        # Create a new event loop for each attempt to avoid stale state
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_run_agent_async(
                prompt, config, agent_config,
                on_tool_request, on_message, is_cancelled, anon_context,
                resume_session_id
            ))
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.wait(pending, timeout=2.0))
            except RuntimeError:
                pass
            except (asyncio.CancelledError, asyncio.TimeoutError, OSError):
                pass
            try:
                loop.close()
            except RuntimeError:
                pass
            _cleanup_temp_files()
            _restore_user_config()
            # Clean up session filter in Filter Proxy (Phase 4)
            _cleanup_session_filter()
            # Fix 2: Clean up orphan processes after each attempt (planfeature-027)
            # Previously only cleaned before agent start, causing orphan accumulation
            # during retries. Both functions are idempotent with built-in timeouts.
            _cleanup_orphan_mcp_processes()
            _cleanup_orphan_claude_cli_processes()

        last_result = result

        # Success or non-retryable error -> return immediately
        if result.success or not _is_retryable_error(result):
            if attempt > 0 and result.success:
                log(f"[Agent SDK] Succeeded on retry attempt {attempt + 1}")
            return result

        # Retryable error -> log and continue loop
        log(f"[Agent SDK] Attempt {attempt + 1} failed with retryable error: {(result.error or 'unknown')[:200]}")

    # All retries exhausted
    if last_result and not last_result.success:
        log(f"[Agent SDK] All {1 + max_retries} attempts failed")
        if last_result.content:
            last_result.content += (
                f"\n\n---\n"
                f"\u26a0\ufe0f **Automatische Wiederholung fehlgeschlagen** ({1 + max_retries} Versuche)\n\n"
                f"Der Fehler tritt wiederholt auf. M\u00f6gliche L\u00f6sungen:\n"
                f"- Aufgabe in kleinere Schritte aufteilen\n"
                f"- Weniger Tools gleichzeitig verwenden\n"
                f"- [Anthropic Status](https://status.anthropic.com) pr\u00fcfen"
            )

    return last_result
