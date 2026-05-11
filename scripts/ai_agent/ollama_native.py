# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Ollama Native Agent
===================
Direct Ollama API with streaming and tool support.
Provides real-time token streaming for thinking display.

Uses tool_bridge for dynamic MCP tool discovery - new MCP tools
are automatically available without code changes.
"""

import json
import requests
import sys
from pathlib import Path
from paths import PROJECT_DIR
from .agent_logging import AgentResponse, write_prompt_log
from .logging import log
from .prompt_builder import build_system_prompt
from . import tool_bridge

# Add project root to path for MCP imports
sys.path.insert(0, str(PROJECT_DIR))


def check_configured(config: dict) -> tuple:
    """
    Check if this backend is properly configured (Ollama running).

    Args:
        config: Backend configuration dict

    Returns:
        Tuple of (is_configured: bool, issue: str or None)
    """
    # Check if Ollama is reachable
    base_url = config.get("base_url", "http://localhost:11434")
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=2)
        if response.status_code == 200:
            return True, None
        return False, f"Ollama returned status {response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Ollama not running"
    except requests.exceptions.Timeout:
        return False, "Ollama timeout"
    except Exception as e:
        return False, f"Ollama error: {str(e)}"


def _get_tools(mcp_filter: str = None, allowed_tools: list = None, blocked_tools: list = None, tool_mode: str = None) -> list:
    """Get tools from dynamic MCP bridge.

    Args:
        mcp_filter: Optional regex pattern to filter MCP servers (e.g., "outlook|billomat")
        allowed_tools: Optional whitelist of tool names (only these tools will be available)
        blocked_tools: Optional blacklist of tool names (e.g., ["delete_email"])
        tool_mode: Optional security mode ("full", "read_only", "write_safe")
    """
    tools = tool_bridge.get_ollama_tools(mcp_filter, allowed_tools, blocked_tools, tool_mode)
    log(f"[Ollama Native] Loaded {len(tools)} tools from bridge" +
        (f" (filter: {mcp_filter})" if mcp_filter else ""))
    return tools


class CancelledException(Exception):
    """Raised when task is cancelled by user."""
    pass


def call_ollama_native(
    prompt: str,
    config: dict,
    agent_config: dict,
    use_tools: bool = False,
    on_chunk: callable = None,
    is_cancelled: callable = None
) -> AgentResponse:
    """
    Call Ollama API with streaming and optional tool support.

    Args:
        prompt: The prompt for the model
        config: Main configuration
        agent_config: Agent-specific configuration
        use_tools: If True, enable tool calling
        on_chunk: Optional callback for streaming updates
                  Signature: on_chunk(token, is_thinking, full_response)
        is_cancelled: Optional callback to check if task was cancelled
    """
    model = agent_config.get("model", "qwen3:30b")
    base_url = agent_config.get("base_url", "http://localhost:11434")
    timeout = agent_config.get("timeout", 180)
    thinking_mode = agent_config.get("thinking_mode", True)

    # Build system message (base prompt + security warning + templates + knowledge)
    system_message = build_system_prompt(agent_config, config=config)

    # Build messages
    # Note: Disable thinking mode when tools are enabled - otherwise model
    # spends all time reasoning about tools instead of actually calling them
    use_thinking = thinking_mode and not use_tools
    user_content = f"/think\n{prompt}" if use_thinking else prompt
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_content}
    ]

    # Log context
    log(f"[Ollama Native] === Context Summary ===")
    log(f"[Ollama Native]   Model: {model}")
    log(f"[Ollama Native]   Base URL: {base_url}")
    log(f"[Ollama Native]   Tools enabled: {use_tools}")
    log(f"[Ollama Native]   Thinking mode: {use_thinking} (config: {thinking_mode}, disabled for tools: {use_tools})")
    log(f"[Ollama Native]   System message: {len(system_message)} chars")
    log(f"[Ollama Native]   Prompt: {len(prompt)} chars")
    log(f"[Ollama Native] ===========================")

    try:
        # Build request payload
        payload = {
            "model": model,
            "messages": messages,
            "stream": True
        }

        ollama_tools = None
        if use_tools:
            # Get MCP filter pattern from agent config
            mcp_filter = agent_config.get("allowed_mcp")
            allowed_tools = agent_config.get("allowed_tools")
            blocked_tools = agent_config.get("blocked_tools")
            tool_mode = agent_config.get("tool_mode", "full")
            if mcp_filter:
                log(f"[Ollama Native] MCP filter: {mcp_filter}")
                # Set MCP filter in TaskContext for execute_tool() to use
                # (important for hallucinated tool names that need auto-correction)
                tool_bridge.set_mcp_filter(mcp_filter)
            if allowed_tools:
                log(f"[Ollama Native] Allowed tools (whitelist): {allowed_tools}")
            if blocked_tools:
                log(f"[Ollama Native] Blocked tools (blacklist): {blocked_tools}")
            if tool_mode != "full":
                log(f"[Ollama Native] Tool mode: {tool_mode}")
            ollama_tools = _get_tools(mcp_filter, allowed_tools, blocked_tools, tool_mode)
            payload["tools"] = ollama_tools

        # Write complete prompt to log file (overwritten each time)
        write_prompt_log(system_message, prompt, agent_name="ollama", model=model, tools=ollama_tools)

        # Make streaming request
        response = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            stream=True,
            timeout=timeout
        )
        response.raise_for_status()

        full_response = ""
        in_thinking = False
        pending_tool_calls = []

        # Check for cancellation before starting stream processing
        if is_cancelled and is_cancelled():
            log("[Ollama Native] Cancelled before stream processing")
            return AgentResponse(
                success=False,
                content=full_response,
                error="Task cancelled",
                cancelled=True
            )

        # Process stream
        for line in response.iter_lines():
            # Check for cancellation during streaming (check every chunk)
            if is_cancelled and is_cancelled():
                log("[Ollama Native] Cancelled during streaming")
                return AgentResponse(
                    success=False,
                    content=full_response,  # Return accumulated content
                    error="Task cancelled",
                    cancelled=True
                )

            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Check for tool calls
            message = data.get("message", {})
            if "tool_calls" in message:
                pending_tool_calls.extend(message["tool_calls"])
                log(f"[Ollama Native] Tool calls received: {len(pending_tool_calls)}")
                continue

            # Get content token
            content = message.get("content", "")
            if content:
                full_response += content

                # Track thinking state
                if "<think>" in content:
                    in_thinking = True
                elif "</think>" in content:
                    in_thinking = False

                # Call streaming callback if provided
                if on_chunk:
                    try:
                        on_chunk(content, in_thinking, full_response)
                    except Exception as e:
                        log(f"[Ollama Native] Callback error: {e}")

        # Check for text-based tool calls (Mistral format)
        if use_tools and not pending_tool_calls:
            parsed_calls = _parse_text_tool_calls(full_response)
            if parsed_calls:
                pending_tool_calls = parsed_calls
                log(f"[Ollama Native] Parsed {len(parsed_calls)} text-based tool calls")

        # Execute tool calls if any
        if pending_tool_calls:
            # Check for cancellation before tool execution
            if is_cancelled and is_cancelled():
                log("[Ollama Native] Cancelled before tool execution")
                return AgentResponse(
                    success=False,
                    content=full_response,
                    error="Task cancelled",
                    cancelled=True
                )

            log(f"[Ollama Native] Executing {len(pending_tool_calls)} tool calls")
            full_response, was_cancelled = _handle_tool_calls(
                model, base_url, messages, full_response,
                pending_tool_calls, on_chunk, timeout, use_tools, mcp_filter,
                is_cancelled=is_cancelled
            )

            if was_cancelled:
                return AgentResponse(
                    success=False,
                    content=full_response,
                    error="Task cancelled",
                    cancelled=True
                )

        # Log raw response
        log(f"[Ollama Native] === RAW RESPONSE ===")
        log(full_response[:500] + "..." if len(full_response) > 500 else full_response)
        log(f"[Ollama Native] ====================")

        if not full_response.strip():
            return AgentResponse(
                success=False,
                content="",
                error="Empty response from Ollama"
            )

        # Parse thinking from response
        thinking, answer = _parse_thinking(full_response)

        # Format with thinking block for UI
        if thinking:
            formatted = f"""<details class="thinking-block">
