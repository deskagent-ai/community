# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""AgentTask - Unified task execution abstraction.

Consolidates the common patterns from:
- run_tracked_task() for skills
- run_tracked_agent() for agents
- run_tracked_prompt() for prompts

Each task type shares:
- Timing and duration tracking
- Config loading and backend resolution
- Streaming callbacks and cancellation
- SSE event publishing
- Error handling patterns
- History and session management
- Cost tracking

Differences are handled via the TaskType enum and type-specific methods.
"""

import time
from dataclasses import dataclass, field

# winsound is Windows-only
try:
    import winsound
except ImportError:
    winsound = None
from enum import Enum
from typing import Optional, Dict, Any, Callable

import ai_agent
from .streaming import (
    TaskCancelledException,
    create_streaming_callback,
    create_is_cancelled_callback,
    publish_sse_completion,
)
from .files import cleanup_temp_uploads
from .state import (
    update_task,
    get_task,
    add_to_history,
    build_continuation_prompt,
    update_session,
    start_or_continue_session,
    add_turn_to_session,
    add_running_session,
    remove_running_session,
    store_session_log_content,
    get_sdk_session_id,
    clear_sdk_session_id,
)
from .sse_manager import broadcast_global_event
from ai_agent import log
from ..skills import load_config, process_skill, notify
# Note: process_agent imported lazily in _execute_agent to avoid circular import
from .. import cost_tracker
from .. import usage_tracker

# System logging
try:
    system_log = ai_agent.system_log
except AttributeError:
    system_log = lambda msg: None


class TaskType(Enum):
    """Types of AI tasks that can be executed."""
    SKILL = "skill"
    AGENT = "agent"
    PROMPT = "prompt"


@dataclass
class TaskResult:
    """Result of task execution."""
    success: bool
    content: str = ""
    error: Optional[str] = None
    cancelled: bool = False
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    anonymization: Optional[Dict] = None
    duration: float = 0.0


@dataclass
class AgentTask:
    """Unified task execution for skills, agents, and prompts.

    Example usage:
        task = AgentTask(
            task_id="123",
            task_type=TaskType.AGENT,
            name="daily_check",
            icon=tray_icon
        )
        result = task.execute()
    """

    # Required fields
    task_id: str
    task_type: TaskType
    name: str  # skill_name, agent_name, or prompt text
    icon: Any  # Tray icon for notifications

    # Optional fields
    inputs: Optional[Dict[str, Any]] = None  # For agents with pre-inputs
    backend: Optional[str] = None  # Override default AI backend
    continue_context: bool = True  # For prompts - include conversation history
    dry_run: bool = False  # Simulate destructive operations (no actual moves/deletes)
    test_folder: Optional[str] = None  # Outlook folder for test scenarios (e.g., "TestData")
    agent_name: Optional[str] = None  # Chat agent name for prompts (e.g., "chat", "chat_claude")
    triggered_by: str = "webui"  # What triggered this: "webui", "voice", "email_watcher", "workflow", "api"
    initial_prompt: Optional[str] = None  # Initial prompt/input for History display
    prefetched: Optional[Dict[str, Any]] = None  # Pre-fetched data for {{PREFETCH.key}} placeholders
    resume_session_id: Optional[str] = None  # FIX [039]: SDK session ID for resume from History
    disable_anon: bool = False  # [044] Expert Mode: Skip anonymization via context menu

    # Internal state (not set by caller)
    _config: Dict = field(default_factory=dict, repr=False)
    _ai_backend: str = field(default="", repr=False)
    _default_model: str = field(default="", repr=False)
    _start_time: float = field(default=0.0, repr=False)
    _session_id: Optional[str] = field(default=None, repr=False)

    def execute(self) -> TaskResult:
        """Execute the task and return result.

        This is the main entry point that handles the common flow:
        1. Start timing
        2. Load config and resolve backend
        3. Check if enabled
        4. Execute type-specific logic
        5. Handle completion/error/cancellation
        6. Cleanup and broadcast task_ended

        Returns:
            TaskResult with success status, content, and metrics
        """
        self._start_time = time.time()
        self._log_start()

        # Set task context in worker thread for SSE event publishing
        # (ContextVars are thread-local, so must be set in executing thread)
        ai_agent.set_current_task_id(self.task_id)

        result: TaskResult = None
        task_started_broadcast = False

        try:
            # Load config and resolve backend
            self._config = load_config()
            self._resolve_backend()

            # Check if enabled
            if not self._is_enabled():
                result = self._handle_disabled()
                return result

            # Update task with backend info
            update_task(self.task_id, ai_backend=self._ai_backend, model=self._default_model)

            # Broadcast task_started for running task badges
            # Note: Agents broadcast their own events in process_agent() to support
            # all start methods (HTTP routes, EmailWatcher, direct calls)
            if self.task_type != TaskType.AGENT:
                broadcast_global_event("task_started", {
                    "task_id": self.task_id,
                    "name": self.name,
                    "type": self.task_type.value
                })
                task_started_broadcast = True

            # Execute type-specific logic
            if self.task_type == TaskType.SKILL:
                result = self._execute_skill()
            elif self.task_type == TaskType.AGENT:
                result = self._execute_agent()
            else:  # PROMPT
                result = self._execute_prompt()

            return result

        except TaskCancelledException:
            result = self._handle_cancellation()
            return result
        except Exception as e:
            result = self._handle_error(e)
            return result
        finally:
            # Broadcast task_ended for running task badges (only if task_started was broadcast)
            # Note: Agents broadcast their own events in process_agent()
            if task_started_broadcast and self.task_type != TaskType.AGENT:
                status = "done"
                if result:
                    if result.cancelled:
                        status = "cancelled"
                    elif not result.success:
                        status = "error"
                broadcast_global_event("task_ended", {
                    "task_id": self.task_id,
                    "name": self.name,
                    "type": self.task_type.value,
                    "status": status
                })

            self._cleanup()

    def _log_start(self):
        """Log task start."""
        type_name = self.task_type.value
        system_log(f"[AgentTask] START {type_name}={self.name} task={self.task_id}")

    def _resolve_backend(self):
        """Resolve AI backend from config or override.

        Resolution priority:
        1. Global AI Override (system.json global_ai_override) - highest priority
        2. Per-Call Override (self.backend) - explicit API override
        3. Agent-Frontmatter (ai: "gemini") - existing
        4. default_ai from backends.json - existing
        5. First available backend - fallback
        """
        # Check global AI override FIRST (user explicitly set this in Preferences)
        global_override = self._config.get("global_ai_override")
        if global_override and global_override != "auto":
            self._ai_backend = global_override
            system_log(f"[Agent] Global AI override active: {global_override}")
        elif self.backend:
            self._ai_backend = self.backend
        else:
            # Get from task-specific config using discovery service (priority 3+4)
            try:
                from ..services.discovery import get_agent_config, get_skill_config
                if self.task_type == TaskType.SKILL:
                    meta = get_skill_config(self.name) or {}
                elif self.task_type == TaskType.AGENT:
                    meta = get_agent_config(self.name) or {}
                else:
                    meta = {}
                system_log(f"[AgentTask] Discovery config for {self.name}: ai={meta.get('ai')}, allowed_mcp={meta.get('allowed_mcp')}")
            except ImportError as e:
                system_log(f"[AgentTask] Discovery import failed: {e}, using legacy config")
                # Fallback to legacy config
                if self.task_type == TaskType.SKILL:
                    meta = self._config.get("skills", {}).get(self.name, {})
                elif self.task_type == TaskType.AGENT:
                    meta = self._config.get("agents", {}).get(self.name, {})
                else:
                    meta = {}

            self._ai_backend = meta.get("ai", self._config.get("default_ai", "claude"))

        # Check if resolved backend is available, fallback if not
        if not ai_agent.is_backend_available(self._ai_backend, self._config):
            fallback = ai_agent.get_default_backend(self._config)
            system_log(f"[AgentTask] Backend '{self._ai_backend}' not available, using fallback: {fallback}")
            self._ai_backend = fallback

        # Get model from backend config
        ai_config = self._config.get("ai_backends", {}).get(self._ai_backend, {})
        self._default_model = ai_config.get("model", ai_config.get("type", "unknown"))

    def _is_enabled(self) -> bool:
        """Check if task is enabled in config."""
        try:
            from ..services.discovery import get_agent_config, get_skill_config
            if self.task_type == TaskType.SKILL:
                meta = get_skill_config(self.name) or {}
            elif self.task_type == TaskType.AGENT:
                meta = get_agent_config(self.name) or {}
            else:
                return True  # Prompts are always enabled
        except ImportError:
            # Fallback to legacy config
            if self.task_type == TaskType.SKILL:
                meta = self._config.get("skills", {}).get(self.name, {})
            elif self.task_type == TaskType.AGENT:
                meta = self._config.get("agents", {}).get(self.name, {})
            else:
                return True  # Prompts are always enabled

        return meta.get("enabled", True)

    def _handle_disabled(self) -> TaskResult:
        """Handle disabled task."""
        type_name = self.task_type.value.title()
        error = f"{type_name} '{self.name}' is disabled"
        log(f"[Task {self.task_id}] {error}")
        update_task(self.task_id, status="error", error=error)
        system_log(f"[AgentTask] SKIP {self.task_type.value}={self.name} (disabled)")
        return TaskResult(success=False, error=error)

    def _handle_cancellation(self) -> TaskResult:
        """Handle task cancellation."""
        elapsed = self._get_elapsed()
        log(f"[Task {self.task_id}] {self.task_type.value.title()} cancelled by user")
        update_task(self.task_id, status="cancelled", error="Cancelled by user", duration=elapsed)

        # Clean up session if one was started
        self._cleanup_session("cancelled")

        system_log(f"[AgentTask] Calling publish_sse_completion(cancelled) for task {self.task_id}")
        publish_sse_completion(self.task_id, "cancelled", duration=elapsed)
        system_log(f"[AgentTask] CANCELLED {self.task_type.value}={self.name}")
        return TaskResult(success=False, cancelled=True, duration=elapsed)

    def _handle_error(self, error: Exception) -> TaskResult:
        """Handle task error."""
        elapsed = self._get_elapsed()
        error_msg = str(error)
        log(f"[Task {self.task_id}] Error: {error_msg}")
        update_task(self.task_id, status="error", error=error_msg, duration=elapsed)

        # Clean up session if one was started (Bug fix #5: imbalanced running sessions)
        self._cleanup_session("error")

        system_log(f"[AgentTask] Calling publish_sse_completion(error) for task {self.task_id}")
        publish_sse_completion(self.task_id, "error", error=error_msg, duration=elapsed)
        system_log(f"[AgentTask] ERROR {self.task_type.value}={self.name}: {error}")
        return TaskResult(success=False, error=error_msg, duration=elapsed)

    def _get_elapsed(self) -> float:
        """Get elapsed time since start."""
        return round(time.time() - self._start_time, 1)

    def _cleanup(self):
        """Cleanup after task execution."""
        # Clear task context from worker thread
        ai_agent.set_current_task_id(None)

        # Clean up SSE queue with delay to allow final events to be delivered
        # (Bug fix: Queue was removed before SSE clients received final events)
        try:
            from .sse_manager import schedule_queue_removal
            schedule_queue_removal(self.task_id, delay=5.0)
        except Exception:
            pass

        # Delete task from tasks dict with delay to prevent memory leak (#3)
        # AND allow sync polling clients (desk_run_agent_sync) to fetch results
        # Without delay: desk_run_agent_sync gets 404 "Task not found" because
        # task is deleted before polling can retrieve the result
        # Delay (10s) is longer than SSE queue delay (5s) to ensure proper ordering
        try:
            from .state import schedule_task_deletion
            schedule_task_deletion(self.task_id, delay=10.0)
        except Exception:
            pass

        # Only agents need temp file cleanup (for pre-inputs)
        if self.task_type == TaskType.AGENT:
            cleanup_temp_uploads()

    def _cleanup_session(self, status: str = "completed"):
        """Clean up session after task execution.

        Args:
            status: Session end status - "completed", "cancelled", or "error"
        """
        if not self._session_id:
            return

        # Remove from running sessions set
        remove_running_session(self._session_id)

        # Broadcast session_ended for History panel
        broadcast_global_event("session_ended", {
            "session_id": self._session_id,
            "name": self.name,
            "type": self.task_type.value,
            "status": status
        })

        # Sessions stay active until user explicitly closes them
        # (via closeResult/Escape/Clear History)
        # No automatic complete_session() - user controls session lifecycle
        system_log(f"[AgentTask] Session {self._session_id} kept active (user controls lifecycle)")

    def _resolve_anonymization_enabled(self) -> bool | None:
        """Resolve whether anonymization is enabled for this task.

        Uses resolve_anonymization_setting() from the anonymizer module.
        This is called BEFORE session creation to store the status in the DB.

        Returns:
            True if anonymization is active, False if not, None if unknown.
        """
        try:
            from ai_agent.anonymizer import resolve_anonymization_setting

            # Get task config (agent/skill frontmatter)
            task_config = {}
            try:
                from ..services.discovery import get_agent_config, get_skill_config
                if self.task_type == TaskType.SKILL:
                    task_config = get_skill_config(self.name) or {}
                elif self.task_type == TaskType.AGENT:
                    task_config = get_agent_config(self.name) or {}
            except ImportError:
                pass

            # Get backend config from backends.json
            agent_config = self._config.get("ai_backends", {}).get(self._ai_backend, {})

            # Determine task_type string
            task_type_str = "agent" if self.task_type == TaskType.AGENT else (
                "skill" if self.task_type == TaskType.SKILL else "agent"
            )

            anon_enabled, anon_source = resolve_anonymization_setting(
                self._config, agent_config, task_config,
                self.name, task_type_str, self._ai_backend
            )
            system_log(f"[AgentTask] Anonymization resolved: {anon_enabled} (source: {anon_source})")
            return anon_enabled
        except Exception as e:
            system_log(f"[AgentTask] Failed to resolve anonymization: {e}")
            return None

    # =========================================================================
    # Type-Specific Execution
    # =========================================================================

    def _execute_skill(self) -> TaskResult:
        """Execute skill task."""
        log(f"[Task {self.task_id}] Starting skill: {self.name}")

        success, content, anon_info = process_skill(
            self.name, "", self.icon,
            on_chunk=create_streaming_callback(self.task_id)
        )

        elapsed = self._get_elapsed()

        if success:
            log(f"[Task {self.task_id}] Completed successfully")
            updates = {"status": "done", "result": content, "duration": elapsed}
            if anon_info:
                updates["anonymization"] = anon_info
            update_task(self.task_id, **updates)
            publish_sse_completion(self.task_id, "done", result=content, duration=elapsed)

            # Add to history
            add_to_history("assistant", content, task_name=self.name, task_type="skill")
            log(f"[Task {self.task_id}] Added skill output to session history")
            system_log(f"[AgentTask] DONE skill={self.name} duration={elapsed}s")

            return TaskResult(
                success=True, content=content, duration=elapsed,
                anonymization=anon_info
            )
        else:
            log(f"[Task {self.task_id}] Failed: {content}")
            update_task(self.task_id, status="error", error=content, duration=elapsed)
            publish_sse_completion(self.task_id, "error", error=content, duration=elapsed)
            system_log(f"[AgentTask] FAILED skill={self.name}: {content[:100]}")

            return TaskResult(success=False, error=content, duration=elapsed)

    def _execute_agent(self) -> TaskResult:
        """Execute agent task."""
        # Lazy import to avoid circular dependency (agents.py imports from core)
        from ..agents import process_agent

        # Start NEW session for agent execution (clicking agent tile starts fresh)
        # Follow-up prompts will continue the session via _execute_prompt
        # Clear SDK session ID to prevent resume of previous session (#bug-fix)
        clear_sdk_session_id()

        # [043] Resolve anonymization setting before session creation
        anon_enabled = self._resolve_anonymization_enabled()

        self._session_id = start_or_continue_session(
            self.name, self._ai_backend, self._default_model,
            triggered_by=self.triggered_by,
            force_new_session=True,  # Agent tile click = new session
            anonymization_enabled=anon_enabled  # [043] Store in session
        )
        session_id = self._session_id  # Keep local reference for backward compat
        if session_id:
            system_log(f"[AgentTask] Agent session: {session_id} (triggered_by: {self.triggered_by})")

            # Broadcast session_started for History panel running indicators
            broadcast_global_event("session_started", {
                "session_id": session_id,
                "task_id": self.task_id,
                "name": self.name,
                "type": "agent",
                "triggered_by": self.triggered_by
            })

            # Redundant safety: session already marked running in start_or_continue_session()
            add_running_session(session_id, self.task_id)

            # Store initial prompt as first user turn (for History display)
            if self.initial_prompt:
                add_turn_to_session(
                    role="user",
                    content=self.initial_prompt,
                    task_id=self.task_id,
                    session_id=session_id  # Explicit session_id for parallel execution
                )

        success, content, stats = process_agent(
            self.name, self.icon,
            on_chunk=create_streaming_callback(self.task_id),
            task_id=self.task_id,
            is_cancelled=create_is_cancelled_callback(self.task_id),
            inputs=self.inputs,
            dry_run=self.dry_run,
            test_folder=self.test_folder,
            backend=self._ai_backend,  # Pass resolved backend (includes global override)
            session_id=session_id,  # For parallel execution isolation
            prefetched=self.prefetched,  # Pre-fetched data for {{PREFETCH.key}}
            disable_anon=self.disable_anon  # [044] Expert Mode: Skip anonymization
        )

        elapsed = self._get_elapsed()

        if success:
            updates = {"status": "done", "result": content, "duration": elapsed}
            result = TaskResult(success=True, content=content, duration=elapsed)

            # Extract stats
            if stats:
                if stats.get("anonymization"):
                    updates["anonymization"] = stats["anonymization"]
                    result.anonymization = stats["anonymization"]
                if stats.get("model"):
                    updates["model"] = stats["model"]
                    result.model = stats["model"]
                if stats.get("input_tokens"):
                    updates["input_tokens"] = stats["input_tokens"]
                    result.input_tokens = stats["input_tokens"]
                if stats.get("output_tokens"):
                    updates["output_tokens"] = stats["output_tokens"]
                    result.output_tokens = stats["output_tokens"]
                if stats.get("cost_usd"):
                    updates["cost_usd"] = stats["cost_usd"]
                    result.cost_usd = stats["cost_usd"]

                # SDK Extended Mode: Store session ID for resume capability
                if stats.get("sdk_session_id"):
                    from .state import set_sdk_session_id
                    set_sdk_session_id(stats["sdk_session_id"])
                    system_log(f"[AgentTask] SDK session stored for resume: {stats['sdk_session_id'][:20]}...")

                # Track costs
                cost_tracker.add_cost(
                    cost_usd=stats.get("cost_usd"),
                    input_tokens=stats.get("input_tokens"),
                    output_tokens=stats.get("output_tokens"),
                    model=stats.get("model"),
                    task_type="agent",
                    task_name=self.name,
                    backend=self._ai_backend
                )

                # Aggregate costs to parent task if this is a sub-agent
                current_task = get_task(self.task_id)
                if current_task and current_task.get("parent_task_id"):
                    parent_id = current_task["parent_task_id"]
                    parent_task = get_task(parent_id)
                    if parent_task:
                        # Aggregate sub-agent costs to parent
                        sub_cost = stats.get("cost_usd", 0) or 0
                        sub_input = stats.get("input_tokens", 0) or 0
                        sub_output = stats.get("output_tokens", 0) or 0

                        # Track sub-agent costs separately
                        existing_sub_costs = parent_task.get("sub_agent_costs", {
                            "cost_usd": 0, "input_tokens": 0, "output_tokens": 0, "count": 0
                        })
                        new_sub_costs = {
                            "cost_usd": existing_sub_costs.get("cost_usd", 0) + sub_cost,
                            "input_tokens": existing_sub_costs.get("input_tokens", 0) + sub_input,
                            "output_tokens": existing_sub_costs.get("output_tokens", 0) + sub_output,
                            "count": existing_sub_costs.get("count", 0) + 1
                        }

                        # Update parent with aggregated sub-agent costs
                        update_task(parent_id, sub_agent_costs=new_sub_costs)
                        system_log(f"[AgentTask] Aggregated sub-agent costs to parent {parent_id}: "
                                   f"+${sub_cost:.4f} +{sub_input}/{sub_output} tokens")

            update_task(self.task_id, **updates)

            # Track agent usage count
            usage_tracker.increment_agent(self.name)

            # Get sub_agent_costs from task (if this parent has sub-agents)
            current_task_final = get_task(self.task_id)
            sub_agent_costs = current_task_final.get("sub_agent_costs") if current_task_final else None

            system_log(f"[AgentTask] Calling publish_sse_completion(done) for task {self.task_id}")
            publish_sse_completion(
                self.task_id, "done", result=content, duration=elapsed,
                input_tokens=stats.get("input_tokens") if stats else None,
                output_tokens=stats.get("output_tokens") if stats else None,
                cost_usd=stats.get("cost_usd") if stats else None,
                sub_agent_costs=sub_agent_costs,
                session_id=self._session_id  # V2 Link Placeholder System
            )
            system_log(f"[AgentTask] publish_sse_completion(done) returned for task {self.task_id}")

            # Update session and history
            model_name = stats.get("model") if stats else self._default_model
            update_session(self.task_id, self.name, "agent", self._ai_backend, model_name, content)
            add_to_history("assistant", content, self.name, "agent")

            # Add assistant response to persistent session with metrics (for History panel)
            output_tokens = stats.get("output_tokens", 0) if stats else 0
            cost_usd = stats.get("cost_usd", 0) if stats else 0
            add_turn_to_session(
                "assistant", content, tokens=output_tokens, cost_usd=cost_usd,
                task_id=self.task_id, session_id=self._session_id  # Explicit session_id for parallel execution
            )

            # Store execution log in session for improve_agent (if available)
            if hasattr(result, 'log_content') and result.log_content:
                store_session_log_content(result.log_content)

            system_log(f"[AgentTask] DONE agent={self.name} duration={elapsed}s tokens={stats.get('input_tokens', 0) if stats else 0}/{output_tokens}")

            # Clean up session (remove from running, broadcast ended, mark complete)
            self._cleanup_session("completed")

            # Check for next_agent in frontmatter (auto-chaining)
            self._start_next_agent_if_configured(result)

            return result
        else:
            # Check if cancelled via callback
            if stats and stats.get("cancelled"):
                log(f"[Task {self.task_id}] Agent cancelled by user (via callback)")
                update_task(self.task_id, status="cancelled", error="Cancelled by user")
                publish_sse_completion(self.task_id, "cancelled", duration=elapsed)
                system_log(f"[AgentTask] CANCELLED agent={self.name}")
                # Clean up session (remove from running, broadcast ended, mark complete)
                self._cleanup_session("cancelled")
                return TaskResult(success=False, cancelled=True, duration=elapsed)
            else:
                updates = {"status": "error", "error": content, "duration": elapsed}
                if stats and stats.get("model"):
                    updates["model"] = stats["model"]
                update_task(self.task_id, **updates)
                publish_sse_completion(self.task_id, "error", error=content, duration=elapsed)
                system_log(f"[AgentTask] FAILED agent={self.name}: {content[:100] if content else 'unknown'}")
                # Clean up session (remove from running, broadcast ended, mark complete)
                self._cleanup_session("error")
                return TaskResult(success=False, error=content, duration=elapsed)

    def _execute_prompt(self) -> TaskResult:
        """Execute prompt task.

        Chat/Prompt is now unified with agents:
        - Uses process_agent() with prompt_override parameter
        - Agent config (knowledge, allowed_mcp) is loaded from agent_name (default: "chat")
        - Dialog support (QUESTION_NEEDED/CONFIRMATION_NEEDED) works automatically
        - Sessions are tracked in SQLite for Continue/Transfer functionality
        """
        # Lazy import to avoid circular dependency
        from ..agents import process_agent
        from .state import set_sdk_session_id

        # If agent_name is set, this is a chat agent (load its config)
        effective_agent = self.agent_name or "chat"

        log(f"\n{'='*50}")
        log(f"[Prompt] Starting... (backend={self._ai_backend}, agent={effective_agent}, continue_context={self.continue_context})")
        log(f"{'='*50}")

        # FIX [039]: If resume_session_id provided from History, set it in state
        # This ensures get_sdk_session_id() returns the correct value for the SDK call
        # FIX [051]: Also call load_session_for_continue() to reactivate session,
        # load conversation history, and restore SDK session ID from DB
        if self.resume_session_id:
            set_sdk_session_id(self.resume_session_id)
            system_log(f"[AgentTask] Set SDK session from History resume: {self.resume_session_id[:20]}...")
            from .state import load_session_for_continue
            load_session_for_continue(self.resume_session_id)
            system_log(f"[AgentTask] Session reactivated for resume: {self.resume_session_id}")

            # FIX [051]: Bug #2c - Use backend from session if not explicitly provided
            if not self.backend:
                try:
                    from .. import session_store
                    session_data = session_store.get_session(self.resume_session_id)
                    if session_data and session_data.get("backend"):
                        session_backend = session_data["backend"]
                        if session_backend != self._ai_backend:
                            system_log(f"[AgentTask] Overriding backend from session: {self._ai_backend} -> {session_backend}")
                            self._ai_backend = session_backend
                            # Re-resolve model for the session backend
                            ai_config = self._config.get("ai_backends", {}).get(session_backend, {})
                            self._default_model = ai_config.get("model", ai_config.get("type", "unknown"))
                            update_task(self.task_id, ai_backend=self._ai_backend, model=self._default_model)
                except Exception as e:
                    system_log(f"[AgentTask] Could not load backend from session: {e}")
        # If starting fresh (continue_context=False), clear SDK session ID
        # to prevent Claude SDK from resuming a previous conversation
        elif not self.continue_context:
            clear_sdk_session_id()

        # [043] Resolve anonymization setting before session creation
        anon_enabled = self._resolve_anonymization_enabled()

        # Start or continue persistent session (SQLite-backed)
        # If continue_context=False, force new session (don't continue from previous)
        self._session_id = start_or_continue_session(
            effective_agent, self._ai_backend, self._default_model,
            triggered_by=self.triggered_by,
            force_new_session=not self.continue_context,
            anonymization_enabled=anon_enabled  # [043] Store in session
        )
        session_id = self._session_id  # Keep local reference for backward compat
        if session_id:
            system_log(f"[AgentTask] Session: {session_id} (triggered_by: {self.triggered_by})")

            # [035] Broadcast session_started for History panel running indicators
            # Without this, follow-up prompts (chat continuations) don't show the
            # blue pulsing dot in the History panel.
            broadcast_global_event("session_started", {
                "session_id": session_id,
                "task_id": self.task_id,
                "name": self.agent_name or "chat",
                "type": "prompt",
                "triggered_by": self.triggered_by
            })

            # [035] Mark session as running (ensures /task/active returns it)
            add_running_session(session_id, self.task_id)

        # Build prompt with history if continuing context
        # IMPORTANT: Do NOT add user prompt to history here - it will be added AFTER
        # the assistant response to prevent race conditions when user sends multiple
        # messages quickly (which caused two user messages without assistant response between them)
        #
        # SDK Extended Mode: When resuming SDK session, skip history in prompt (SDK has it)
        if self.continue_context:
            # Check if agent uses claude_sdk backend (uses discovery to check frontmatter too)
            use_sdk_resume = False
            try:
                from ..services.discovery import get_agent_config
                agent_meta = get_agent_config(effective_agent)
                if agent_meta and agent_meta.get("ai") == "claude_sdk" and get_sdk_session_id() is not None:
                    use_sdk_resume = True
            except ImportError:
                pass  # Discovery not available, skip SDK resume check
            effective_prompt = build_continuation_prompt(self.name, use_sdk_resume=use_sdk_resume)
        else:
            effective_prompt = self.name

        # Use unified process_agent() with prompt_override
        # This provides dialog support (QUESTION_NEEDED/CONFIRMATION_NEEDED)
        success, content, stats = process_agent(
            effective_agent,
            self.icon,
            on_chunk=create_streaming_callback(self.task_id),
            task_id=self.task_id,
            is_cancelled=create_is_cancelled_callback(self.task_id),
            backend=self._ai_backend,
            prompt_override=effective_prompt,  # Key: use user prompt instead of agent file content
            session_id=session_id  # For parallel execution isolation
        )

        elapsed = self._get_elapsed()

        # Check for cancellation
        if stats and stats.get("cancelled"):
            log(f"[Task {self.task_id}] Prompt cancelled by user")
            updates = {"status": "cancelled", "error": "Cancelled by user"}
            if content:
                updates["result"] = content
                # Add both user prompt and partial response to history
                add_to_history("user", self.name, "chat", "chat")
                add_to_history("assistant", content, "chat", "chat")
            update_task(self.task_id, **updates)
            publish_sse_completion(self.task_id, "cancelled", duration=elapsed)
            system_log(f"[AgentTask] CANCELLED prompt task={self.task_id}")
            # Clean up session (remove from running, broadcast ended, mark complete)
            self._cleanup_session("cancelled")
            return TaskResult(success=False, cancelled=True, content=content or "", duration=elapsed)

        if success:
            updates = {"status": "done", "result": content, "duration": elapsed}
            result = TaskResult(success=True, content=content, duration=elapsed)

            # Extract stats
            if stats:
                if stats.get("anonymization"):
                    updates["anonymization"] = stats["anonymization"]
                    result.anonymization = stats["anonymization"]
                if stats.get("model"):
                    updates["model"] = stats["model"]
                    result.model = stats["model"]
                if stats.get("input_tokens"):
                    updates["input_tokens"] = stats["input_tokens"]
                    result.input_tokens = stats["input_tokens"]
                if stats.get("output_tokens"):
                    updates["output_tokens"] = stats["output_tokens"]
                    result.output_tokens = stats["output_tokens"]
                if stats.get("cost_usd"):
                    updates["cost_usd"] = stats["cost_usd"]
                    result.cost_usd = stats["cost_usd"]

                # SDK Extended Mode: Store session ID for resume capability
                if stats.get("sdk_session_id"):
                    from .state import set_sdk_session_id
                    set_sdk_session_id(stats["sdk_session_id"])
                    system_log(f"[AgentTask] SDK session stored for resume: {stats['sdk_session_id'][:20]}...")

                # Track costs
                cost_tracker.add_cost(
                    cost_usd=stats.get("cost_usd"),
                    input_tokens=stats.get("input_tokens"),
                    output_tokens=stats.get("output_tokens"),
                    model=stats.get("model"),
                    task_type="chat",
                    task_name=effective_agent,
                    backend=self._ai_backend
                )

            update_task(self.task_id, **updates)

            # Get sub_agent_costs (prompt tasks typically don't have sub-agents but stay consistent)
            prompt_task_final = get_task(self.task_id)
            prompt_sub_costs = prompt_task_final.get("sub_agent_costs") if prompt_task_final else None

            publish_sse_completion(
                self.task_id, "done", result=content, duration=elapsed,
                input_tokens=stats.get("input_tokens") if stats else None,
                output_tokens=stats.get("output_tokens") if stats else None,
                cost_usd=stats.get("cost_usd") if stats else None,
                sub_agent_costs=prompt_sub_costs,
                session_id=self._session_id  # V2 Link Placeholder System
            )

            # Update session and history
            # Add BOTH user prompt AND assistant response together to prevent race conditions
            model_name = stats.get("model") if stats else self._default_model
            update_session(self.task_id, "chat", "chat", self._ai_backend, model_name, content)
            add_to_history("user", self.name, "chat", "chat")  # User prompt first
            add_to_history("assistant", content, "chat", "chat")  # Then assistant response

            # Add to persistent session (SQLite)
            add_turn_to_session("user", self.name, session_id=self._session_id)  # User prompt
            output_tokens = stats.get("output_tokens", 0) if stats else 0
            cost_usd = stats.get("cost_usd", 0) if stats else 0
            add_turn_to_session(
                "assistant", content, tokens=output_tokens, cost_usd=cost_usd,
                task_id=self.task_id, session_id=self._session_id  # Explicit session_id
            )

            system_log(f"[AgentTask] DONE prompt task={self.task_id} tokens={stats.get('input_tokens', 0) if stats else 0}/{output_tokens}")

            # Clean up session (remove from running, broadcast ended, mark complete)
            self._cleanup_session("completed")

            return result
        else:
            # Error case
            error_msg = content or "Unknown error"
            updates = {"status": "error", "error": error_msg, "duration": elapsed}
            if stats and stats.get("model"):
                updates["model"] = stats["model"]
            update_task(self.task_id, **updates)
            publish_sse_completion(self.task_id, "error", error=error_msg, duration=elapsed)
            system_log(f"[AgentTask] FAILED prompt task={self.task_id}: {error_msg[:100] if error_msg else 'unknown'}")

            # Clean up session (remove from running, broadcast ended, mark complete)
            self._cleanup_session("error")

            return TaskResult(success=False, error=error_msg, duration=elapsed)

    def _start_next_agent_if_configured(self, result: TaskResult):
        """Start next agent if configured in frontmatter (auto-chaining).

        Checks agent frontmatter for:
        - next_agent: Name of next agent to run
        - pass_result_to_next: If True, passes result as "previous_result" input
        - next_agent_inputs: Additional inputs for next agent

        Example frontmatter:
            {
              "next_agent": "process_results",
              "pass_result_to_next": true,
              "next_agent_inputs": {
                "mode": "batch"
              }
            }
        """
        try:
            # Load agent config to check for next_agent
            from ..services.discovery import get_agent_config
            agent_config = get_agent_config(self.name)
            if not agent_config:
                return

            next_agent_name = agent_config.get("next_agent")
            if not next_agent_name:
                return  # No chaining configured

            system_log(f"[AgentTask] Auto-chaining: {self.name} → {next_agent_name}")

            # Build inputs for next agent
            next_inputs = agent_config.get("next_agent_inputs", {}).copy()

            # Pass result if configured
            if agent_config.get("pass_result_to_next", False):
                next_inputs["previous_result"] = result.content

            # Start next agent asynchronously (non-blocking)
            import uuid
            next_task_id = str(uuid.uuid4())

            system_log(f"[AgentTask] Starting next agent: {next_agent_name} (task_id={next_task_id})")

            # Import task registration functions
            from .state import create_task_entry
            from .sse_manager import create_queue

            # Get backend info for the next agent
            try:
                next_agent_config = get_agent_config(next_agent_name) or {}
                next_backend = next_agent_config.get("ai", self._config.get("default_ai", "claude"))
                next_ai_config = self._config.get("ai_backends", {}).get(next_backend, {})
                next_model = next_ai_config.get("model", next_ai_config.get("type", "unknown"))
            except Exception:
                next_backend = "unknown"
                next_model = "unknown"

            # CRITICAL: Register task entry BEFORE starting thread
            # Without this, is_cancelled() returns True immediately (task not in tasks dict)
            create_task_entry(next_task_id, {
                "status": "running",
                "agent": next_agent_name,
                "ai_backend": next_backend,
                "model": next_model,
                "triggered_by": "auto_chain",
                "parent_task_id": self.task_id  # Track parent for cost aggregation
            })

            # Create SSE queue for streaming (optional but enables UI updates)
            create_queue(next_task_id)

            # Create and start task in background thread
            import threading

            def run_next_agent():
                try:
                    next_task = AgentTask(
                        task_id=next_task_id,
                        task_type=TaskType.AGENT,
                        name=next_agent_name,
                        icon=self.icon,  # Reuse same icon
                        inputs=next_inputs,
                        triggered_by="auto_chain",
                        initial_prompt=f"Auto-chain: {self.name} → {next_agent_name}"
                    )
                    next_task.execute()
                except Exception as e:
                    system_log(f"[AgentTask] Auto-chain failed: {next_agent_name} - {e}")

            thread = threading.Thread(
                target=run_next_agent,
                daemon=True,
                name=f"AutoChain-{next_agent_name}"
            )
            thread.start()

            # Broadcast auto-chain event for UI
            broadcast_global_event("agent_chained", {
                "from_agent": self.name,
                "to_agent": next_agent_name,
                "task_id": next_task_id,
                "inputs": next_inputs
            })

        except ImportError as e:
            system_log(f"[AgentTask] Auto-chain import failed: {e}")
        except Exception as e:
            system_log(f"[AgentTask] Auto-chain error: {e}")


# =============================================================================
# Backward Compatible Wrapper Functions
# =============================================================================

def execute_skill(task_id: str, skill_name: str, icon: Any) -> TaskResult:
    """Execute a skill task using AgentTask.

    This is the new preferred API that returns a TaskResult.
    """
    task = AgentTask(
        task_id=task_id,
        task_type=TaskType.SKILL,
        name=skill_name,
        icon=icon
    )
    return task.execute()


def execute_agent(task_id: str, agent_name: str, icon: Any,
                  inputs: Optional[Dict[str, Any]] = None) -> TaskResult:
    """Execute an agent task using AgentTask.

    This is the new preferred API that returns a TaskResult.
    """
    task = AgentTask(
        task_id=task_id,
        task_type=TaskType.AGENT,
        name=agent_name,
        icon=icon,
        inputs=inputs
    )
    return task.execute()


def execute_prompt(task_id: str, prompt: str, icon: Any,
                   continue_context: bool = True,
                   backend: Optional[str] = None) -> TaskResult:
    """Execute a prompt task using AgentTask.

    This is the new preferred API that returns a TaskResult.
    """
    task = AgentTask(
        task_id=task_id,
        task_type=TaskType.PROMPT,
        name=prompt,
        icon=icon,
        continue_context=continue_context,
        backend=backend
    )
    return task.execute()
