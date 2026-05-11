# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Agent Logging
=============
Logging utilities for AI agent executions.

This module provides:
- AgentResponse: Dataclass for agent call results
- write_prompt_log: Write complete prompt to log file
- write_agent_log: Write agent execution details to log file
- log_task_summary: Log task completion summary

These functions centralize all agent-related logging, ensuring consistent
output across all AI backends.

Usage:
    from ai_agent.agent_logging import AgentResponse, write_agent_log, log_task_summary

    result = AgentResponse(success=True, content="...")
    write_agent_log(config, "claude", "my_skill", "skill", prompt, result)
    log_task_summary("my_skill", result)
"""

import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

# Path is set up by ai_agent/__init__.py
from paths import get_logs_dir

# Import from extracted modules (lazy to avoid circular imports at module level)
from .logging import log, system_log
from .token_utils import estimate_tokens, format_tokens, get_context_limit

# Type checking imports (no runtime cost)
if TYPE_CHECKING:
    from .metrics import AgentMetrics

__all__ = [
    "AgentResponse",
    "write_prompt_log",
    "write_agent_log",
    "log_task_summary",
]


@dataclass
class AgentResponse:
    """
    Response from an AI Agent.

    This is the standard return type for all agent backend calls.
    It includes the response content, error information, usage metrics,
    and optional metadata like anonymization mappings.

    Attributes:
        success: Whether the agent call completed successfully
        content: The agent's response text
        error: Error message if success is False
        raw_output: Unprocessed output (for debugging)
        anonymization: Dict of {placeholder: original} if anonymization was applied
        cancelled: True if task was cancelled by user
        model: Name of the model used
        input_tokens: Number of input tokens consumed
        output_tokens: Number of output tokens generated
        duration_seconds: Total execution time
        cost_usd: Estimated cost in USD
        metrics: AgentMetrics object with detailed performance data
        simulated_actions: List of simulated actions (dry-run mode)
        log_content: Execution log content (for database storage)
        sdk_session_id: Claude SDK session ID for resume (extended mode only)
        can_resume: True if session can be resumed via SDK
        structured_output: Structured output dict (extended mode with output_schema)
    """
    success: bool
    content: str
    error: Optional[str] = None
    raw_output: Optional[str] = None
    anonymization: Optional[dict] = None
    cancelled: bool = False
    # Usage/stats info
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    duration_seconds: Optional[float] = None
    cost_usd: Optional[float] = None
    # Performance metrics
    metrics: Optional['AgentMetrics'] = None
    # Dry-run mode results (captured before TaskContext is cleared)
    simulated_actions: Optional[list] = None
    # Execution log content (for storing in session history DB)
    log_content: Optional[str] = None
    # SDK Extended Mode (sdk_mode: extended) - Claude SDK only
    sdk_session_id: Optional[str] = None  # Session ID for resume capability
    can_resume: bool = False              # True if session can be resumed
    structured_output: Optional[dict] = None  # Structured output (JSON schema mode)
    # Anonymization session ID (for API-based de-anonymization)
    anon_session_id: Optional[str] = None  # Session ID for server-side mappings
    # [069] anon_context moved to TaskContext - no longer needed in AgentResponse


def _get_logs_dir() -> Path:
    """Get or create the logs directory (in User-Space)."""
    return get_logs_dir()


def write_prompt_log(
    system_prompt: str,
    user_prompt: str,
    agent_name: str = "",
    model: str = "",
    tools: list = None
):
    """
    Write the complete prompt (system + user) to a single log file.

    This file is overwritten on each new agent call, providing a quick way
    to inspect the exact prompt being sent to the AI. Useful for debugging
    token usage, knowledge loading, and prompt composition.

    The log includes:
    - Timestamp and agent/model info
    - Token estimates for system and user prompts
    - Knowledge stats (files, tokens, threshold status)
    - Template stats (if dialogs loaded)
    - Available tools list
    - Full system prompt content
    - Full user prompt content

    Args:
        system_prompt: The full system prompt including knowledge, templates, etc.
        user_prompt: The user's task/prompt
        agent_name: Name of the agent/backend being used
        model: Model name being used
        tools: List of available tools (dicts with 'name' and optional 'description')
    """
    # Lazy import to avoid circular dependencies
    from .knowledge_loader import get_last_knowledge_stats
    from .template_loader import get_last_template_stats

    logs_dir = _get_logs_dir()
    prompt_log_path = logs_dir / "prompt_latest.txt"

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Calculate token estimates
    system_tokens = estimate_tokens(system_prompt)
    user_tokens = estimate_tokens(user_prompt)
    total_tokens = system_tokens + user_tokens

    # Get context limit for model
    context_limit = get_context_limit(model)
    usage_percent = (total_tokens / context_limit * 100) if context_limit > 0 else 0

    lines = []
    lines.append("=" * 80)
    lines.append("PROMPT LOG")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Timestamp:      {timestamp}")
    lines.append(f"Agent:          {agent_name}")
    lines.append(f"Model:          {model}")
    lines.append(f"Context Limit:  {format_tokens(context_limit)} tokens")
    lines.append("")
    lines.append("-" * 40)
    lines.append("TOKEN ESTIMATES")
    lines.append("-" * 40)
    lines.append(f"System Prompt:  {format_tokens(system_tokens)} tokens ({len(system_prompt)} chars)")
    lines.append(f"User Prompt:    {format_tokens(user_tokens)} tokens ({len(user_prompt)} chars)")
    lines.append(f"Total:          {format_tokens(total_tokens)} tokens ({usage_percent:.1f}% of limit)")
    lines.append("")

    # Add knowledge stats if available
    knowledge_stats = get_last_knowledge_stats()
    if knowledge_stats:
        lines.append("-" * 40)
        lines.append("KNOWLEDGE STATS")
        lines.append("-" * 40)
        lines.append(f"Files:          {knowledge_stats.get('files_count', 0)}")
        lines.append(f"Tokens:         {knowledge_stats.get('total_tokens', 0):,}")
        lines.append(f"Chars:          {knowledge_stats.get('total_chars', 0):,}")
        lines.append(f"Threshold:      {knowledge_stats.get('threshold_tokens', 30000):,}")
        exceeds = knowledge_stats.get('exceeds_threshold', False)
        lines.append(f"Status:         {'EXCEEDS THRESHOLD' if exceeds else 'OK'}")
        lines.append(f"Mode:           {knowledge_stats.get('mode', 'full')}")
        lines.append(f"Cache Hit:      {knowledge_stats.get('cache_hit', False)}")
        lines.append(f"Load Time:      {knowledge_stats.get('load_time_ms', 0):.1f}ms")

        # List files
        files = knowledge_stats.get('files', [])
        if files:
            lines.append("")
            lines.append("Knowledge Files:")
            for f in files:
                lines.append(f"  - {f.get('name', '?')}: {f.get('tokens', 0):,} tokens")
        lines.append("")

    # Add template stats if available
    template_stats = get_last_template_stats()
    if template_stats:
        lines.append("-" * 40)
        lines.append("TEMPLATES")
        lines.append("-" * 40)
        if template_stats.get('skipped'):
            lines.append("Status:         SKIPPED (skip_dialogs: true)")
            lines.append("Tokens saved:   ~1,400 tokens")
        else:
            lines.append(f"Files:          {len(template_stats.get('files', []))}")
            lines.append(f"Tokens:         {template_stats.get('total_tokens', 0):,}")
            # List files
            for f in template_stats.get('files', []):
                lines.append(f"  - {f.get('name', '?')}: {f.get('tokens', 0):,} tokens")
            # Add hint if dialogs loaded
            if any(f.get('name') == 'dialogs' for f in template_stats.get('files', [])):
                lines.append("")
                lines.append("TIP: Add 'skip_dialogs: true' in agent config to skip (~1,400 tokens)")
        lines.append("")

    # Add tools section if tools provided
    if tools:
        lines.append("-" * 40)
        lines.append(f"AVAILABLE TOOLS ({len(tools)})")
        lines.append("-" * 40)
        for tool in tools:
            tool_name = tool.get("name", str(tool)) if isinstance(tool, dict) else str(tool)
            lines.append(f"  - {tool_name}")
        lines.append("")

    lines.append("=" * 80)
    lines.append("SYSTEM PROMPT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(system_prompt)
    lines.append("")
    lines.append("=" * 80)
    lines.append("USER PROMPT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(user_prompt)
    lines.append("")
    lines.append("=" * 80)

    log_content = "\n".join(lines)

    try:
        with open(prompt_log_path, "w", encoding="utf-8") as f:
            f.write(log_content)
        log(f"[PromptLog] Saved: prompt_latest.txt ({format_tokens(total_tokens)} tokens, {usage_percent:.1f}% of {format_tokens(context_limit)})")
    except Exception as e:
        log(f"[PromptLog] Failed to write: {e}")


def write_agent_log(
    config: dict,
    agent_name: str,
    task_name: str,
    task_type: str,
    prompt: str,
    result: 'AgentResponse',
    dev_context: dict = None,
    console_logs: list = None
) -> str:
    """
    Write agent call to log file (agent_latest.txt only).

    Historical logs are now stored in the database via session_store.
    This file is only for quick access to the most recent execution.

    The log includes:
    - Header with timestamp, agent, task, model info
    - Metrics section (tokens, cost, duration)
    - Knowledge stats (if available)
    - Tool calls summary with args
    - Console log messages
    - Full prompt and response content

    Args:
        config: Configuration with agent_logging settings
        agent_name: Name of AI backend used (e.g., "claude_sdk", "gemini")
        task_name: Name of skill or agent
        task_type: "skill" or "agent"
        prompt: The prompt sent to the agent
        result: AgentResponse from the call
        dev_context: Optional developer context with tool results
        console_logs: Optional list of console log messages

    Returns:
        The log content string (for storing in database)
    """
    # Lazy import to avoid circular dependencies
    from .knowledge_loader import get_last_knowledge_stats

    log_config = config.get("agent_logging", {})
    max_content_length = log_config.get("max_content_length", 50000)

    logs_dir = _get_logs_dir()

    # Build text log content
    timestamp = datetime.datetime.now()
    lines = []

    # Header
    lines.append("=" * 80)
    lines.append(f"AGENT LOG: {task_name or 'unknown'}")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Timestamp:    {timestamp.isoformat()}")
    lines.append(f"Agent:        {agent_name}")
    lines.append(f"Task:         {task_name} ({task_type})")
    lines.append(f"Model:        {result.model or 'unknown'}")
    lines.append(f"Success:      {result.success}")
    if result.error:
        lines.append(f"Error:        {result.error}")
    if result.cancelled:
        lines.append(f"Cancelled:    {result.cancelled}")
    lines.append("")

    # Metrics
    lines.append("-" * 40)
    lines.append("METRICS")
    lines.append("-" * 40)
    lines.append(f"Input Tokens:   {result.input_tokens or 'N/A'}")
    lines.append(f"Output Tokens:  {result.output_tokens or 'N/A'}")
    lines.append(f"Cost USD:       ${result.cost_usd:.4f}" if result.cost_usd else "Cost USD:       N/A")
    lines.append(f"Duration:       {result.duration_seconds:.2f}s" if result.duration_seconds else "Duration:       N/A")
    if result.anonymization:
        lines.append(f"Anonymized:     {len(result.anonymization)} entities")
    lines.append("")

    # Knowledge stats
    knowledge_stats = get_last_knowledge_stats()
    if knowledge_stats and knowledge_stats.get('files_count', 0) > 0:
        lines.append("-" * 40)
        lines.append("KNOWLEDGE")
        lines.append("-" * 40)
        lines.append(f"Files:          {knowledge_stats.get('files_count', 0)}")
        lines.append(f"Tokens:         {knowledge_stats.get('total_tokens', 0):,}")
        lines.append(f"Threshold:      {knowledge_stats.get('threshold_tokens', 30000):,}")
        exceeds = knowledge_stats.get('exceeds_threshold', False)
        lines.append(f"Status:         {'EXCEEDS THRESHOLD' if exceeds else 'OK'}")
        lines.append(f"Mode:           {knowledge_stats.get('mode', 'full')}")
        # Show files summary
        files = knowledge_stats.get('files', [])
        if files:
            files_str = ", ".join(f"{f.get('name', '?')}({f.get('tokens', 0)})" for f in files[:5])
            if len(files) > 5:
                files_str += f" +{len(files)-5} more"
            lines.append(f"Files:          {files_str}")
        lines.append("")

    # Tool calls
    if dev_context and dev_context.get("tool_results"):
        lines.append("-" * 40)
        lines.append(f"TOOL CALLS ({len(dev_context['tool_results'])})")
        lines.append("-" * 40)
        for i, tr in enumerate(dev_context["tool_results"], 1):
            chars = len(tr['result']) if tr.get('result') else 0
            anon = tr.get('anon_count', 0)
            anon_str = f", {anon} PII" if anon > 0 else ""
            # Show tool name and result size
            lines.append(f"  [{i}] {tr['tool']} ({chars} chars{anon_str})")
            # Show args if present (for debugging)
            if tr.get('args'):
                args_str = json.dumps(tr['args'], ensure_ascii=False)
                # Truncate very long args
                if len(args_str) > 500:
                    args_str = args_str[:500] + "..."
                lines.append(f"      Args: {args_str}")
        lines.append("")

    # Console log
    if console_logs:
        lines.append("-" * 40)
        lines.append("CONSOLE LOG")
        lines.append("-" * 40)
        for msg in console_logs:
            lines.append(msg)
        lines.append("")

    # Prompt
    lines.append("-" * 40)
    lines.append("PROMPT")
    lines.append("-" * 40)
    prompt_text = prompt[:max_content_length] if prompt else "(empty)"
    lines.append(prompt_text)
    lines.append("")

    # Response
    lines.append("-" * 40)
    lines.append("RESPONSE")
    lines.append("-" * 40)
    response_text = result.content[:max_content_length] if result.content else "(empty)"
    lines.append(response_text)
    lines.append("")
    lines.append("=" * 80)

    # Build log content
    log_content = "\n".join(lines)

    # Write to agent_latest.txt only (historical logs are stored in DB)
    # Only write file if logging is enabled in config
    if log_config.get("enabled", False):
        latest_path = logs_dir / "agent_latest.txt"
        try:
            with open(latest_path, "w", encoding="utf-8") as f:
                f.write(log_content)
            log(f"[AgentLog] Saved: agent_latest.txt")
        except Exception as e:
            log(f"[AgentLog] Failed to write log: {e}")

    # Always return content for DB storage
    return log_content


def log_task_summary(
    task_name: str,
    result: 'AgentResponse',
    metrics: 'AgentMetrics' = None,
    dev_context: dict = None
):
    """
    Log a summary line for a completed task to system.log.

    This provides a quick overview of what happened in the task for debugging.
    The summary is a single line with key metrics separated by pipes.

    Format: [Task Summary] name | status | duration | tokens | cost | tools | anon

    Args:
        task_name: Name of the skill/agent
        result: AgentResponse from the call
        metrics: Optional AgentMetrics with turn/tool data
        dev_context: Optional developer context with tool names

    Example output:
        [Task Summary] reply_email | OK | 5.2s | 15.2K->2.1K tokens | $0.0234 | 3 tools: outlook_get_email, outlook_reply
    """
    parts = [f"[Task Summary] {task_name}"]

    # Status
    if result.cancelled:
        parts.append("CANCELLED")
    elif result.success:
        parts.append("OK")
    else:
        parts.append(f"FAILED: {result.error[:50]}..." if result.error and len(result.error) > 50 else f"FAILED: {result.error}")

    # Duration
    if result.duration_seconds:
        parts.append(f"{result.duration_seconds:.1f}s")

    # Tokens
    if result.input_tokens or result.output_tokens:
        parts.append(f"{format_tokens(result.input_tokens or 0)}->{format_tokens(result.output_tokens or 0)} tokens")

    # Cost
    if result.cost_usd and result.cost_usd > 0:
        parts.append(f"${result.cost_usd:.4f}")

    # Tool calls
    if metrics:
        parts.append(f"{metrics.ai_turns} turns, {metrics.tool_calls} tools")
    elif dev_context and dev_context.get("tool_results"):
        tool_count = len(dev_context["tool_results"])
        # Get unique tool names
        tool_names = list(set(tr.get("tool", "?") for tr in dev_context["tool_results"]))
        if len(tool_names) <= 5:
            parts.append(f"{tool_count} tools: {', '.join(tool_names)}")
        else:
            parts.append(f"{tool_count} tools ({len(tool_names)} unique)")

    # Anonymization
    if result.anonymization:
        parts.append(f"anon:{len(result.anonymization)}")

    summary = " | ".join(parts)
    system_log(summary)
