# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Workflow Base Class
===================
Base class and decorators for defining workflows.
"""

from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple
from .state import save_state, complete, fail

# Centralized timestamp utilities
try:
    from utils.timestamp import get_timestamp_datetime
except ImportError:
    from datetime import datetime
    def get_timestamp_datetime(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Import system logging
try:
    from ai_agent import system_log
except ImportError:
    def system_log(msg: str):
        print(msg)

# Import session store for saving workflow responses
try:
    from assistant.session_store import add_turn
except ImportError:
    def add_turn(*args, **kwargs): return False

# Import centralized SSE broadcast
from .sse import broadcast_sse as _broadcast_sse

# Workflow log file (separate from system.log)
_workflow_log_path: Optional[Path] = None
MAX_LOG_SIZE = 100 * 1024  # 100 KB max size
KEEP_LOG_SIZE = 50 * 1024  # Keep last 50 KB when rotating


def _get_workflow_log_path() -> Path:
    """Get path for workflow log file."""
    global _workflow_log_path
    if _workflow_log_path is None:
        # paths module is always available in this context
        from paths import get_logs_dir
        logs_dir = get_logs_dir()
        _workflow_log_path = logs_dir / "workflow.txt"
    return _workflow_log_path


def _rotate_log_if_needed(log_path: Path):
    """Rotate log file if it exceeds max size - keeps last KEEP_LOG_SIZE bytes."""
    try:
        if not log_path.exists():
            return
        size = log_path.stat().st_size
        if size > MAX_LOG_SIZE:
            # Read last KEEP_LOG_SIZE bytes
            with open(log_path, "rb") as f:
                f.seek(-KEEP_LOG_SIZE, 2)  # Seek from end
                # Find next newline to avoid cutting mid-line
                f.readline()
                remaining = f.read()
            # Overwrite with truncated content
            with open(log_path, "wb") as f:
                f.write(b"[...log truncated...]\n")
                f.write(remaining)
    except Exception:
        pass  # Don't fail if rotation fails


def workflow_log(msg: str):
    """Log to workflow log file (appends, auto-rotates when too large).

    Args:
        msg: Message to log
    """
    log_line = f"[{get_timestamp_datetime()}] {msg}\n"

    log_path = _get_workflow_log_path()

    # Also log to system.log for unified view
    system_log(msg)

    # Rotate if needed
    _rotate_log_if_needed(log_path)

    # Append to workflow log
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception:
        pass  # Don't fail workflow if logging fails

# Global counter for step ordering (reset per module load)
_step_counter = 0


def step(func: Callable) -> Callable:
    """
    Decorator to mark a method as a workflow step.
    Steps are executed in the order they are defined.

    Usage:
        @step
        def my_step(self):
            # Do something
            pass

    Return values:
        None        - Continue to next step
        "skip"      - End workflow successfully (status: Skipped)
        "pause"     - Pause workflow (can be resumed later)
        "goto:name" - Jump to step with given method name
    """
    global _step_counter
    _step_counter += 1
    func._step_order = _step_counter
    func._is_workflow_step = True
    return func


class ToolProxy:
    """
    Dynamic proxy for MCP tool calls.

    Provides `self.tool.<tool_name>(...)` syntax for calling MCP tools.

    Example:
        self.tool.gmail_add_label(self.email_id, "IsDone")
        self.tool.desk_run_agent_sync("my_agent", '{"key": "value"}')
    """

    def __init__(self):
        self._bridge = None

    def _get_bridge(self):
        """Lazy-load tool bridge."""
        if self._bridge is None:
            try:
                from ai_agent.tool_bridge import ToolBridge
                self._bridge = ToolBridge()
            except ImportError:
                import sys
                from pathlib import Path
                sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
                from ai_agent.tool_bridge import ToolBridge
                self._bridge = ToolBridge()
        return self._bridge

    def __getattr__(self, name: str) -> Callable:
        """
        Dynamically handle tool calls.

        Workflows are trusted code - no MCP restrictions needed.
        """
        def call_tool(*args, **kwargs) -> Any:
            bridge = self._get_bridge()
            return bridge.execute(name, *args, **kwargs)

        return call_tool


class Workflow:
    """
    Base class for all workflows.

    Subclasses define steps using the @step decorator.
    Workflows are deterministic: same inputs → same outputs.

    For AI/creative tasks, use desk_run_agent_sync() to call agents.

    Attributes:
        name (str): Display name in WebUI
        icon (str): FontAwesome icon name (without "fa-")
        category (str): Category for WebUI grouping
        description (str): Short description (tooltip)
        hidden (bool): Hide from WebUI

    Example:
        class MyWorkflow(Workflow):
            name = "My Workflow"
            icon = "envelope"

            @step
            def check_blocklist(self):
                if self.tool.db_contains("blocked", self.sender) == "true":
                    return "skip"

            @step
            def generate_reply(self):
                self.reply = self.tool.desk_run_agent_sync(
                    "reply_agent",
                    f'{{"email": "{self.email_content}"}}'
                )
    """

    # Metadata (override in subclasses)
    name: str = "Unnamed Workflow"
    icon: str = "cog"
    category: str = "general"
    description: str = ""
    hidden: bool = False

    def __init__(self, run_id: str, **inputs):
        """
        Initialize workflow with run ID and inputs.

        Args:
            run_id: Unique identifier for this workflow run
            **inputs: Input parameters (set as instance attributes)
                      Special: _session_id is used for saving to history
        """
        self.run_id = run_id
        self.tool = ToolProxy()

        # Extract session_id for history saving (passed by manager)
        self._session_id = inputs.pop("_session_id", None)

        # Set all inputs as instance attributes
        for key, value in inputs.items():
            setattr(self, key, value)

    def log(self, message: str):
        """Log a custom message to the workflow log.

        Use this in your workflow steps for custom logging:
            self.log("Processing invoice...")
            self.log(f"Found {count} items")
        """
        workflow_log(f"[{self.name}] {message}")

    def save_response(self, content: str, tokens: int = 0, cost_usd: float = 0.0):
        """Save an assistant response to the workflow session history.

        Use this after getting AI responses (e.g., from desk_run_agent_sync)
        to persist them for display when viewing history.

        Args:
            content: The response content (AI reply)
            tokens: Optional token count
            cost_usd: Optional cost in USD
        """
        if self._session_id and content:
            add_turn(self._session_id, "assistant", content, tokens, cost_usd)

    def execute(self, from_step: int = 0) -> str:
        """
        Execute the workflow from a given step.

        Args:
            from_step: Step index to start from (for resume)

        Returns:
            Final status message
        """
        steps = self._get_steps()
        step_names = [m.__name__ for _, m in steps]

        # Log workflow start
        workflow_log(f"[Workflow] Started: {self.name} (run_id={self.run_id[:8]}...) steps={step_names}")

        i = 0
        while i < len(steps):
            order, method = steps[i]
            step_name = method.__name__

            # Skip steps before from_step (for resume)
            if order < from_step:
                i += 1
                continue

            # Save state before executing step
            save_state(self.run_id, order, self.__dict__)

            try:
                # Execute step
                workflow_log(f"[Workflow] Step: {step_name} ({i+1}/{len(steps)})")

                # Broadcast step start via SSE
                _broadcast_sse("workflow_step", {
                    "run_id": self.run_id,
                    "name": self.name,
                    "step_name": step_name,
                    "step_index": i + 1,
                    "total_steps": len(steps)
                })

                result = method()

                # Handle return values
                if result == "skip":
                    reason = getattr(self, "skip_reason", "no reason")
                    workflow_log(f"[Workflow] Skipped: {self.name} - {reason}")
                    complete(self.run_id, "Skipped")
                    return "Skipped"

                elif result == "pause":
                    workflow_log(f"[Workflow] Paused: {self.name} at step {step_name}")
                    # Status remains "running" for later resume
                    return "Paused"

                elif isinstance(result, str) and result.startswith("goto:"):
                    target_name = result[5:]
                    workflow_log(f"[Workflow] Goto: {target_name}")
                    # Find target step by method name
                    found = False
                    for j, (_, m) in enumerate(steps):
                        if m.__name__ == target_name:
                            i = j
                            found = True
                            break
                    if not found:
                        raise ValueError(f"Step not found: {target_name}")
                    continue  # Don't increment i

            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                workflow_log(f"[Workflow] Error: {self.name} at step {step_name}: {e}")
                workflow_log(f"[Workflow] Traceback:\n{tb}")
                fail(self.run_id, str(e))
                raise

            i += 1

        workflow_log(f"[Workflow] Completed: {self.name} (run_id={self.run_id[:8]}...)")
        complete(self.run_id, "Success")
        return "Success"

    def _get_steps(self) -> List[Tuple[int, Callable]]:
        """Get all @step methods sorted by definition order."""
        steps = []
        for name in dir(self):
            if name.startswith("_"):
                continue
            method = getattr(self, name)
            if callable(method) and hasattr(method, "_is_workflow_step"):
                steps.append((method._step_order, method))
        return sorted(steps, key=lambda x: x[0])
