# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Task execution functions for skills, agents, and prompts.

This module provides backward-compatible wrapper functions that delegate
to the AgentTask class for unified task execution.

The AgentTask class (in agent_task.py) consolidates:
- Status updates via thread-safe state
- Streaming callbacks for real-time output
- SSE event publishing for connected clients
- Error handling and cancellation
- History and session management
- Cost tracking

For new code, prefer using AgentTask directly:
    from .agent_task import AgentTask, TaskType
    task = AgentTask(task_id, TaskType.AGENT, name, icon)
    result = task.execute()
"""

import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

import ai_agent
from .agent_task import AgentTask, TaskType, TaskResult
from .files import SCRIPTS_DIR
from .state import update_test_task, generate_task_id, create_task_entry
from .sse_manager import create_queue
from ai_agent import log

# Path is set up by assistant/__init__.py
from paths import PROJECT_DIR

# System logging
try:
    system_log = ai_agent.system_log
except AttributeError:
    system_log = lambda msg: None


# =============================================================================
# Backward Compatible Wrapper Functions
# =============================================================================
# These functions maintain the original API while delegating to AgentTask.
# They are kept for backward compatibility with existing code.

def run_tracked_task(task_id: str, skill_name: str, icon: Any) -> None:
    """Execute skill task with tracking (thread-safe).

    This is a backward-compatible wrapper that delegates to AgentTask.

    Args:
        task_id: Unique task ID for tracking
        skill_name: Name of the skill to execute
        icon: Tray icon for notifications
    """
    task = AgentTask(
        task_id=task_id,
        task_type=TaskType.SKILL,
        name=skill_name,
        icon=icon
    )
    task.execute()


def run_tracked_agent(task_id: str, agent_name: str, icon: Any,
                      inputs: Optional[Dict[str, Any]] = None,
                      backend: Optional[str] = None,
                      dry_run: bool = False,
                      test_folder: Optional[str] = None,
                      triggered_by: str = "webui",
                      initial_prompt: Optional[str] = None,
                      prefetched: Optional[Dict[str, Any]] = None,
                      disable_anon: bool = False) -> None:
    """Execute agent task with tracking (thread-safe).

    This is a backward-compatible wrapper that delegates to AgentTask.

    Args:
        task_id: Task ID for tracking
        agent_name: Name of the agent
        icon: Tray icon for notifications
        inputs: Optional dict of user-provided input values
        backend: Override AI backend (e.g., "gemini", "openai")
        dry_run: If true, simulate destructive operations (no actual moves/deletes)
        test_folder: Optional Outlook folder for test scenarios (e.g., "TestData")
        triggered_by: What triggered this: "webui", "voice", "email_watcher", "workflow", "api"
        initial_prompt: Initial prompt/input for History display
        prefetched: Optional dict of pre-fetched data for {{PREFETCH.key}} placeholders
        disable_anon: If True, skip anonymization (Expert Mode override via context menu)
    """
    task = AgentTask(
        task_id=task_id,
        task_type=TaskType.AGENT,
        name=agent_name,
        icon=icon,
        inputs=inputs,
        backend=backend,
        dry_run=dry_run,
        test_folder=test_folder,
        triggered_by=triggered_by,
        initial_prompt=initial_prompt,
        prefetched=prefetched,
        disable_anon=disable_anon
    )
    task.execute()


def run_tracked_prompt(task_id: str, prompt: str, icon: Any,
                       continue_context: bool = True,
                       backend: Optional[str] = None,
                       agent_name: Optional[str] = None,
                       triggered_by: str = "webui",
                       resume_session_id: Optional[str] = None) -> None:
    """Execute prompt with tracking (thread-safe).

    This is a backward-compatible wrapper that delegates to AgentTask.

    Args:
        task_id: Task-ID for tracking
        prompt: The prompt text
        icon: Tray icon for notifications
        continue_context: If True, includes conversation history
        backend: Optional backend name (e.g. "gemini", "claude_sdk"). If None, uses default_ai.
        agent_name: Optional chat agent name (e.g. "chat", "chat_claude"). Used to load agent config.
        triggered_by: What triggered this: "webui", "voice", "email_watcher", "workflow", "api"
        resume_session_id: Optional SDK session ID for resume from History (FIX [039])
    """
    task = AgentTask(
        task_id=task_id,
        task_type=TaskType.PROMPT,
        name=prompt,
        icon=icon,
        continue_context=continue_context,
        backend=backend,
        agent_name=agent_name,
        triggered_by=triggered_by,
        resume_session_id=resume_session_id  # FIX [039]
    )
    task.execute()


# =============================================================================
# Test Execution
# =============================================================================

def run_tests(task_id: str, scope: str = "unit"):
    """Run pytest tests in background with streaming output (thread-safe).

    Args:
        task_id: Task ID for tracking
        scope: "unit" (no integration), "integration" (only integration), "all"
    """
    start_time = time.time()
    update_test_task(task_id, status="running", output="")
    system_log(f"[Executor] START tests task={task_id} scope={scope}")

    try:
        # Build pytest command
        cmd = [
            "python", "-m", "pytest",
            str(SCRIPTS_DIR / "tests"),
            "-v", "--tb=short",
            "--no-header"
        ]

        # Add scope filter
        if scope == "unit":
            cmd.extend(["-m", "not integration"])
        elif scope == "integration":
            cmd.extend(["-m", "integration"])
        # "all" runs everything

        log(f"[Tests] Running: {' '.join(cmd)}")

        # Run pytest with streaming output using Popen
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(PROJECT_DIR),
            bufsize=1  # Line buffered
        )

        output_lines = []
        # Stream output line by line
        for line in iter(process.stdout.readline, ''):
            if line:
                output_lines.append(line)
                update_test_task(task_id, output="".join(output_lines),
                                duration=round(time.time() - start_time, 2))

        process.stdout.close()
        return_code = process.wait(timeout=300)

        output = "".join(output_lines)

        # Parse results from output
        passed = 0
        failed = 0
        skipped = 0

        for line in output.split("\n"):
            if " passed" in line:
                try:
                    passed = int(line.split(" passed")[0].split()[-1])
                except (ValueError, IndexError):
                    pass
            if " failed" in line:
                try:
                    failed = int(line.split(" failed")[0].split()[-1])
                except (ValueError, IndexError):
                    pass
            if " skipped" in line:
                try:
                    skipped = int(line.split(" skipped")[0].split()[-1])
                except (ValueError, IndexError):
                    pass

        update_test_task(task_id,
                        output=output,
                        duration=round(time.time() - start_time, 2),
                        passed=passed,
                        failed=failed,
                        skipped=skipped,
                        status="done" if return_code == 0 else "failed",
                        exit_code=return_code)

        log(f"[Tests] Completed: {passed} passed, {failed} failed, {skipped} skipped")
        system_log(f"[Executor] DONE tests task={task_id} passed={passed} failed={failed} skipped={skipped}")

    except subprocess.TimeoutExpired:
        process.kill()
        update_test_task(task_id, status="timeout", error="Test timeout (5 min)")
        log("[Tests] Timeout after 5 minutes")
        system_log(f"[Executor] TIMEOUT tests task={task_id}")

    except Exception as e:
        update_test_task(task_id, status="error", error=str(e))
        log(f"[Tests] Error: {e}")
        system_log(f"[Executor] ERROR tests task={task_id}: {e}")


# =============================================================================
# Task Orchestration
# =============================================================================
# These functions handle task creation, threading, and response building.
# Moved from state.py as they are orchestration logic, not state management.

def get_ai_backend_info(config: dict, task_name: str = None,
                        task_type: str = "agent") -> Tuple[str, str]:
    """Get AI backend and model info for a task.

    Uses Discovery service for merged config (frontmatter has priority over legacy).
    Global AI override takes highest priority.

    Args:
        config: Loaded config dict
        task_name: Name of agent/skill (optional)
        task_type: "agent" or "skill" to determine config lookup

    Returns:
        Tuple of (ai_backend, model)
    """
    # Global AI override has highest priority
    global_override = config.get("global_ai_override")
    if global_override and global_override != "auto":
        ai_backend = global_override
    else:
        default_ai = config.get("default_ai", "claude")

        # Use Discovery service for merged config (frontmatter priority)
        if task_name:
            try:
                from ..services.discovery import get_agent_config, get_skill_config
                if task_type == "agent":
                    task_config = get_agent_config(task_name) or {}
                else:
                    task_config = get_skill_config(task_name) or {}
                ai_backend = task_config.get("ai", default_ai)
            except ImportError:
                # Fallback to legacy config if Discovery not available
                if task_type == "agent":
                    agents_config = config.get("agents", {})
                    ai_backend = agents_config.get(task_name, {}).get("ai", default_ai)
                else:
                    ai_backend = default_ai
        else:
            ai_backend = default_ai

    # Get model from backend config
    ai_config = config.get("ai_backends", {}).get(ai_backend, {})
    model = ai_config.get("model", ai_config.get("type", "unknown"))

    return ai_backend, model


def create_and_start_task(
    task_type: str,
    task_name: str,
    runner_func,
    runner_args: tuple = (),
    ai_backend: str = None,
    model: str = None,
    user_prompt: str = "",
    triggered_by: str = "webui",
    initial_prompt: str = None,
    **extra_task_data
) -> Tuple[str, dict]:
    """Create a task entry, start the runner thread, and return task info.

    Consolidates the common task creation pattern used across agent, skill,
    and prompt endpoints.

    Args:
        task_type: Type of task ("agent", "skill", "prompt", "chat")
        task_name: Name for logging (agent/skill name or "prompt")
        runner_func: Function to run in thread (run_tracked_agent, etc.)
        runner_args: Additional args for runner_func (after task_id)
        ai_backend: AI backend name (optional)
        model: Model name (optional)
        user_prompt: The prompt/content for display (optional)
        triggered_by: What triggered this: "webui", "voice", "email_watcher", "workflow", "api"
        initial_prompt: Initial prompt/input for History display (optional)
        **extra_task_data: Additional fields for task entry

    Returns:
        Tuple of (task_id, response_data) where response_data contains
        status, task_id, and any relevant task info for JSON response.
    """
    task_id = generate_task_id()

    # Build task entry
    task_entry = {"status": "running", "user_prompt": user_prompt, "triggered_by": triggered_by}
    if ai_backend:
        task_entry["ai_backend"] = ai_backend
    if model:
        task_entry["model"] = model
    if task_type in ("agent", "skill"):
        task_entry[task_type] = task_name
    elif task_type in ("chat", "prompt"):
        # Chat/prompt: store the agent name so config lookup works
        task_entry["type"] = task_type
        task_entry["agent"] = task_name  # e.g., "chat" or "chat_claude"
    else:
        task_entry["type"] = task_type
    task_entry.update(extra_task_data)

    # Create task entry (thread-safe)
    create_task_entry(task_id, task_entry)

    # Log task start
    backend_info = f" ({ai_backend})" if ai_backend else ""
    log(f"\n[HTTP] {task_type.title()} Task {task_id}: {task_name}{backend_info}")

    # Create SSE queue BEFORE starting thread to avoid race condition
    # The streaming callback checks has_queue() - queue must exist first
    create_queue(task_id)

    # Start runner thread
    threading.Thread(
        target=runner_func,
        args=(task_id,) + runner_args
    ).start()

    # Build response data
    response = {"status": "started", "task_id": task_id}
    if task_type == "agent":
        response["agent"] = task_name
    elif task_type == "skill":
        response["skill"] = task_name
    if ai_backend:
        response["ai_backend"] = ai_backend
    if model:
        response["model"] = model
    if user_prompt:
        response["user_prompt"] = user_prompt

    return task_id, response
