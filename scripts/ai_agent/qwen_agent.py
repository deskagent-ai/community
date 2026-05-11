# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Qwen Agent
==========
Uses Qwen-Agent framework with MCP tool support for AI tasks.
Runs locally via Ollama with full function calling capabilities.

Supports Qwen3 Thinking Mode - reasoning is shown in <think>...</think> blocks.

Requires: pip install qwen-agent[mcp]
"""

import json
import re
from paths import PROJECT_DIR
from .agent_logging import AgentResponse, write_prompt_log
from .logging import log
from .prompt_builder import build_system_prompt

# Lazy import to avoid dependency issues if not installed
_qwen_agent_available = None


def check_configured(config: dict) -> tuple:
    """
    Check if this backend is properly configured (Ollama running, package installed).

    Args:
        config: Backend configuration dict

    Returns:
        Tuple of (is_configured: bool, issue: str or None)
    """
    import requests

    # Check if qwen-agent package is installed
    if not _check_qwen_agent():
        return False, "qwen-agent package not installed"

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


def _check_qwen_agent():
    """Check if qwen-agent is available."""
    global _qwen_agent_available
    if _qwen_agent_available is None:
        try:
            from qwen_agent.agents import Assistant
            _qwen_agent_available = True
        except ImportError:
            _qwen_agent_available = False
    return _qwen_agent_available


def _load_mcp_config() -> dict:
    """Load MCP server configuration from .mcp.json."""
    mcp_file = PROJECT_DIR / ".mcp.json"
    if mcp_file.exists():
        try:
            config = json.loads(mcp_file.read_text(encoding="utf-8"))
            return config.get("mcpServers", {})
        except Exception as e:
            log(f"[Qwen Agent] Error loading MCP config: {e}")
    return {}


def _parse_thinking(response: str) -> tuple[str, str]:
    """
    Parse Qwen3 thinking blocks from response.

    Args:
        response: Raw response possibly containing <think>...</think> blocks
        or inline thinking patterns like "Okay, let's see..."

    Returns:
        Tuple of (thinking_content, final_answer)
    """
    thinking = ""
    answer = response

    # Method 1: Find <think>...</think> block (standard format)
    match = re.search(r'<think>(.*?)</think>', response, re.DOTALL)
    if match:
        thinking = match.group(1).strip()
        answer = re.sub(r'<think>.*?</think>\s*', '', response, flags=re.DOTALL).strip()
        return thinking, answer

    # Method 2: Find </think> even if <think> is missing (Qwen sometimes omits opening tag)
    if '</think>' in response:
        parts = response.split('</think>', 1)
        if len(parts) == 2:
            # Remove <think> if present at start
            thinking = parts[0].replace('<think>', '').strip()
            answer = parts[1].strip()
            if answer and len(answer) > 50:
                return thinking, answer

    # Method 3: Detect answer start patterns (markdown headers, greetings, bold text)
    answer_patterns = [
        r'\n\s*\*\*[A-ZÄÖÜ]',           # **Bold heading (e.g., **Preise)
        r'\n\s*#{1,3}\s+[A-ZÄÖÜ]',      # # Markdown heading
        r'\n\s*(Dear |Sehr geehrte|Hallo |Hello |Hi |Liebe )',  # Greetings
    ]

    for pattern in answer_patterns:
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            before = response[:match.start()].strip()
            thinking_starters = ('okay', 'alright', 'let me', 'so,', 'hmm', 'i need',
                                 'the user', 'this', 'first', 'looking', 'now,', 'wait')
            if before.lower().startswith(thinking_starters):
                thinking = before
                answer = response[match.start():].strip()
                if answer and len(answer) > 50:
                    return thinking, answer

    return thinking, answer


def call_qwen_agent(
    prompt: str,
    config: dict,
    agent_config: dict,
    use_tools: bool = False
) -> AgentResponse:
    """
    Calls Qwen-Agent with optional MCP tool access.

    Args:
        prompt: The prompt/task for the agent
        config: Main configuration
        agent_config: Agent-specific configuration (model, base_url, etc.)
        use_tools: If True, enable MCP tools
    """
    if not _check_qwen_agent():
        return AgentResponse(
            success=False,
            content="",
            error="qwen-agent not installed. Install with: pip install qwen-agent[mcp]"
        )

    from qwen_agent.agents import Assistant

    # LLM configuration for Ollama
    model = agent_config.get("model", "qwen2.5:32b")
    base_url = agent_config.get("base_url", "http://localhost:11434")
    timeout = agent_config.get("timeout", 180)
    thinking_mode = agent_config.get("thinking_mode", True)  # Enable Qwen3 thinking by default

    # Ollama uses OpenAI-compatible API at /v1
    model_server = base_url.rstrip("/")
    if not model_server.endswith("/v1"):
        model_server += "/v1"

    llm_cfg = {
        "model": model,
        "model_server": model_server,
        "api_key": "EMPTY",
        "generate_cfg": {
            "timeout": timeout
        }
    }

    log(f"[Qwen Agent] Model: {model}")
    log(f"[Qwen Agent] Server: {model_server}")
    log(f"[Qwen Agent] Timeout: {timeout}s")
    log(f"[Qwen Agent] Tools enabled: {use_tools}")
    log(f"[Qwen Agent] Prompt length: {len(prompt)}")

    # Build tools list
    tools = []
    mcp_server_names = []
    if use_tools:
        mcp_servers = _load_mcp_config()
        if mcp_servers:
            tools.append({"mcpServers": mcp_servers})
            mcp_server_names = list(mcp_servers.keys())
            log(f"[Qwen Agent] MCP servers: {mcp_server_names}")
        else:
            log("[Qwen Agent] Warning: No MCP servers configured")

    # Build system message (base prompt + security warning + templates + knowledge)
    system_message = build_system_prompt(agent_config, config=config)

    # Log context sizes
    log(f"[Qwen Agent] === Context Summary ===")
    log(f"[Qwen Agent]   System message total: {len(system_message)} chars")
    log(f"[Qwen Agent]   User prompt: {len(prompt)} chars")
    log(f"[Qwen Agent] =========================")

    # Write complete prompt to log file (overwritten each time)
    mcp_tool_list = [{"name": f"MCP:{name}"} for name in sorted(mcp_server_names)]
    write_prompt_log(system_message, prompt, agent_name="qwen", model=model, tools=mcp_tool_list)

    try:
        # Create agent
        log(f"[Qwen Agent] Creating Assistant with tools: {tools}")
        bot = Assistant(
            llm=llm_cfg,
            function_list=tools if tools else None,
            system_message=system_message
        )

        # Debug: Check what tools were registered
        if hasattr(bot, 'function_map'):
            log(f"[Qwen Agent] Registered functions: {list(bot.function_map.keys())}")
        else:
            log("[Qwen Agent] No function_map attribute found")

        # Run agent - optionally prepend /think to enable Qwen3 thinking mode
        # This outputs thinking in <think>...</think> blocks
        if thinking_mode:
            thinking_prompt = f"/think\n{prompt}"
            log("[Qwen Agent] Thinking mode: enabled")
        else:
            thinking_prompt = f"/no_think\n{prompt}"
            log("[Qwen Agent] Thinking mode: disabled")
        messages = [{"role": "user", "content": thinking_prompt}]
        response_text = ""

        log("[Qwen Agent] Running...")

        # Collect streaming response and log intermediate results
        all_responses = []
        for responses in bot.run(messages=messages):
            all_responses = responses
            # Log each step
            if responses:
                last = responses[-1]
                if isinstance(last, dict):
                    role = last.get("role", "unknown")
                    fn_call = last.get("function_call")
                    if fn_call:
                        log(f"[Qwen Agent] Tool call: {fn_call}")
                    elif role == "function":
                        log(f"[Qwen Agent] Tool result received")

        responses = all_responses

        # Get final response
        if responses:
            last_response = responses[-1]
            if isinstance(last_response, dict):
                response_text = last_response.get("content", "")
            else:
                response_text = str(last_response)

        log(f"[Qwen Agent] Response length: {len(response_text)}")

        # Debug: Log full raw response
        log(f"[Qwen Agent] === RAW RESPONSE START ===")
        log(response_text)
        log(f"[Qwen Agent] === RAW RESPONSE END ===")

        if not response_text or not response_text.strip():
            return AgentResponse(
                success=False,
                content="",
                error="Empty response from Qwen Agent"
            )

        # Parse thinking blocks (Qwen3 Thinking Mode)
        thinking, answer = _parse_thinking(response_text)

        # Debug: Log parsing results
        log(f"[Qwen Agent] === PARSING RESULT ===")
        log(f"[Qwen Agent]   Has </think> tag: {'</think>' in response_text}")
        log(f"[Qwen Agent]   Thinking extracted: {len(thinking)} chars")
        log(f"[Qwen Agent]   Answer extracted: {len(answer)} chars")
        if thinking:
            log(f"[Qwen Agent]   Thinking starts with: {repr(thinking[:100])}")
        log(f"[Qwen Agent]   Answer starts with: {repr(answer[:100])}")
        log(f"[Qwen Agent] =========================")

        # Format result with thinking section for web UI
        if thinking:
            formatted_content = f"""<details class="thinking-block">
<summary>🧠 Thinking Process</summary>

{thinking}

</details>

---

{answer.strip()}"""
        else:
            formatted_content = answer.strip()

        return AgentResponse(
            success=True,
            content=formatted_content,
            raw_output=response_text  # Keep full response with thinking
        )

    except Exception as e:
        log(f"[Qwen Agent] Error: {e}")
        return AgentResponse(
            success=False,
            content="",
            error=str(e)
        )