<summary>🧠 Thinking Process</summary>

{thinking}

</details>

---

{answer}"""
        else:
            formatted = answer

        return AgentResponse(
            success=True,
            content=formatted,
            raw_output=full_response
        )

    except requests.exceptions.Timeout:
        return AgentResponse(
            success=False,
            content="",
            error=f"Timeout after {timeout}s"
        )
    except requests.exceptions.ConnectionError as e:
        return AgentResponse(
            success=False,
            content="",
            error=f"Connection error: {e}. Is Ollama running at {base_url}?"
        )
    except Exception as e:
        log(f"[Ollama Native] Error: {e}")
        return AgentResponse(
            success=False,
            content="",
            error=str(e)
        )


def _handle_tool_calls(
    model: str,
    base_url: str,
    messages: list,
    response_so_far: str,
    tool_calls: list,
    on_chunk: callable,
    timeout: int,
    use_tools: bool,
    mcp_filter: str = None,
    is_cancelled: callable = None
) -> tuple:
    """Execute tool calls and continue conversation.

    Returns:
        tuple: (response_content, was_cancelled)
    """
    log(f"[Ollama Native] === TOOL HANDLING START ===")
    log(f"[Ollama Native] Tool calls to process: {len(tool_calls)}")

    # Add assistant message with tool calls
    messages.append({
        "role": "assistant",
        "content": response_so_far,
        "tool_calls": tool_calls
    })

    # Execute each tool and add results
    for call in tool_calls:
        # Check for cancellation before each tool
        if is_cancelled and is_cancelled():
            log("[Ollama Native] Cancelled during tool execution")
            return response_so_far, True  # Return with cancelled flag

        func = call.get("function", {})
        name = func.get("name", "")
        args_str = func.get("arguments", "{}")

        log(f"[Ollama Native] Executing tool: {name}")
        log(f"[Ollama Native] Args: {args_str}")

        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            args = {}

        result = tool_bridge.execute_tool(name, args)
        log(f"[Ollama Native] Tool result length: {len(result)} chars")
        log(f"[Ollama Native] Tool result preview: {result[:300]}...")

        messages.append({
            "role": "tool",
            "content": result
        })

    # Continue conversation with tool results
    log(f"[Ollama Native] === CONTINUATION REQUEST ===")
    payload = {
        "model": model,
        "messages": messages,
        "stream": True
    }
    if use_tools:
        payload["tools"] = _get_tools(mcp_filter)

    log(f"[Ollama Native] Messages count: {len(messages)}")
    log(f"[Ollama Native] Last message role: {messages[-1].get('role')}")

    try:
        response = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            stream=True,
            timeout=timeout
        )
        log(f"[Ollama Native] Continuation response status: {response.status_code}")
        response.raise_for_status()

        continuation = ""
        in_thinking = False
        chunk_count = 0

        for line in response.iter_lines():
            # Check for cancellation during continuation streaming
            if is_cancelled and is_cancelled():
                log("[Ollama Native] Cancelled during continuation streaming")
                return response_so_far + "\n\n" + continuation, True

            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            chunk_count += 1
            content = data.get("message", {}).get("content", "")
            if content:
                continuation += content

                if "<think>" in content:
                    in_thinking = True
                elif "</think>" in content:
                    in_thinking = False

                if on_chunk:
                    try:
                        on_chunk(content, in_thinking, response_so_far + continuation)
                    except Exception:
                        pass

        log(f"[Ollama Native] Continuation chunks: {chunk_count}")
        log(f"[Ollama Native] Continuation length: {len(continuation)} chars")

        # Check for additional text-based tool calls in continuation
        if use_tools:
            more_calls = _parse_text_tool_calls(continuation)
            if more_calls:
                # Check for cancellation before recursive tool handling
                if is_cancelled and is_cancelled():
                    log("[Ollama Native] Cancelled before recursive tool handling")
                    return response_so_far + "\n\n" + continuation, True

                log(f"[Ollama Native] Found {len(more_calls)} more tool calls in continuation")
                # Recursively handle
                return _handle_tool_calls(
                    model, base_url, messages, response_so_far + "\n\n" + continuation,
                    more_calls, on_chunk, timeout, use_tools, mcp_filter,
                    is_cancelled=is_cancelled
                )

        log(f"[Ollama Native] === TOOL HANDLING END ===")

        return response_so_far + "\n\n" + continuation, False  # Not cancelled

    except Exception as e:
        log(f"[Ollama Native] Continuation error: {e}")
        return response_so_far + f"\n\nError continuing after tool calls: {e}", False


def _parse_text_tool_calls(response: str) -> list:
    """Parse text-based tool calls from models like Mistral.

    Handles formats like:
    [TOOL_CALLS] Calls:
      - FunctionCall:
          name: get_selected_email
          arguments: {}

    Or: CALL get_selected_email
    Or: create_reply_draft with body="..."
    """
    import re

    tool_calls = []

    # Pattern 1: [TOOL_CALLS] format
    if "[TOOL_CALLS]" in response:
        # Extract function name
        name_match = re.search(r'name:\s*(\w+)', response)
        args_match = re.search(r'arguments:\s*(\{[^}]*\})', response)

        if name_match:
            name = name_match.group(1)
            args = args_match.group(1) if args_match else "{}"
            tool_calls.append({
                "function": {
                    "name": name,
                    "arguments": args
                }
            })
            log(f"[Ollama Native] Parsed [TOOL_CALLS] format: {name}")

    # Pattern 2: "CALL tool_name" format
    call_match = re.search(r'CALL\s+(\w+)', response, re.IGNORECASE)
    if call_match and not tool_calls:
        name = call_match.group(1)
        tool_calls.append({
            "function": {
                "name": name,
                "arguments": "{}"
            }
        })
        log(f"[Ollama Native] Parsed CALL format: {name}")

    # Pattern 3: "create_reply_draft" with body in response
    if "create_reply_draft" in response.lower() and not tool_calls:
        # Try to extract body content
        body_match = re.search(r'body[=:]\s*["\'](.+?)["\']', response, re.DOTALL)
        if body_match:
            body = body_match.group(1)
            tool_calls.append({
                "function": {
                    "name": "create_reply_draft",
                    "arguments": json.dumps({"body": body})
                }
            })
            log(f"[Ollama Native] Parsed create_reply_draft with body")

    return tool_calls


def _parse_thinking(response: str) -> tuple:
    """Parse thinking blocks from response."""
    import re

    thinking = ""
    answer = response

    # Method 1: Standard <think>...</think>
    match = re.search(r'<think>(.*?)</think>', response, re.DOTALL)
    if match:
        thinking = match.group(1).strip()
        answer = re.sub(r'<think>.*?</think>\s*', '', response, flags=re.DOTALL).strip()
        return thinking, answer

    # Method 2: Handle </think> without opening tag
    if '</think>' in response:
        parts = response.split('</think>', 1)
        if len(parts) == 2:
            thinking = parts[0].replace('<think>', '').strip()
            answer = parts[1].strip()
            if answer and len(answer) > 50:
                return thinking, answer

    return thinking, answer
