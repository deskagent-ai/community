# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
AI Agent - Central module for AI calls
======================================
Supports multiple AI backends:
- claude_cli: Claude Code CLI with MCP
- claude_api: Direct Anthropic API with streaming + tools
- claude_agent_sdk: Official Claude Agent SDK with user approval workflow
- qwen_agent: Qwen-Agent framework with MCP (local via Ollama)
- ollama_native: Direct Ollama API with streaming + tools
- gemini_adk: Google Gemini API with streaming + tools
- openai_api: OpenAI GPT API with streaming + tools
"""

# === PATH SETUP ===
# Ensure scripts directory is on sys.path for 'paths' module import
# This is done once here, at package import time, so submodules don't need
# the try/except pattern for importing from paths.
import sys
from pathlib import Path
_scripts_dir = str(Path(__file__).parent.parent.resolve())
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
# === END PATH SETUP ===

import json
import os

# Logging functions - from dedicated logging module (no circular imports)
from .logging import (
    log,
    set_logger,
    set_console_logging,
    start_log_buffer,
    stop_log_buffer,
    init_system_log,
    system_log,
    anon_message_log,
    log_tool_call
)
from .base import (
    AgentResponse,
    AgentMetrics,
    write_agent_log,
    write_prompt_log,
    log_task_summary,
    set_current_task_id,
    get_current_task_id,
    publish_tool_event,
    publish_context_event,
    clear_all_caches
)
from .backend_config import (
    get_agent_config,
    is_backend_available,
    get_default_backend,
)
from .dev_context import (
    get_dev_context,
    reset_dev_context,
    capture_dev_context,
    set_dev_anonymization,
    add_dev_tool_result,
    update_dev_iteration,
    clear_dev_context
)
from .token_utils import (
    estimate_tokens,
    format_tokens,
    get_context_limit,
    calculate_cost
)
from .response_parser import extract_json, clean_tool_markers
from .knowledge_loader import (
    load_knowledge,
    load_knowledge_cached,
    invalidate_knowledge_cache,
    get_last_knowledge_stats
)
from .template_loader import (
    load_templates,
    get_last_template_stats,
    set_template_stats_skipped
)
from .task_context import (
    TaskContext,
    get_task_context,
    get_task_context_or_none,
    set_task_context,
    clear_task_context,
    create_task_context
)
from .claude_cli import call_claude_cli
from .claude_api import call_claude_api
from .claude_agent_sdk import call_claude_agent_sdk
from .qwen_agent import call_qwen_agent
from .ollama_native import call_ollama_native
from .gemini_adk import call_gemini_adk
from .openai_api import call_openai_api
from . import anonymizer

# Discovery service - imported lazily to avoid circular import issues
_discovery_module = None

def _get_discovery_module():
    """Lazy load discovery module to avoid circular import at module level."""
    global _discovery_module
    if _discovery_module is None:
        try:
            from assistant.services import discovery
            _discovery_module = discovery
        except ImportError:
            _discovery_module = False  # Mark as unavailable
    return _discovery_module if _discovery_module else None


def call_agent(
    prompt: str,
    config: dict,
    use_tools: bool = False,
    agent_name: str = None,
    continue_conversation: bool = False,
    on_chunk: callable = None,
    task_name: str = None,
    task_type: str = None,
    is_cancelled: callable = None,
    dry_run: bool = False,
    test_folder: str = None,
    task_id: str = None,
    session_id: str = None,
    disable_anon: bool = False,
    task_context: 'TaskContext' = None
) -> AgentResponse:
    """
    Calls the configured AI agent with optional PII anonymization.

    Args:
        prompt: The prompt for the agent
        config: Configuration from config.json
        use_tools: If True, enable MCP tool access
        agent_name: Optional - name of AI backend (e.g. "claude", "qwen")
        continue_conversation: If True, continue last conversation (Claude CLI only)
        on_chunk: Optional callback for streaming
                  Signature: on_chunk(token, is_thinking, full_response, anon_mappings=None)
                  anon_mappings: dict {placeholder: original} for real-time de-anonymization
        is_cancelled: Optional callback that returns True if task should be cancelled
        task_name: Optional - name of skill or agent (for anonymization)
        task_type: Optional - "skill" or "agent" (for anonymization)
        dry_run: If True, simulate destructive operations (no actual moves/deletes)
        test_folder: Optional Outlook folder for test scenarios (e.g., "TestData")
        task_id: Optional unique identifier for this task (for per-task isolation)
        session_id: Optional SQLite session ID for parallel execution isolation
        disable_anon: If True, skip anonymization (Expert Mode override via context menu)
        task_context: Optional TaskContext from caller (e.g., process_agent).
                     When provided, reuses the existing context and does NOT clear it
                     at the end (caller is responsible for cleanup).
                     When None (default), creates and clears its own context.

    Returns:
        AgentResponse with result or error
    """
    import uuid

    # === TASK CONTEXT INITIALIZATION ===
    # [069] owns_context pattern: If caller provides task_context, we reuse it
    # and do NOT clear it at the end. Otherwise we create and manage our own.
    owns_context = task_context is None

    # Generate task_id if not provided
    if not task_id:
        if task_context and task_context.task_id:
            task_id = task_context.task_id
        else:
            # Generate a task_id from task_name + short UUID
            name_part = (task_name or agent_name or "task")[:20]
            task_id = f"{name_part}-{str(uuid.uuid4())[:4]}"

    # Resolve backend with automatic fallback
    if agent_name:
        backend_name = agent_name
    else:
        backend_name = get_default_backend(config)

    if owns_context:
        # Create TaskContext with all per-task state
        # This replaces the old global variables in tool_bridge
        ctx = create_task_context(
            task_id=task_id,
            backend_name=backend_name,
            dry_run_mode=dry_run,
            test_folder=test_folder,
            session_id=session_id
        )
        log(f"[AI Agent] TaskContext created: task_id={task_id}, backend={backend_name}, session={session_id}")
    else:
        # Reuse caller's TaskContext
        ctx = task_context
        set_task_context(ctx)
        log(f"[AI Agent] TaskContext reused from caller: task_id={ctx.task_id}, backend={backend_name}")

    # [069] Resolve existing_anon_context from TaskContext
    # In multi-round scenarios, the TaskContext preserves anon_context across rounds
    existing_anon_context = ctx.anon_context

    # Set ANON_SESSION_ID environment variable for in-process MCP calls (Gemini, Ollama)
    # Claude SDK sets this in subprocesses, but tool_bridge needs it in the main process
    if session_id:
        os.environ["ANON_SESSION_ID"] = session_id
        log(f"[AI Agent] Set ANON_SESSION_ID={session_id[:20]}... for in-process MCPs")

    # Set console logging from config
    set_console_logging(config.get("console_logging", True))

    # Start log buffer if agent logging is enabled
    log_config = config.get("agent_logging", {})
    if log_config.get("enabled", False):
        start_log_buffer()

    # Reset dev context for new task (centralized - backends don't need to do this)
    reset_dev_context()

    # Dry-run and test_folder are now set via TaskContext above
    # The tool_bridge reads from TaskContext automatically
    if dry_run:
        log(f"[AI Agent] DRY-RUN MODE enabled - destructive operations will be simulated")
    if test_folder:
        log(f"[AI Agent] Test folder: {test_folder}")

    agent_config = get_agent_config(config, agent_name)
    agent_type = agent_config.get("type", "claude_cli")
    backend_name = agent_name or config.get("default_ai", "claude")

    # Merge task-specific config overrides into backend config
    # This allows agents/skills to override backend settings like use_anonymization_proxy
    if task_name and task_type:
        # Use discovery service for merged config (frontmatter + agents.json)
        discovery = _get_discovery_module()
        if discovery:
            if task_type == "agent":
                task_config = discovery.get_agent_config(task_name)
            else:
                task_config = discovery.get_skill_config(task_name)
        else:
            # Fallback to legacy config (discovery module not available)
            tasks_config = config.get(f"{task_type}s", {})  # "skills" or "agents"
            task_config = tasks_config.get(task_name, {})

        # DEBUG: Log what discovery returned
        log(f"[AI Agent] Discovery task_config for {task_name}: ai={task_config.get('ai')}, allowed_mcp={task_config.get('allowed_mcp')}, use_anonymization_proxy={task_config.get('use_anonymization_proxy')}")

        # Allow task to override specific backend settings
        override_keys = ["anonymize", "use_anonymization_proxy", "knowledge", "permission_mode", "allowed_mcp", "allowed_tools", "blocked_tools", "filesystem", "skip_dialogs", "tool_mode"]
        for key in override_keys:
            if key in task_config:
                agent_config = dict(agent_config)  # Make a copy to avoid modifying original
                agent_config[key] = task_config[key]
                log(f"[AI Agent] Task override: {key}={task_config[key]}")

    # === CENTRAL ANONYMIZATION DECISION ===
    # Determine ONCE if anonymization should be used.
    # This replaces scattered checks in individual backends.
    # Priority: Expert-Override > Agent-OFF > Agent-ON (if global ON) > Global-OFF > Backend-Default
    if task_name and task_type:
        # [044] Expert override: disable_anon from context menu (passed as parameter)
        final_anon, anon_source = anonymizer.resolve_anonymization_setting(
            config, agent_config, task_config, task_name, task_type, backend_name,
            disable_anon=disable_anon
        )

        # Update agent_config with final decision
        agent_config = dict(agent_config) if not isinstance(agent_config, dict) else agent_config
        agent_config["anonymize"] = final_anon
        agent_config["use_anonymization_proxy"] = final_anon

        log(f"[AI Agent] Anonymization: {final_anon} (source: {anon_source}, "
            f"global={config.get('anonymization', {}).get('enabled')}, "
            f"backend={agent_config.get('anonymize')}, "
            f"agent={task_config.get('anonymize')})")

    # Centralized: allowed_mcp: null means disable all tools
    if "allowed_mcp" in agent_config and agent_config["allowed_mcp"] is None:
        use_tools = False
        log(f"[AI Agent] Tools disabled (allowed_mcp: null)")

    # === FILESYSTEM RESTRICTIONS ===
    # Apply per-agent filesystem write restrictions to TaskContext
    filesystem_config = agent_config.get("filesystem", {})
    write_paths = filesystem_config.get("write", [])
    if write_paths:
        # Resolve placeholders in write paths (e.g., {{EXPORTS_DIR}})
        from .base import _resolve_path_placeholders
        resolved_paths = [_resolve_path_placeholders(p) for p in write_paths]
        ctx.filesystem_write_paths = resolved_paths
        log(f"[AI Agent] Filesystem write paths restricted to: {resolved_paths}")

    # === MCP FILTER ===
    # Set MCP filter in TaskContext for execute_tool() to use
    # This prevents hallucinated tools from being loaded from unfiltered MCPs
    # Bug fix: Without this, execute_tool() would call _discover_mcp_tools(None)
    # when a tool isn't in cache, loading ALL MCPs instead of filtered ones
    if use_tools:
        mcp_filter = agent_config.get("allowed_mcp")
        if mcp_filter:
            from . import tool_bridge
            tool_bridge.set_mcp_filter(mcp_filter)
            log(f"[AI Agent] MCP filter set in TaskContext: {mcp_filter}")

    # === ANONYMIZATION: Before AI call ===
    # IMPORTANT: Only anonymize the INPUT section, NOT the system prompt!
    # The system prompt contains agent instructions (folder names, workflow terms)
    # that should never be anonymized.
    # NOTE: The central decision was already made above via resolve_anonymization_setting()
    # and stored in agent_config["use_anonymization_proxy"].
    anon_context = None
    if agent_config.get("use_anonymization_proxy", False):
        log(f"[AI Agent] Anonymizing PII for {task_type}: {task_name}")

        # Find the input section to anonymize only that part
        input_marker = "### Input:"
        output_marker = "### Output:"

        if input_marker in prompt:
            # Split prompt into system prompt + input + rest
            input_start = prompt.find(input_marker)
            input_end = prompt.find(output_marker) if output_marker in prompt else len(prompt)

            system_prompt = prompt[:input_start]
            input_section = prompt[input_start:input_end]
            rest_section = prompt[input_end:] if input_end < len(prompt) else ""

            # Only anonymize the input section (contains user data/emails)
            # [068] Pass existing_anon_context for continuation rounds to prevent
            # data corruption (same PII values get same placeholders)
            anonymized_input, anon_context = anonymizer.anonymize(
                input_section, config, existing_context=existing_anon_context
            )
            prompt = system_prompt + anonymized_input + rest_section

            if existing_anon_context:
                log(f"[AI Agent] Anonymized INPUT with REUSED context ({len(anon_context.mappings)} mappings)")
            else:
                log(f"[AI Agent] Anonymized INPUT section only (system prompt preserved)")
        else:
            # No ### Input: marker = pure agent prompt, DO NOT anonymize
            # Agent prompts contain system instructions (folder names, workflow terms)
            # that should never be anonymized. Continuation prompts now include
            # ### Input: marker to ensure user data is still anonymized.
            log(f"[AI Agent] Skipping anonymization - agent prompt only (no ### Input: marker)")
            anon_context = existing_anon_context or anonymizer.AnonymizationContext()

        # Log anonymized input - VERY VISIBLE (only if something was anonymized)
        pii_count = len(anon_context.mappings) if anon_context else 0

        if pii_count > 0:
            log("")
            log("=" * 70)
            log(f">>>  ANONYMIZED INPUT SENT TO AI  ({pii_count} PII replaced)  <<<")
            log("=" * 70)

            # Show the input section
            if input_marker in prompt:
                input_start = prompt.find(input_marker)
                input_end = prompt.find(output_marker) if output_marker in prompt else len(prompt)
                anonymized_input_display = prompt[input_start:input_end].strip()
                log(anonymized_input_display)
            else:
                # No ### Input: marker - show first 500 chars of anonymized prompt
                preview = prompt[:500] + "..." if len(prompt) > 500 else prompt
                log(preview)

            log("=" * 70)
            log("")

            # Log to anon_messages.log for easy verification
            anon_message_log("PROMPT", prompt, task_name or "unknown", pii_count, backend_name)

            # Capture anonymization for dev context display
            set_dev_anonymization(anon_context.mappings if anon_context else {})

    log(f"[AI Agent] Type: {agent_type}" +
        (f" ({agent_name})" if agent_name else "") +
        (" (continue)" if continue_conversation else ""))

    # Call the appropriate backend
    match agent_type:
        case "claude_cli":
            result = call_claude_cli(
                prompt, config, agent_config,
                use_tools=use_tools,
                continue_conversation=continue_conversation
            )

        case "qwen_agent":
            result = call_qwen_agent(
                prompt, config, agent_config,
                use_tools=use_tools
            )

        case "ollama_native":
            result = call_ollama_native(
                prompt, config, agent_config,
                use_tools=use_tools,
                on_chunk=on_chunk,
                is_cancelled=is_cancelled
            )

        case "claude_api":
            # For claude_api with tools, pass context for tool result anonymization
            # IMPORTANT: Reuse existing anon_context to keep prompt mappings for de-anonymization
            api_anon_context = None
            if use_tools and agent_config.get("use_anonymization_proxy", False):
                # Reuse existing context (has prompt mappings) or create new one
                if anon_context is not None:
                    api_anon_context = anon_context
                    log(f"[AI Agent] Reusing prompt anonymization context ({len(anon_context.mappings)} mappings)")
                else:
                    api_anon_context = anonymizer.AnonymizationContext()
                log(f"[AI Agent] Tool result anonymization enabled for {task_type}: {task_name}")

            result = call_claude_api(
                prompt, config, agent_config,
                use_tools=use_tools,
                on_chunk=on_chunk,
                anon_context=api_anon_context
            )

            # Merge tool anonymization context (only if different objects)
            if api_anon_context and api_anon_context.mappings:
                if anon_context is None:
                    anon_context = api_anon_context
                elif anon_context is not api_anon_context:
                    # Merge only if they're different objects
                    anon_context.mappings.update(api_anon_context.mappings)
                    anon_context.reverse_mappings.update(api_anon_context.reverse_mappings)
                    for k, v in api_anon_context.counters.items():
                        anon_context.counters[k] = max(anon_context.counters.get(k, 0), v)

        case "claude_api_confirmed":
            # Claude API with user confirmation for tools - combines anonymization + approval
            # IMPORTANT: Reuse existing anon_context to keep prompt mappings for de-anonymization
            api_anon_context = None
            if use_tools and agent_config.get("use_anonymization_proxy", False):
                # Reuse existing context (has prompt mappings) or create new one
                if anon_context is not None:
                    api_anon_context = anon_context
                    log(f"[AI Agent] Reusing prompt anonymization context ({len(anon_context.mappings)} mappings)")
                else:
                    api_anon_context = anonymizer.AnonymizationContext()
                log(f"[AI Agent] Tool result anonymization enabled for {task_type}: {task_name}")

            # Simple auto-approve callback (can be enhanced for interactive confirmation)
            def tool_confirm(tool_name: str, tool_input: dict) -> bool:
                """Auto-approve all tools but log them clearly."""
                log(f"[AI Agent] ✓ Tool approved: {tool_name}")
                return True

            result = call_claude_api(
                prompt, config, agent_config,
                use_tools=use_tools,
                on_chunk=on_chunk,
                anon_context=api_anon_context,
                tool_confirm_callback=tool_confirm
            )

            # Merge tool anonymization context (only if different objects)
            if api_anon_context and api_anon_context.mappings:
                if anon_context is None:
                    anon_context = api_anon_context
                elif anon_context is not api_anon_context:
                    # Merge only if they're different objects
                    anon_context.mappings.update(api_anon_context.mappings)
                    anon_context.reverse_mappings.update(api_anon_context.reverse_mappings)
                    for k, v in api_anon_context.counters.items():
                        anon_context.counters[k] = max(anon_context.counters.get(k, 0), v)

        case "claude_agent_sdk":
            # Claude Agent SDK - multi-step workflows with user approval
            # SDK uses anonymization proxy which handles de-anonymization of tool inputs
            # Tool results are anonymized by proxy before being sent back to AI
            if anon_context and anon_context.mappings:
                log(f"[AI Agent] Passing {len(anon_context.mappings)} prompt mappings to SDK proxy")

            # SDK Extended Mode: Get session ID for resume (if continuing chat)
            from assistant.core.state import get_sdk_session_id, set_sdk_session_id
            resume_session_id = get_sdk_session_id()
            if resume_session_id:
                log(f"[AI Agent] Will resume SDK session: {resume_session_id[:20]}...")

            result = call_claude_agent_sdk(
                prompt, config, agent_config,
                on_message=on_chunk,  # Use on_chunk for streaming
                is_cancelled=is_cancelled,  # For cancellation support
                anon_context=anon_context,  # Pass mappings for tool input de-anonymization
                resume_session_id=resume_session_id  # SDK Extended Mode resume
            )

            # SDK Extended Mode: Store session ID for next call in this chat
            if result.sdk_session_id:
                set_sdk_session_id(result.sdk_session_id)
                log(f"[AI Agent] Stored SDK session for resume: {result.sdk_session_id[:20]}...")

            # SDK may provide cost directly via total_cost_usd
            if result.success and result.cost_usd:
                log(f"[AI Agent] SDK reported cost: ${result.cost_usd:.4f}")
            elif result.success and result.input_tokens is None:
                log("[AI Agent] Note: SDK did not report token usage (cost unavailable)")

        case "gemini_adk":
            # Google Gemini API with streaming and tool support
            # IMPORTANT: Reuse existing anon_context to keep prompt mappings for de-anonymization
            gemini_anon_context = None
            if use_tools and agent_config.get("use_anonymization_proxy", False):
                # Reuse existing context (has prompt mappings) or create new one
                if anon_context is not None:
                    gemini_anon_context = anon_context
                    log(f"[AI Agent] Reusing prompt anonymization context ({len(anon_context.mappings)} mappings)")
                else:
                    gemini_anon_context = anonymizer.AnonymizationContext()
                log(f"[AI Agent] Tool result anonymization enabled for {task_type}: {task_name}")

            result = call_gemini_adk(
                prompt, config, agent_config,
                use_tools=use_tools,
                on_chunk=on_chunk,
                anon_context=gemini_anon_context,
                is_cancelled=is_cancelled
            )

            # Merge tool anonymization context (only if different objects)
            if gemini_anon_context and gemini_anon_context.mappings:
                if anon_context is None:
                    anon_context = gemini_anon_context
                elif anon_context is not gemini_anon_context:
                    # Merge only if they're different objects
                    anon_context.mappings.update(gemini_anon_context.mappings)
                    anon_context.reverse_mappings.update(gemini_anon_context.reverse_mappings)
                    for k, v in gemini_anon_context.counters.items():
                        anon_context.counters[k] = max(anon_context.counters.get(k, 0), v)

        case "openai_api":
            # OpenAI API with streaming and tool support
            # IMPORTANT: Reuse existing anon_context to keep prompt mappings for de-anonymization
            openai_anon_context = None
            if use_tools and agent_config.get("use_anonymization_proxy", False):
                # Reuse existing context (has prompt mappings) or create new one
                if anon_context is not None:
                    openai_anon_context = anon_context
                    log(f"[AI Agent] Reusing prompt anonymization context ({len(anon_context.mappings)} mappings)")
                else:
                    openai_anon_context = anonymizer.AnonymizationContext()
                log(f"[AI Agent] Tool result anonymization enabled for {task_type}: {task_name}")

            result = call_openai_api(
                prompt, config, agent_config,
                use_tools=use_tools,
                on_chunk=on_chunk,
                anon_context=openai_anon_context,
                is_cancelled=is_cancelled
            )

            # Merge tool anonymization context (only if different objects)
            if openai_anon_context and openai_anon_context.mappings:
                if anon_context is None:
                    anon_context = openai_anon_context
                elif anon_context is not openai_anon_context:
                    # Merge only if they're different objects
                    anon_context.mappings.update(openai_anon_context.mappings)
                    anon_context.reverse_mappings.update(openai_anon_context.reverse_mappings)
                    for k, v in openai_anon_context.counters.items():
                        anon_context.counters[k] = max(anon_context.counters.get(k, 0), v)

        case _:
            result = AgentResponse(
                success=False,
                content="",
                error=f"Unknown agent type: {agent_type}"
            )

    # === CHART EXTRACTION: Central handling for all backends ===
    # Extract [CHART:...] markers from tool results and include in response
    # This handles two cases:
    # 1. AI outputs [CHART] placeholder → replace with actual chart data
    # 2. AI doesn't include charts in response → append chart data at end
    if result.content:
        import re
        dev_context = get_dev_context()
        chart_markers = []
        for tr in dev_context.get("tool_results", []):
            tool_result = tr.get("result", "")

            # Handle JSON wrapper from proxy MCP: {"result":"[CHART:..."}
            # The actual chart JSON is escaped inside the wrapper, so parse it first
            if tool_result.startswith('{"result":'):
                try:
                    parsed = json.loads(tool_result)
                    tool_result = parsed.get("result", tool_result)
                except (json.JSONDecodeError, TypeError):
                    pass  # Keep original if parsing fails

            if "[CHART:" in tool_result:
                # Extract all chart markers from this tool result
                # Pattern uses [/CHART] end marker for reliable extraction (nested JSON)
                chart_pattern = r'\[CHART:(.*?)\[/CHART\]\]'
                matches = re.findall(chart_pattern, tool_result, re.DOTALL)
                # Reconstruct the marker format expected by WebUI
                chart_markers.extend([f"[CHART:{m}]" for m in matches])

        if chart_markers:
            log(f"[AI Agent] Found {len(chart_markers)} chart(s) in tool results")
            charts_modified = False
            if "[CHART]" in result.content:
                # Case 1: Replace placeholders with actual chart data
                for marker in chart_markers:
                    result.content = result.content.replace("[CHART]", marker, 1)
                log(f"[AI Agent] Replaced [CHART] placeholders with chart data")
                charts_modified = True
            elif "[CHART:" not in result.content:
                # Case 2: Append charts at the end (for backends that don't output placeholders)
                # But only if no chart marker is already in the response
                result.content = result.content.rstrip() + "\n\n" + "\n\n".join(chart_markers)
                log(f"[AI Agent] Appended chart(s) to response")
                charts_modified = True
            else:
                # Case 3: Response already contains [CHART:...] marker (e.g. Gemini)
                log(f"[AI Agent] Chart already in response, skipping append")

            # Send final content_sync so frontend gets the charts
            if charts_modified and task_id:
                try:
                    from assistant.core.sse_manager import publish_content_sync, has_queue
                    if has_queue(task_id):
                        publish_content_sync(task_id, result.content, is_thinking=False)
                        log(f"[AI Agent] Sent content_sync with charts to frontend")
                except Exception as e:
                    log(f"[AI Agent] Failed to send chart content_sync: {e}")

    # === DE-ANONYMIZATION: After AI call ===
    # ALWAYS de-anonymize if we have content (success, error, or cancelled)
    # This is the CENTRAL point for de-anonymization - backends should NOT de-anonymize
    #
    # Mappings can come from two sources:
    # 1. anon_context: Prompt anonymization (done in this function)
    # 2. result.anonymization: Backend's internal anonymization (e.g., SDK's proxy)

    if result.content:
        original_content = result.content
        all_mappings = {}

        # Source 1: Prompt anonymization context
        if anon_context and anon_context.mappings:
            all_mappings.update(anon_context.mappings)
            log(f"[AI Agent] De-anon source 1: {len(anon_context.mappings)} prompt mappings")

        # Source 2: Backend's anonymization (e.g., claude_agent_sdk proxy)
        # Support both formats: nested {"mappings": {...}} and flat {"<X>": "Y"}
        if result.anonymization and isinstance(result.anonymization, dict):
            backend_mappings = result.anonymization.get("mappings")
            if backend_mappings is None:
                # Fallback: flat format - check if keys look like placeholders
                if any(k.startswith("<") for k in result.anonymization.keys()):
                    backend_mappings = result.anonymization
            if backend_mappings:
                all_mappings.update(backend_mappings)
                log(f"[AI Agent] De-anon source 2: {len(backend_mappings)} backend mappings")

        # Source 3: API-based de-anonymization (for MCP API solution)
        # If we have an anon_session_id, call the API to de-anonymize
        if hasattr(result, 'anon_session_id') and result.anon_session_id:
            try:
                import requests
                api_url = "http://localhost:8765/api/mcp/deanonymize"
                resp = requests.post(api_url, json={
                    "session_id": result.anon_session_id,
                    "text": result.content
                }, timeout=30)
                if resp.ok:
                    deanon_result = resp.json()
                    deanon_text = deanon_result.get("text", result.content)
                    if deanon_text != result.content:
                        result.content = deanon_text
                        log(f"[AI Agent] De-anon source 3: API-based (session {result.anon_session_id})")
                else:
                    log(f"[AI Agent] De-anon API call failed: {resp.status_code}")
            except Exception as e:
                log(f"[AI Agent] De-anon API call error: {e}")

        # Log anonymized response BEFORE de-anonymization (for verification)
        # Show all mappings at end of log
        if anon_context:
            anon_message_log("RESPONSE", result.content, task_name or "unknown", mappings=all_mappings)

        # Apply all mappings
        if all_mappings:
            for placeholder, original in all_mappings.items():
                result.content = result.content.replace(placeholder, original)

            if result.content != original_content:
                log(f"[AI Agent] Response de-anonymized ({len(all_mappings)} total mappings)")

            # Store all mappings in result for transparency
            result.anonymization = all_mappings

    # === LINK PLACEHOLDER REPLACEMENT ===
    # Replace {{LINK:ref}} placeholders with actual URLs
    # V2: Get link_map from registry API (MCPs call register_link instead of returning web_link)
    if result.content:
        link_map = {}

        # V2: Get link_map from registry API using session_id
        if session_id:
            try:
                from assistant.routes.mcp_api import get_link_map_for_session
                link_map = get_link_map_for_session(session_id)
                if link_map:
                    log(f"[AI Agent] Link map from registry: {len(link_map)} entries")
            except ImportError:
                pass
            except Exception as e:
                log(f"[AI Agent] Failed to get link_map from registry: {e}")

        if link_map:
            # Replace {{LINK:ref}} placeholders with actual URLs (V2 server-side resolution)
            import re
            original_content = result.content
            lowercase_map = {k.lower(): v for k, v in link_map.items()}

            def _replace_link(match):
                ref = match.group(1).lower()
                return lowercase_map.get(ref, f"(Ref: {match.group(1)})")

            result.content = re.sub(
                r'\{\{[Ll][Ii][Nn][Kk]:([a-fA-F0-9]+)\}\}',
                _replace_link,
                result.content
            )

            # Log statistics and send content_sync if any replacements were made
            if result.content != original_content:
                unresolved = len(re.findall(r'\(Ref: [a-fA-F0-9]+\)', result.content))
                log(f"[AI Agent] Link placeholders replaced ({len(link_map)} refs available)")
                if unresolved > 0:
                    log(f"[AI Agent] Warning: {unresolved} unresolved link placeholder(s)")

                # Send final content_sync so frontend gets resolved links
                if task_id:
                    try:
                        from assistant.core.sse_manager import publish_content_sync, has_queue
                        if has_queue(task_id):
                            publish_content_sync(task_id, result.content, is_thinking=False)
                            log(f"[AI Agent] Sent content_sync with resolved links to frontend")
                    except Exception as e:
                        log(f"[AI Agent] Failed to send link content_sync: {e}")

    # === SYSTEM LOG: Full debug output ===
    # Log response content for debugging (goes to system.log)
    # Controlled by agent_logging.system_log_full_content config
    if log_config.get("system_log_full_content", False):
        if result.success:
            log(f"[AI Agent] Response ({len(result.content)} chars):")
            log("-" * 40)
            # Log full response (truncated for very long outputs)
            if len(result.content) > 10000:
                log(result.content[:10000] + f"\n... [truncated, {len(result.content)} total chars]")
            else:
                log(result.content)
            log("-" * 40)
        elif result.error:
            log(f"[AI Agent] Error: {result.error}")
    else:
        # Minimal logging - just status
        if result.success:
            log(f"[AI Agent] Response: {len(result.content)} chars (content logging disabled)")
        elif result.error:
            log(f"[AI Agent] Error: {result.error}")

    # === AGENT CALL LOGGING ===
    # Log summary to system.log
    log_task_summary(
        task_name=task_name or "unknown",
        result=result,
        dev_context=get_dev_context()
    )

    # Stop log buffer and write to log file + capture for DB storage
    console_logs = stop_log_buffer() if log_config.get("enabled", False) else None
    result.log_content = write_agent_log(
        config=config,
        agent_name=backend_name,
        task_name=task_name,
        task_type=task_type,
        prompt=prompt,
        result=result,
        dev_context=get_dev_context(),
        console_logs=console_logs
    )

    # [069] Store anon_context back into TaskContext for next round
    # When task_context is provided by caller, this persists across rounds automatically
    if anon_context:
        ctx.anon_context = anon_context

    # Capture simulated actions from TaskContext before clearing (for dry-run mode)
    if dry_run:
        ctx = get_task_context()
        if ctx.simulated_actions:
            result.simulated_actions = ctx.simulated_actions.copy()
            log(f"[AI Agent] Captured {len(result.simulated_actions)} simulated actions")

    # [069] Conditional cleanup: only clear if we own the context
    # When caller provides task_context, they are responsible for cleanup
    if owns_context:
        # Clean up DevContext - AFTER write_agent_log() to ensure data is logged first
        clear_dev_context(task_id)
        # Clean up TaskContext - important for sequential tasks in same thread
        clear_task_context()
        log(f"[AI Agent] TaskContext cleared: task_id={task_id}")
    else:
        log(f"[AI Agent] TaskContext retained (caller owns): task_id={task_id}")

    return result


# Config resolver functions - re-export for backwards compatibility
from .config_resolver import (
    resolve_all_placeholders,
    resolve_config_placeholders,
)

# Prompt builder functions - re-export for backwards compatibility
from .prompt_builder import (
    DEFAULT_SYSTEM_PROMPT,
    build_system_prompt,
    build_system_prompt_parts,
)

# Export public API
__all__ = [
    "call_agent",
    "AgentResponse",
    "AgentMetrics",
    "get_agent_config",
    "extract_json",
    "clean_tool_markers",
    "set_logger",
    "set_console_logging",
    "log",
    "init_system_log",
    "system_log",
    # Token utilities
    "estimate_tokens",
    "format_tokens",
    "get_context_limit",
    "calculate_cost",
    # Config resolver
    "resolve_all_placeholders",
    "resolve_config_placeholders",
    # Prompt builder
    "DEFAULT_SYSTEM_PROMPT",
    "build_system_prompt",
    "build_system_prompt_parts",
]
