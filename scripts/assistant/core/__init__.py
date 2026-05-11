# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Core modules for DeskAgent server.

Exports:
- State management (tasks, session, history)
- SSE event publishing
- Streaming callbacks and cancellation
- Task execution (skills, agents, prompts)
- AgentTask class for unified task execution
- File utilities
"""

from .state import (
    # Task state
    tasks,
    tasks_lock,
    test_tasks,
    test_tasks_lock,
    generate_task_id,
    update_task,
    get_task,
    delete_task,
    schedule_task_deletion,
    create_task_entry,
    update_test_task,

    # Session state
    current_session,
    session_lock,
    conversation_history,
    get_session_copy,
    get_history_copy,

    # Server state
    server_start_time,
    get_tray_icon,
    set_tray_icon,
    set_http_server,
    request_shutdown,
    is_shutdown_requested,

    # Session management
    add_to_history,
    build_continuation_prompt,
    clear_conversation_history,
    update_session,

    # Persistent session management (SQLite-backed)
    start_or_continue_session,
    add_turn_to_session,
    end_current_session,
    get_current_session_id,
    load_session_for_continue,

    # Running sessions tracking (for History panel status)
    add_running_session,
    remove_running_session,
    get_running_sessions,
    get_session_task_map,

    # Tray status management
    set_tray_default_title,
    update_tray_status,
    set_tray_busy,
    set_tray_idle,
    get_active_task_name,

    # Recording indicators
    set_tray_recording,
    set_recording_cursor,
)

from .sse_manager import (
    # Event types
    SSEEventType,
    SSEEvent,

    # Queue management (per-task)
    set_event_loop,
    get_event_loop,
    create_queue,
    get_queue,
    remove_queue,
    remove_queue_delayed,
    schedule_queue_removal,
    has_queue,
    get_active_queues,

    # Global broadcast (for running task badges)
    register_global_client,
    unregister_global_client,
    get_global_client_count,
    broadcast_global_event,

    # Event publishing (thread-safe)
    publish_event,
    publish_task_start,
    publish_token,
    publish_tool_call,
    publish_anonymization,
    publish_dev_context,
    publish_pending_input,
    publish_task_complete,
    publish_task_error,
    publish_task_cancelled,
)

from .streaming import (
    TaskCancelledException,
    create_streaming_callback,
    create_is_cancelled_callback,
    publish_sse_completion,
)

from .agent_task import (
    TaskType,
    TaskResult,
    AgentTask,
)

from .executor import (
    run_tracked_task,
    run_tracked_agent,
    run_tracked_prompt,
    run_tests,
    # Task orchestration (moved from state.py)
    get_ai_backend_info,
    create_and_start_task,
)

from .files import (
    cleanup_temp_uploads,
    TEMP_UPLOADS_DIR,
    SCRIPTS_DIR,
    MCP_DIR,
)
