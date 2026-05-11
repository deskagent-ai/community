# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Claude API Agent
=================
Direct Anthropic API with streaming and tool support.
Uses tool_bridge for dynamic MCP tool discovery.
"""

import json
import sys
import time
from pathlib import Path
from paths import PROJECT_DIR
from .agent_logging import AgentResponse, write_prompt_log
from .logging import log
from .prompt_builder import build_system_prompt
from . import tool_bridge
from . import anonymizer

# Add project root to path for MCP imports
sys.path.insert(0, str(PROJECT_DIR))


def check_configured(config: dict) -> tuple:
    """
    Check if this backend is properly configured.

    Args:
        config: Backend configuration dict

    Returns:
        Tuple of (is_configured: bool, issue: str or None)
    """
    api_key = config.get("api_key", "")

    if not api_key:
        return False, "API key missing"
    if api_key.startswith("YOUR_") or api_key == "sk-...":
        return False, "API key is placeholder"
    if len(api_key) < 10:
        return False, "API key too short"

    return True, None


def _stream_with_retry(client, kwargs, max_retries=3):
    """Make streaming request with exponential backoff retry on rate limits."""
    import anthropic

    for attempt in range(max_retries):
        try:
            return client.messages.stream(**kwargs)
        except anthropic.RateLimitError:
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 10  # 10s, 20s, 40s
                log(f"[Claude API] Rate limit hit, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                log(f"[Claude API] Rate limit exceeded after {max_retries} attempts")
                raise


def _get_tools(mcp_filter: str = None, allowed_tools: list = None, blocked_tools: list = None, tool_mode: str = None) -> list:
    """Get tools in Anthropic format.

    Args:
        mcp_filter: Optional regex pattern to filter MCP servers (e.g., "outlook|billomat")
        allowed_tools: Optional whitelist of tool names (e.g., ["read_file", "list_directory"])
        blocked_tools: Optional blacklist of tool names (e.g., ["delete_email"])
        tool_mode: Optional security mode ("full", "read_only", "write_safe")
    """
    ollama_tools = tool_bridge.get_ollama_tools(mcp_filter, allowed_tools, blocked_tools, tool_mode)

    # Convert Ollama format to Anthropic format
    anthropic_tools = []
    for tool in ollama_tools:
        func = tool.get("function", {})
        anthropic_tools.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "input_schema": func.get("parameters", {"type": "object", "properties": {}})
        })

    log(f"[Claude API] Loaded {len(anthropic_tools)} tools")
    return anthropic_tools


def call_claude_api(
    prompt: str,
    config: dict,
    agent_config: dict,
    use_tools: bool = False,
    on_chunk: callable = None,
    anon_context: "anonymizer.AnonymizationContext" = None,
    tool_confirm_callback: callable = None
) -> AgentResponse:
    """
    Call Claude API with streaming and optional tool support.

    Args:
        prompt: The prompt for the model
        config: Main configuration
        agent_config: Agent-specific configuration
        use_tools: If True, enable tool calling
        on_chunk: Optional callback for streaming updates
                  Signature: on_chunk(token, is_thinking, full_response)
        anon_context: Optional anonymization context for tool results
        tool_confirm_callback: Optional callback for tool confirmation
                  Signature: tool_confirm_callback(tool_name, tool_input) -> bool
                  Returns True to allow, False to skip tool
    """
    try:
        import anthropic
    except ImportError:
        return AgentResponse(
            success=False,
            content="",
            error="anthropic package not installed. Run: pip install anthropic"
        )

    api_key = agent_config.get("api_key", "")
    model = agent_config.get("model", "claude-opus-4-6")
    timeout = agent_config.get("timeout", 120)
    max_tokens = agent_config.get("max_tokens", 4096)
    prompt_caching = agent_config.get("prompt_caching", False)
    extended_thinking = agent_config.get("extended_thinking", False)
    thinking_budget = agent_config.get("thinking_budget", 10000)

    if not api_key:
        return AgentResponse(
            success=False,
            content="",
            error="No API key configured for claude_api"
        )

    # Build system message (base prompt + security warning + templates + knowledge)
    system_message = build_system_prompt(agent_config, config=config)

    # Log context
    log(f"[Claude API] === Context Summary ===")
    log(f"[Claude API]   Model: {model}")
    log(f"[Claude API]   Tools enabled: {use_tools}")
    log(f"[Claude API]   Prompt caching: {prompt_caching}")
    log(f"[Claude API]   Extended thinking: {extended_thinking}")
    if extended_thinking:
        log(f"[Claude API]   Thinking budget: {thinking_budget}")
    log(f"[Claude API]   System prompt: {len(system_message)} chars")
    log(f"[Claude API]   Prompt: {len(prompt)} chars")
    log(f"[Claude API] ===========================")

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Build system message (with optional caching)
        if prompt_caching:
            system_param = [
                {
                    "type": "text",
                    "text": system_message,
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        else:
            system_param = system_message

        # Build request kwargs
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_param,
            "messages": [{"role": "user", "content": prompt}]
        }

        api_tools = None
        if use_tools:
            # Get MCP filter pattern from agent config
            mcp_filter = agent_config.get("allowed_mcp")
            allowed_tools = agent_config.get("allowed_tools")
            blocked_tools = agent_config.get("blocked_tools")
            tool_mode = agent_config.get("tool_mode", "full")
            if mcp_filter:
                log(f"[Claude API] MCP filter: {mcp_filter}")
                # Set MCP filter in TaskContext for execute_tool() to use
                # (important for hallucinated tool names that need auto-correction)
                tool_bridge.set_mcp_filter(mcp_filter)
            if allowed_tools:
                log(f"[Claude API] Allowed tools (whitelist): {allowed_tools}")
            if blocked_tools:
                log(f"[Claude API] Blocked tools (blacklist): {blocked_tools}")
            if tool_mode != "full":
                log(f"[Claude API] Tool mode: {tool_mode}")
            # Set anonymization context for tool input de-anonymization
            if anon_context is not None:
                tool_bridge.set_anonymization_context(anon_context)
            api_tools = _get_tools(mcp_filter, allowed_tools, blocked_tools, tool_mode)
            kwargs["tools"] = api_tools

        # Write complete prompt to log file (overwritten each time)
        write_prompt_log(system_message, prompt, agent_name="claude_api", model=model, tools=api_tools)

        # Extended thinking (note: not compatible with tools)
        if extended_thinking and not use_tools:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget
            }

        # Make streaming request with retry
        full_response = ""
        thinking_response = ""
        in_thinking = False
        tool_timings = {}  # Track tool execution times

        with _stream_with_retry(client, kwargs) as stream:
            for event in stream:
                if hasattr(event, 'type'):
                    # Track content block types for thinking
                    if event.type == 'content_block_start':
                        if hasattr(event, 'content_block'):
                            if event.content_block.type == 'thinking':
                                in_thinking = True
                                log("[Claude API] Thinking block started")
                            elif event.content_block.type == 'text':
                                in_thinking = False

                    elif event.type == 'content_block_delta':
                        # Handle thinking delta
                        if hasattr(event.delta, 'thinking'):
                            thinking_token = event.delta.thinking
                            thinking_response += thinking_token
                            if on_chunk:
                                try:
                                    on_chunk(thinking_token, True, thinking_response)
                                except Exception as e:
                                    log(f"[Claude API] Callback error: {e}")
                        # Handle text delta
                        elif hasattr(event.delta, 'text'):
                            token = event.delta.text
                            full_response += token
                            if on_chunk:
                                try:
                                    on_chunk(token, False, full_response)
                                except Exception as e:
                                    log(f"[Claude API] Callback error: {e}")

                    elif event.type == 'content_block_stop':
                        if in_thinking:
                            in_thinking = False
                            log(f"[Claude API] Thinking complete: {len(thinking_response)} chars")

        # Get final message for tool use
        message = stream.get_final_message()

        # Log and capture token usage
        input_tokens = None
        output_tokens = None
        if hasattr(message, 'usage'):
            usage = message.usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            log(f"[Claude API] Tokens: {input_tokens} in, {output_tokens} out")

        # If streaming didn't capture text, extract from final message content
        if not full_response.strip() and hasattr(message, 'content'):
            for block in message.content:
                if hasattr(block, 'text'):
                    full_response += block.text

        # Check for tool use
        if message.stop_reason == "tool_use":
            tool_results = []
            for block in message.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id

                    log(f"[Claude API] Tool requested: {tool_name}")
                    log(f"[Claude API] Args: {tool_input}")

                    # Start timing and send tool marker
                    tool_timings[tool_name] = time.time()
                    input_str = str(tool_input)
                    input_preview = input_str[:60].replace('\n', ' ')
                    if len(input_str) > 60:
                        input_preview += "..."
                    tool_msg = f"\n[Tool: {tool_name} ...] `{input_preview}`\n"
                    full_response += tool_msg
                    if on_chunk:
                        try:
                            on_chunk(tool_msg, False, full_response)
                        except Exception as e:
                            log(f"[Claude API] Callback error: {e}")

                    # Ask for user confirmation if callback provided
                    if tool_confirm_callback:
                        confirmed = tool_confirm_callback(tool_name, tool_input)
                        if not confirmed:
                            log(f"[Claude API] Tool {tool_name} rejected by user")
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": f"Tool execution was rejected by user.",
                                "is_error": True
                            })
                            continue

                    log(f"[Claude API] Executing tool: {tool_name}")
                    result = tool_bridge.execute_tool(tool_name, tool_input)
                    log(f"[Claude API] Result length: {len(result)} chars")

                    # Update tool marker with duration
                    if tool_name in tool_timings:
                        tool_duration = time.time() - tool_timings[tool_name]
                        del tool_timings[tool_name]
                        old_marker = f"[Tool: {tool_name} ...]"
                        new_marker = f"[Tool: {tool_name} | {tool_duration:.1f}s]"
                        full_response = full_response.replace(old_marker, new_marker)
                        if on_chunk:
                            try:
                                on_chunk("", False, full_response)
                            except Exception:
                                pass
                        log(f"[Claude API] Tool {tool_name} completed in {tool_duration:.2f}s")

                    # Anonymize tool result if context is provided
                    if anon_context is not None:
                        result, anon_context = anonymizer.anonymize_with_context(
                            result, config, anon_context
                        )
                        if anon_context.mappings:
                            log(f"[Claude API] Tool result anonymized: {len(anon_context.mappings)} entities")
                            # Show anonymized tool result - VERY VISIBLE
                            log("")
                            log("=" * 70)
                            log(f">>>  ANONYMIZED TOOL RESULT SENT TO AI  ({tool_name})  <<<")
                            log("=" * 70)
                            log(result[:2000] + "..." if len(result) > 2000 else result)
                            log("=" * 70)
                            log("")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result
                    })

            # Continue conversation with tool results
            if tool_results:
                full_response, anon_context = _continue_with_tools(
                    client, model, max_tokens, system_message,
                    prompt, message, tool_results,
                    use_tools, on_chunk, config, anon_context,
                    tool_confirm_callback=tool_confirm_callback
                )

        log(f"[Claude API] === RESPONSE ===")
        log(full_response[:500] + "..." if len(full_response) > 500 else full_response)
        log(f"[Claude API] ================")

        if not full_response.strip():
            return AgentResponse(
                success=False,
                content="",
                error="Empty response from Claude API"
            )

        # Calculate cost based on pricing config
        cost_usd = None
        if input_tokens and output_tokens:
            pricing = config.get("ai_backends", {}).get("claude_api", {}).get("pricing", {})
            input_price = pricing.get("input", 3)  # $/1M tokens
            output_price = pricing.get("output", 15)  # $/1M tokens
            cost_usd = (input_tokens * input_price + output_tokens * output_price) / 1_000_000

        return AgentResponse(
            success=True,
            content=full_response,
            raw_output=full_response,
            anonymization=dict(anon_context.mappings) if anon_context and anon_context.mappings else None,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd
        )

    except anthropic.APIError as e:
        log(f"[Claude API] API Error: {e}")
        return AgentResponse(
            success=False,
            content="",
            error=f"Claude API error: {e}"
        )
    except Exception as e:
        log(f"[Claude API] Error: {e}")
        return AgentResponse(
            success=False,
            content="",
            error=str(e)
        )


def _continue_with_tools(
    client,
    model: str,
    max_tokens: int,
    system_message: str,
    original_prompt: str,
    assistant_message,
    tool_results: list,
    use_tools: bool,
    on_chunk: callable,
    config: dict = None,
    anon_context: "anonymizer.AnonymizationContext" = None,
    depth: int = 1,
    tool_confirm_callback: callable = None
) -> tuple:
    """Continue conversation after tool execution. Returns (response, anon_context)."""
    log(f"[Claude API] Continuing with {len(tool_results)} tool results (depth={depth})")

    # Use minimal system message for continuations (knowledge already in context)
    continuation_system = """Fahre mit der Aufgabe fort basierend auf den Tool-Ergebnissen.
