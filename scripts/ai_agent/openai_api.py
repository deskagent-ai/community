# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
OpenAI API Agent
================
OpenAI GPT API with streaming and tool support.
Uses tool_bridge for dynamic MCP tool discovery.
"""

import json
import sys
import time
from pathlib import Path
from paths import PROJECT_DIR
from .agent_logging import AgentResponse, write_prompt_log
from .dev_context import add_dev_tool_result, capture_dev_context, update_dev_iteration
from .event_publishing import publish_context_event
from .logging import log, log_tool_call
from .prompt_builder import build_system_prompt
from .token_utils import estimate_tokens, format_tokens, get_context_limit
from . import tool_bridge
from . import anonymizer

# Add project root to path for MCP imports
sys.path.insert(0, str(PROJECT_DIR))

# Retry settings for transient errors (429, 5xx)
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2  # seconds, exponential backoff


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


def _call_with_retry(client, messages, model, tools=None, max_tokens=4096, temperature=0.7, stream=True, max_retries=MAX_RETRIES, parallel_tool_calls=True):
    """Call OpenAI API with retry logic for rate limits (429) and server errors (5xx).

    Uses exponential backoff: 2s, 4s, 8s between retries.

    Args:
        parallel_tool_calls: If False, force sequential tool calls (fixes Mistral JSON corruption bug)
    """
    from openai import RateLimitError, APIStatusError

    last_error = None

    # Models that require max_completion_tokens instead of max_tokens and don't support temperature
    _new_token_param_models = {"o1", "o1-mini", "o1-preview", "o3", "o3-mini", "o3-pro", "gpt-5"}
    model_lower = model.lower() if model else ""
    use_new_param = any(model_lower.startswith(m) for m in _new_token_param_models)

    for attempt in range(max_retries + 1):
        try:
            kwargs = {
                "model": model,
                "messages": messages,
                "stream": stream
            }
            # Newer OpenAI models (o1, o3, gpt-5) require max_completion_tokens
            # Reasoning models need higher budget (reasoning tokens share the limit)
            if use_new_param:
                kwargs["max_completion_tokens"] = max(max_tokens, 16384)
            else:
                kwargs["max_tokens"] = max_tokens
                kwargs["temperature"] = temperature
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
                # Disable parallel tool calls if requested (fixes Mistral JSON corruption)
                if not parallel_tool_calls:
                    kwargs["parallel_tool_calls"] = False

            return client.chat.completions.create(**kwargs)

        except RateLimitError as e:
            last_error = e
            if attempt < max_retries:
                delay = RETRY_DELAY_BASE * (2 ** attempt)
                log(f"[OpenAI] Rate limit hit (attempt {attempt + 1}/{max_retries + 1})")
                log(f"[OpenAI] Retrying in {delay}s...")
                time.sleep(delay)
                continue
            raise

        except APIStatusError as e:
            error_str = str(e)
            # Auto-fix: swap unsupported params for reasoning models (400 error)
            if e.status_code == 400 and ("max_tokens" in error_str or "temperature" in error_str):
                fixed = False
                if "max_completion_tokens" in error_str and "max_tokens" in kwargs:
                    log(f"[OpenAI] Model {model} requires max_completion_tokens, retrying...")
                    kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                    fixed = True
                if "temperature" in error_str and "temperature" in kwargs:
                    log(f"[OpenAI] Model {model} does not support custom temperature, removing...")
                    del kwargs["temperature"]
                    fixed = True
                if fixed:
                    use_new_param = True
                    return client.chat.completions.create(**kwargs)
            # Retry on 5xx server errors
            if e.status_code >= 500:
                last_error = e
                if attempt < max_retries:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    log(f"[OpenAI] Server error {e.status_code} (attempt {attempt + 1}/{max_retries + 1})")
                    log(f"[OpenAI] Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
            raise

        except Exception as e:
            raise

    # All retries exhausted
    raise last_error


def _get_tools(mcp_filter: str = None, allowed_tools: list = None, blocked_tools: list = None, tool_mode: str = None) -> list:
    """Get tools in OpenAI format.

    OpenAI uses the same format as Ollama - no conversion needed!

    Args:
        mcp_filter: Optional regex pattern to filter MCP servers
        allowed_tools: Optional whitelist of tool names
        blocked_tools: Optional blacklist of tool names
        tool_mode: Optional security mode ("full", "read_only", "write_safe")
    """
    ollama_tools = tool_bridge.get_ollama_tools(mcp_filter, allowed_tools, blocked_tools, tool_mode)

    log(f"[OpenAI] Loaded {len(ollama_tools)} tools" +
        (f" (filter: {mcp_filter})" if mcp_filter else ""))
    return ollama_tools


def call_openai_api(
    prompt: str,
    config: dict,
    agent_config: dict,
    use_tools: bool = False,
    on_chunk: callable = None,
    anon_context: "anonymizer.AnonymizationContext" = None,
    knowledge_pattern: str = None,
    is_cancelled: callable = None
) -> AgentResponse:
    """
    Call OpenAI API with streaming and optional tool support.

    Args:
        prompt: The prompt for the model
        config: Main configuration
        agent_config: Agent-specific configuration
        use_tools: If True, enable tool calling
        on_chunk: Optional callback for streaming updates
                  Signature: on_chunk(token, is_thinking, full_response, anon_mappings)
        anon_context: Optional anonymization context for tool results
        knowledge_pattern: Optional regex pattern to filter knowledge files
        is_cancelled: Optional callback that returns True if task should be cancelled
    """
    try:
        from openai import OpenAI
    except ImportError:
        return AgentResponse(
            success=False,
            content="",
            error="openai package not installed. Run: pip install openai"
        )

    api_key = agent_config.get("api_key", "")
    base_url = agent_config.get("base_url")  # For OpenAI-compatible APIs (Mistral, Groq, etc.)
    model = agent_config.get("model", "gpt-4o")
    timeout = agent_config.get("timeout", 120)
    max_tokens = agent_config.get("max_tokens", 4096)
    temperature = agent_config.get("temperature", 0.7)
    max_iterations = agent_config.get("max_iterations", 30)

    if not api_key:
        return AgentResponse(
            success=False,
            content="",
            error="No API key configured for openai_api"
        )

    # Build system message (base prompt + security warning + templates + knowledge)
    system_message = build_system_prompt(agent_config, knowledge_pattern, config=config)

    # Log context with token estimates
    system_tokens = estimate_tokens(system_message)
    prompt_tokens = estimate_tokens(prompt)
    context_limit = get_context_limit(model)
    initial_total = system_tokens + prompt_tokens

    # Token breakdown for UI display
    token_breakdown = {
        "system": system_tokens,
        "prompt": prompt_tokens,
        "tools": 0  # Will be updated as tools execute
    }

    log(f"[OpenAI] CONTEXT ESTIMATE:")
    log(f"[OpenAI]    Model: {model} ({format_tokens(context_limit)} limit)")
    log(f"[OpenAI]    System prompt: {format_tokens(system_tokens)} tokens ({len(system_message)} chars)")
    log(f"[OpenAI]    User prompt: {format_tokens(prompt_tokens)} tokens ({len(prompt)} chars)")
    log(f"[OpenAI]    Initial total: {format_tokens(initial_total)} tokens ({initial_total/context_limit*100:.1f}% of limit)")
    log(f"[OpenAI]    Tools enabled: {use_tools}")

    # Capture context for Developer Mode debugging
    capture_dev_context(system_prompt=system_message, user_prompt=prompt, model=model)

    # Send initial context breakdown to UI
    publish_context_event(
        iteration=0, max_iterations=max_iterations,
        system_tokens=system_tokens, prompt_tokens=prompt_tokens, tool_tokens=0
    )

    start_time = time.time()

    try:
        # Initialize client
        # Support custom base_url for OpenAI-compatible APIs (Mistral, Groq, etc.)
        client_kwargs = {"api_key": api_key, "timeout": timeout}
        if base_url:
            client_kwargs["base_url"] = base_url
            log(f"[OpenAI] Using custom base_url: {base_url}")
        client = OpenAI(**client_kwargs)

        # Build messages
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt}
        ]

        # Build tool config if needed
        tools = None
        if use_tools:
            mcp_filter = agent_config.get("allowed_mcp")
            allowed_tools = agent_config.get("allowed_tools")
            blocked_tools = agent_config.get("blocked_tools")
            tool_mode = agent_config.get("tool_mode", "full")
            if mcp_filter:
                log(f"[OpenAI] MCP filter: {mcp_filter}")
                # Set MCP filter in TaskContext for execute_tool() to use
                # (important for hallucinated tool names that need auto-correction)
                tool_bridge.set_mcp_filter(mcp_filter)
            if allowed_tools:
                log(f"[OpenAI] Allowed tools (whitelist): {allowed_tools}")
            if blocked_tools:
                log(f"[OpenAI] Blocked tools (blacklist): {blocked_tools}")
            if tool_mode != "full":
                log(f"[OpenAI] Tool mode: {tool_mode}")

            # Set anonymization context for tool input de-anonymization
            if anon_context is not None:
                tool_bridge.set_anonymization_context(anon_context)

            tools = _get_tools(mcp_filter, allowed_tools, blocked_tools, tool_mode)
            if not tools:
                tools = None  # OpenAI doesn't accept empty list

        # Write complete prompt to log file (overwritten each time)
        write_prompt_log(system_message, prompt, agent_name="openai", model=model, tools=tools)

        # Detect Mistral API (disable parallel tool calls to fix JSON corruption bug)
        is_mistral = base_url and "mistral" in base_url.lower()
        if is_mistral and use_tools:
            log(f"[OpenAI] Mistral detected - disabling parallel tool calls")

        # Check for cancellation before API call
        if is_cancelled and is_cancelled():
            log("[OpenAI] Task cancelled before API call")
            return AgentResponse(
                success=False,
                content="",
                error="Task cancelled"
            )

        # Make streaming API call
        log(f"[OpenAI] Calling API...")
        stream = _call_with_retry(
            client, messages, model,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            parallel_tool_calls=not is_mistral  # Disable for Mistral
        )

        # Process streaming response
        full_response = ""
        tool_calls = []
        current_tool_call = None
        last_finish_reason = None

        for chunk in stream:
            # Check for cancellation during streaming
            if is_cancelled and is_cancelled():
                log("[OpenAI] Task cancelled during streaming")
                return AgentResponse(
                    success=False,
                    content=full_response if full_response else "",
                    error="Task cancelled"
                )

            if not chunk.choices:
                continue

            # Track finish_reason
            if chunk.choices[0].finish_reason:
                last_finish_reason = chunk.choices[0].finish_reason

            delta = chunk.choices[0].delta

            # Handle text content
            if delta.content:
                # Mistral returns content as list, others as string
                content_chunk = delta.content if isinstance(delta.content, str) else "".join(delta.content)
                full_response += content_chunk
                if on_chunk:
                    try:
                        mappings = anon_context.mappings if anon_context else None
                        on_chunk(content_chunk, False, full_response, mappings)
                    except Exception as e:
                        log(f"[OpenAI] Callback error: {e}")

            # Handle tool calls (streaming format)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    if tc.index is not None:
                        # Ensure we have a slot for this tool call
                        while len(tool_calls) <= tc.index:
                            tool_calls.append({
                                "id": "",
                                "name": "",
                                "arguments": ""
                            })

                        if tc.id:
                            tool_calls[tc.index]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls[tc.index]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls[tc.index]["arguments"] += tc.function.arguments

        log(f"[OpenAI] API response received (finish_reason={last_finish_reason})")

        # Check for cancellation after streaming
        if is_cancelled and is_cancelled():
            log("[OpenAI] Task cancelled after API call")
            return AgentResponse(
                success=False,
                content=full_response if full_response else "",
                error="Task cancelled"
            )

        # Handle tool calls if present
        if tool_calls and any(tc["name"] for tc in tool_calls):
            log(f"[OpenAI] {len(tool_calls)} tool call(s) requested")

            # Execute all tools and collect results
            tool_results = []
            for tc in tool_calls:
                if not tc["name"]:
                    continue

                tool_name = tc["name"]
                tool_id = tc["id"]

                # Parse arguments
                try:
                    tool_args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    log(f"[OpenAI] Failed to parse tool arguments: {tc['arguments']}")
                    tool_args = {}

                log(f"[OpenAI] Tool: {tool_name}")
                log(f"[OpenAI] Args: {tool_args}")

                # Add tool marker to response for UI badge display
                tool_msg = f"\n[Tool: {tool_name} ⏳]\n"
                full_response += tool_msg
                if on_chunk:
                    try:
                        mappings = anon_context.mappings if anon_context else None
                        on_chunk(tool_msg, True, full_response, mappings)
                    except Exception as e:
                        log(f"[OpenAI] Callback error: {e}")

                # Execute tool with timing
                tool_start = time.time()
                result = tool_bridge.execute_tool(tool_name, tool_args)
                tool_duration = time.time() - tool_start

                result_tokens = estimate_tokens(result)
                token_breakdown["tools"] += result_tokens  # Track for UI display
                log(f"[OpenAI] Result: {len(result)} chars (+{format_tokens(result_tokens)} tokens) in {tool_duration:.1f}s")

                # Update tool marker with timing
                full_response = full_response.replace(
                    f"[Tool: {tool_name} ⏳]",
                    f"[Tool: {tool_name} | {tool_duration:.1f}s]"
                )
                if on_chunk:
                    try:
                        mappings = anon_context.mappings if anon_context else None
                        on_chunk("", False, full_response, mappings)
                    except Exception:
                        pass

                # Anonymize tool result if context provided
                anon_count = 0
                if anon_context is not None:
                    old_count = len(anon_context.mappings)
                    result, anon_context = anonymizer.anonymize_with_context(
                        result, config, anon_context
                    )
                    anon_count = len(anon_context.mappings) - old_count
                    if anon_count > 0:
                        log(f"[OpenAI] Tool result anonymized")

                # Log anonymized result (what goes to AI over internet)
                log_tool_call(tool_name, "RESULT", result)

                # Capture for Developer Mode (with anon count and args)
                add_dev_tool_result(tool_name, result, anon_count, args=tool_args)

                tool_results.append({
                    "id": tool_id,
                    "name": tool_name,
                    "args": tool_args,
                    "result": result
                })

            # Continue with tool results
            continuation_response, anon_context = _continue_with_tool_results(
                client, model, max_tokens, temperature,
                messages, tool_calls, tool_results,
                on_chunk, tools,
                anon_context=anon_context, config=config,
                max_iterations=max_iterations,
                is_cancelled=is_cancelled,
                initial_response=full_response,
                token_breakdown=token_breakdown,
                parallel_tool_calls=not is_mistral  # Disable for Mistral
            )
            full_response = continuation_response or full_response

        duration = time.time() - start_time

        # Calculate cost (estimate based on response length since streaming doesn't give usage)
        pricing = agent_config.get("pricing", {"input": 2.5, "output": 10})
        estimated_input = initial_total
        estimated_output = estimate_tokens(full_response)
        cost_usd = (estimated_input * pricing["input"] / 1_000_000) + \
                   (estimated_output * pricing["output"] / 1_000_000)

        log(f"[OpenAI] Cost: ${cost_usd:.4f} (estimated)")
        log(f"[OpenAI] Duration: {duration:.1f}s")
        log(f"[OpenAI] === RESPONSE ===")
        log(full_response[:500] + "..." if len(full_response) > 500 else full_response)
        log(f"[OpenAI] ================")

        if not full_response.strip():
            return AgentResponse(
                success=False,
                content="",
                error="Empty response from OpenAI API"
            )

        # Clean response (remove tool markers for final output)
        clean_response = _clean_response(full_response)

        return AgentResponse(
            success=True,
            content=clean_response,
            raw_output=full_response,
            model=model,
            input_tokens=estimated_input,
            output_tokens=estimated_output,
            cost_usd=cost_usd,
            anonymization=dict(anon_context.mappings) if anon_context and anon_context.mappings else None
        )

    except Exception as e:
        log(f"[OpenAI] Error: {e}")
        import traceback
        log(f"[OpenAI] Traceback: {traceback.format_exc()}")
        return AgentResponse(
            success=False,
            content="",
            error=str(e)
        )


def _clean_response(response: str) -> str:
    """Clean up response by removing tool markers."""
    import re

    lines = response.split('\n')
    clean_lines = []

    for line in lines:
        # Skip tool markers (e.g. "[Tool: get_file_info | 0.0s]")
        if re.match(r'^\s*\[Tool:\s*\S+.*\]\s*$', line):
            continue
        clean_lines.append(line)

    # Remove multiple consecutive empty lines
    result = '\n'.join(clean_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


def _continue_with_tool_results(
    client,
    model: str,
    max_tokens: int,
    temperature: float,
    messages: list,
    tool_calls: list,
    tool_results: list,
    on_chunk: callable,
    tools: list = None,
    anon_context: "anonymizer.AnonymizationContext" = None,
    config: dict = None,
    max_iterations: int = 30,
    is_cancelled: callable = None,
    initial_response: str = "",
    token_breakdown: dict = None,
    parallel_tool_calls: bool = True
) -> tuple:
    """
    Continue conversation with tool results.

    Sends tool results back to the model and handles any additional tool calls
    until the model provides a final text response.

    Returns:
        tuple: (response_text, anon_context)
    """
    log(f"[OpenAI] Continuing with {len(tool_results)} tool result(s)")

    # Build assistant message with tool calls
    assistant_tool_calls = []
    for tc in tool_calls:
        if tc["name"]:
            assistant_tool_calls.append({
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"]
                }
            })

    # Add assistant message with tool calls
    messages.append({
        "role": "assistant",
        "tool_calls": assistant_tool_calls
    })

    # Add tool results
    for tr in tool_results:
        messages.append({
            "role": "tool",
            "tool_call_id": tr["id"],
            "content": tr["result"]
        })

    # Tool calling loop
    iteration = 0
    nudge_retries = 0
    max_nudge_retries = 2
    accumulated_response = initial_response if initial_response else ""

    while iteration < max_iterations:
        # Check for cancellation at start of each iteration
        if is_cancelled and is_cancelled():
            log("[OpenAI] Task cancelled during tool loop")
            if accumulated_response.strip():
                return accumulated_response + "\n\n[Task cancelled]", anon_context
            return "[Task cancelled]", anon_context

        iteration += 1
        update_dev_iteration(iteration, max_iterations)
        if token_breakdown:
            publish_context_event(
                iteration=iteration, max_iterations=max_iterations,
                system_tokens=token_breakdown["system"],
                prompt_tokens=token_breakdown["prompt"],
                tool_tokens=token_breakdown["tools"]
            )
        log(f"[OpenAI] Calling continuation API (iteration {iteration})...")

        # Make API call
        stream = _call_with_retry(
            client, messages, model,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            parallel_tool_calls=parallel_tool_calls
        )

        # Process streaming response
        iteration_response = ""
        new_tool_calls = []
        last_finish_reason = None

        for chunk in stream:
            if is_cancelled and is_cancelled():
                log("[OpenAI] Task cancelled during continuation streaming")
                if accumulated_response.strip():
                    return accumulated_response + "\n\n[Task cancelled]", anon_context
                return "[Task cancelled]", anon_context

            if not chunk.choices:
                continue

            # Track finish_reason
            if chunk.choices[0].finish_reason:
                last_finish_reason = chunk.choices[0].finish_reason

            delta = chunk.choices[0].delta

            # Handle text content
            if delta.content:
                iteration_response += delta.content
                accumulated_response += delta.content
                if on_chunk:
                    try:
                        mappings = anon_context.mappings if anon_context else None
                        on_chunk(delta.content, False, accumulated_response, mappings)
                    except Exception:
                        pass

            # Handle tool calls
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    if tc.index is not None:
                        while len(new_tool_calls) <= tc.index:
                            new_tool_calls.append({
                                "id": "",
                                "name": "",
                                "arguments": ""
                            })

                        if tc.id:
                            new_tool_calls[tc.index]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                new_tool_calls[tc.index]["name"] = tc.function.name
                            if tc.function.arguments:
                                new_tool_calls[tc.index]["arguments"] += tc.function.arguments

        log(f"[OpenAI] Continuation response received (finish_reason={last_finish_reason})")

        # If we got text and no new tool calls, we're done
        if iteration_response.strip() and not any(tc["name"] for tc in new_tool_calls):
            log(f"[OpenAI] Final response: {len(accumulated_response)} chars")
            return accumulated_response, anon_context

        # If we got new tool calls, execute them
        if new_tool_calls and any(tc["name"] for tc in new_tool_calls):
            log(f"[OpenAI] Model requested {len([tc for tc in new_tool_calls if tc['name']])} more tool call(s)")

            # Execute all tool calls
            new_tool_results = []
            for tc in new_tool_calls:
                if not tc["name"]:
                    continue

                tool_name = tc["name"]
                tool_id = tc["id"]

                try:
                    tool_args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    tool_args = {}

                log(f"[OpenAI] Tool: {tool_name}")
                log(f"[OpenAI] Args: {tool_args}")

                # Add tool marker
                tool_msg = f"\n[Tool: {tool_name} ⏳]\n"
                accumulated_response += tool_msg
                if on_chunk:
                    try:
                        mappings = anon_context.mappings if anon_context else None
                        on_chunk(tool_msg, True, accumulated_response, mappings)
                    except Exception:
                        pass

                # Execute tool
                tool_start = time.time()
                result = tool_bridge.execute_tool(tool_name, tool_args)
                tool_duration = time.time() - tool_start

                result_tokens = estimate_tokens(result)
                if token_breakdown:
                    token_breakdown["tools"] += result_tokens  # Track for UI display
                log(f"[OpenAI] Result: {len(result)} chars (+{format_tokens(result_tokens)} tokens) in {tool_duration:.1f}s")

                # Update tool marker
                accumulated_response = accumulated_response.replace(
                    f"[Tool: {tool_name} ⏳]",
                    f"[Tool: {tool_name} | {tool_duration:.1f}s]"
                )
                if on_chunk:
                    try:
                        mappings = anon_context.mappings if anon_context else None
                        on_chunk("", False, accumulated_response, mappings)
                    except Exception:
                        pass

                # Anonymize if needed
                anon_count = 0
                if anon_context is not None and config is not None:
                    old_count = len(anon_context.mappings)
                    result, anon_context = anonymizer.anonymize_with_context(
                        result, config, anon_context
                    )
                    anon_count = len(anon_context.mappings) - old_count
                    if anon_count > 0:
                        log(f"[OpenAI] Tool result anonymized")

                # Log anonymized result (what goes to AI over internet)
                log_tool_call(tool_name, "RESULT", result)

                # Capture for Developer Mode (with anon count and args)
                add_dev_tool_result(tool_name, result, anon_count, args=tool_args)

                new_tool_results.append({
                    "id": tool_id,
                    "name": tool_name,
                    "args": tool_args,
                    "result": result
                })

            # Build assistant message with new tool calls
            assistant_tool_calls = []
            for tc in new_tool_calls:
                if tc["name"]:
                    assistant_tool_calls.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"]
                        }
                    })

            messages.append({
                "role": "assistant",
                "tool_calls": assistant_tool_calls
            })

            # Add tool results
            for tr in new_tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tr["id"],
                    "content": tr["result"]
                })

            # Continue loop
            continue

        # GPT-5 / reasoning models: empty response after tool calls
        # Nudge the model to produce text output (with retry counter to prevent infinite loops)
        if nudge_retries >= max_nudge_retries:
            log(f"[OpenAI] Empty response after {nudge_retries} nudge retries, giving up")
            break

        nudge_retries += 1
        log(f"[OpenAI] Empty response after tool calls (finish_reason={last_finish_reason}), nudging model ({nudge_retries}/{max_nudge_retries})...")
        messages.append({
            "role": "user",
            "content": "Please provide your analysis and summary based on the tool results above. Respond in the same language as the original request."
        })
        # Temporarily disable tools to force text output
        tools = None
        continue

    # Check if we hit max iterations
    if iteration >= max_iterations:
        log(f"[OpenAI] Max iterations ({max_iterations}) reached")
        iteration_warning = (
            f"\n\n---\n"
            f"**Agent stopped after {max_iterations} tool calls**\n\n"
            f"The agent was still working but hit the iteration limit.\n"
            f"You can increase `max_iterations` in the agent config."
        )
        return accumulated_response + iteration_warning, anon_context

    return accumulated_response if accumulated_response.strip() else "[No response from model]", anon_context