Du kannst weitere Tools aufrufen wenn nötig um die Aufgabe abzuschließen.
Regeln:
- Verwende NUR Fakten aus der Wissenbasis (bereits im Kontext)
- Erfinde KEINE Daten
- Antworte auf Deutsch, außer die Anfrage ist auf Englisch
- KEINE Signatur - Outlook fügt sie automatisch hinzu"""

    # Truncate tool results to reduce continuation token costs
    # Each tool result can be 80K+ tokens for email lists - this causes massive costs
    # Strategy: Keep IDs and key metadata, truncate body content
    MAX_TOOL_RESULT_CHARS = 12000  # ~3K tokens per result - enough for ~30 email headers with IDs
    truncated_results = []
    for tr in tool_results:
        if isinstance(tr, dict) and "content" in tr:
            content = tr["content"]
            if isinstance(content, str) and len(content) > MAX_TOOL_RESULT_CHARS:
                # Smart truncation: preserve IDs and headers at the start
                # IDs are typically at the beginning of email lists
                truncated_content = content[:MAX_TOOL_RESULT_CHARS] + (
                    f"\n\n[TRUNCATED for token efficiency - {len(content) - MAX_TOOL_RESULT_CHARS} chars omitted]\n"
                    f"Note: You already saw the full data above. Use the IDs you extracted earlier."
                )
                truncated_results.append({**tr, "content": truncated_content})
                log(f"[Claude API] Truncated tool result: {len(content)} -> {MAX_TOOL_RESULT_CHARS} chars (saved ~{(len(content) - MAX_TOOL_RESULT_CHARS) // 4} tokens)")
            else:
                truncated_results.append(tr)
        else:
            truncated_results.append(tr)

    # Build messages with truncated tool results
    messages = [
        {"role": "user", "content": original_prompt},
        {"role": "assistant", "content": assistant_message.content},
        {"role": "user", "content": truncated_results}
    ]

    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "system": continuation_system,
        "messages": messages
    }

    # Include tools up to depth 5 to support complex agents like create_offer
    # (which needs: get_email, search_customer, create_customer, create_offer, add_item x2)
    if use_tools and depth <= 5:
        kwargs["tools"] = _get_tools()
        log(f"[Claude API] Tools included (depth={depth})")
    else:
        log(f"[Claude API] Tools skipped to save tokens (depth={depth})")

    full_response = ""
    tool_timings = {}  # Track tool execution times

    with _stream_with_retry(client, kwargs) as stream:
        for event in stream:
            if hasattr(event, 'type'):
                if event.type == 'content_block_delta':
                    if hasattr(event.delta, 'text'):
                        token = event.delta.text
                        full_response += token
                        if on_chunk:
                            try:
                                on_chunk(token, False, full_response)
                            except Exception:
                                pass

    # Check for more tool calls
    message = stream.get_final_message()

    # Log token usage and stop reason
    if hasattr(message, 'usage'):
        usage = message.usage
        log(f"[Claude API] Continuation tokens: {usage.input_tokens} in, {usage.output_tokens} out")

    # If streaming didn't capture text, extract from final message content
    if not full_response.strip() and hasattr(message, 'content'):
        for block in message.content:
            if hasattr(block, 'text'):
                full_response += block.text

    if message.stop_reason == "tool_use":
        more_results = []
        for block in message.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input

                log(f"[Claude API] Tool requested: {tool_name}")

                # Start timing and send tool marker
                tool_timings[tool_name] = time.time()
                input_str = str(tool_input)
                input_preview = input_str[:60].replace('\n', ' ')
                if len(input_str) > 60:
                    input_preview += "..."
                tool_msg = f"\n[Tool: {tool_name} ...] `{input_preview}`\n"
                full_response += tool_msg
                if on_chunk:
                    try:
                        on_chunk(tool_msg, False, full_response)
                    except Exception:
                        pass

                # Ask for user confirmation if callback provided
                if tool_confirm_callback:
                    confirmed = tool_confirm_callback(tool_name, tool_input)
                    if not confirmed:
                        log(f"[Claude API] Tool {tool_name} rejected by user")
                        more_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Tool execution was rejected by user.",
                            "is_error": True
                        })
                        continue

                log(f"[Claude API] Executing tool: {tool_name}")
                result = tool_bridge.execute_tool(tool_name, tool_input)
                log(f"[Claude API] Result length: {len(result)} chars")

                # Update tool marker with duration
                if tool_name in tool_timings:
                    tool_duration = time.time() - tool_timings[tool_name]
                    del tool_timings[tool_name]
                    old_marker = f"[Tool: {tool_name} ...]"
                    new_marker = f"[Tool: {tool_name} | {tool_duration:.1f}s]"
                    full_response = full_response.replace(old_marker, new_marker)
                    if on_chunk:
                        try:
                            on_chunk("", False, full_response)
                        except Exception:
                            pass
                    log(f"[Claude API] Tool {tool_name} completed in {tool_duration:.2f}s")

                # Anonymize tool result if context is provided
                if anon_context is not None and config is not None:
                    result, anon_context = anonymizer.anonymize_with_context(
                        result, config, anon_context
                    )
                    if anon_context.mappings:
                        log(f"[Claude API] Tool result anonymized: {len(anon_context.mappings)} entities")

                more_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result
                })

        if more_results:
            return _continue_with_tools(
                client, model, max_tokens, system_message,
                original_prompt, message, more_results,
                use_tools, on_chunk, config, anon_context, depth + 1,
                tool_confirm_callback=tool_confirm_callback
            )

    return full_response, anon_context
