# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Gemini ADK Agent
=================
Google Gemini API with streaming and tool support.
Uses tool_bridge for dynamic MCP tool discovery.
"""

import base64
import concurrent.futures
import json
import random
import sys
import time
from pathlib import Path
from typing import Callable, Optional
from paths import PROJECT_DIR
from .agent_logging import AgentResponse, write_prompt_log
from .dev_context import add_dev_tool_result, capture_dev_context, update_dev_iteration
from .event_publishing import publish_context_event, publish_tool_event
from .logging import log, log_tool_call
from .prompt_builder import build_system_prompt, build_system_prompt_parts
from .token_utils import estimate_tokens, format_tokens, get_context_limit
from . import tool_bridge
from . import anonymizer


class CancelledException(Exception):
    """Raised when task is cancelled by user."""
    pass

# Add project root to path for MCP imports
sys.path.insert(0, str(PROJECT_DIR))

# Retry settings for transient errors (503, 429, etc.)
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2  # seconds, exponential backoff

# =============================================================================
# GEMINI CONTEXT CACHING
# =============================================================================
# Cache static system prompt content for 40-60% token savings on multi-turn
# conversations. Dynamic content (date/time) is appended at runtime.
#
# Cache structure: {cache_key: {"cache_name": str, "created": float, "tokens": int}}
# Cache key: hash of model + static_prompt
# TTL: 5 minutes (Gemini default)

import hashlib

_gemini_cache_store: dict = {}  # In-memory cache metadata
_CACHE_TTL_SECONDS = 300  # 5 minutes (Gemini's minimum)


def _get_cache_key(model: str, static_prompt: str) -> str:
    """Generate cache key from model and static prompt content."""
    content = f"{model}::{static_prompt}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _is_cache_valid(cache_key: str) -> bool:
    """Check if cached content is still valid (within TTL)."""
    if cache_key not in _gemini_cache_store:
        return False
    cache_entry = _gemini_cache_store[cache_key]
    age = time.time() - cache_entry.get("created", 0)
    return age < _CACHE_TTL_SECONDS


def _get_or_create_cache(client, model: str, static_prompt: str) -> tuple:
    """
    Get existing cache or create new one for the static system prompt.

    Args:
        client: Gemini API client
        model: Model name (e.g., "gemini-2.5-pro")
        static_prompt: The cacheable part of the system prompt

    Returns:
        Tuple of (cache_name or None, cache_tokens, is_cache_hit)
        - cache_name: Name of the cached content (for API calls) or None if caching failed
        - cache_tokens: Number of tokens in cached content
        - is_cache_hit: True if using existing cache, False if created new
    """
    from google.genai import types

    cache_key = _get_cache_key(model, static_prompt)
    cache_tokens = estimate_tokens(static_prompt)

    # Check for existing valid cache
    if _is_cache_valid(cache_key):
        cache_entry = _gemini_cache_store[cache_key]
        log(f"[Gemini Cache] HIT - reusing cache '{cache_key}' ({cache_entry.get('tokens', 0)} tokens, "
            f"{int(time.time() - cache_entry.get('created', 0))}s old)")
        return cache_entry.get("cache_name"), cache_entry.get("tokens", 0), True

    # Create new cache
    try:
        log(f"[Gemini Cache] MISS - creating new cache for {cache_tokens} tokens...")

        # Create cached content via Gemini API
        # Note: Requires minimum 32,768 tokens for caching to be effective
        # For smaller prompts, caching overhead may not be worth it
        if cache_tokens < 1000:
            log(f"[Gemini Cache] Skipped - prompt too small ({cache_tokens} tokens < 1000 minimum)")
            return None, cache_tokens, False

        cached_content = client.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                system_instruction=static_prompt,
                ttl=f"{_CACHE_TTL_SECONDS}s"
            )
        )

        # Store cache metadata
        _gemini_cache_store[cache_key] = {
            "cache_name": cached_content.name,
            "created": time.time(),
            "tokens": cache_tokens,
            "model": model
        }

        log(f"[Gemini Cache] Created cache '{cached_content.name}' ({cache_tokens} tokens, TTL {_CACHE_TTL_SECONDS}s)")
        return cached_content.name, cache_tokens, False

    except Exception as e:
        # Caching failed - continue without cache (graceful degradation)
        log(f"[Gemini Cache] Failed to create cache: {e}")
        log(f"[Gemini Cache] Continuing without caching (full prompt will be sent each time)")
        return None, cache_tokens, False


def _cleanup_expired_caches():
    """Remove expired cache entries from local store."""
    global _gemini_cache_store
    now = time.time()
    expired = [k for k, v in _gemini_cache_store.items()
               if now - v.get("created", 0) > _CACHE_TTL_SECONDS]
    for key in expired:
        del _gemini_cache_store[key]
    if expired:
        log(f"[Gemini Cache] Cleaned up {len(expired)} expired cache entries")


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
    if api_key.startswith("YOUR_") or api_key == "AIza...":
        return False, "API key is placeholder"
    if len(api_key) < 10:
        return False, "API key too short"

    return True, None


def _get_candidate_parts(candidate):
    """Safely get parts from a Gemini candidate response.

    Returns empty list if candidate, content, or parts is None.
    This handles cases where Gemini returns a response with finish_reason=STOP
    but no actual content (e.g., after processing many tool results).
    """
    if not candidate:
        return []
    if not hasattr(candidate, 'content') or not candidate.content:
        return []
    if not hasattr(candidate.content, 'parts') or not candidate.content.parts:
        return []
    return candidate.content.parts


def _clean_gemini_response(response: str) -> str:
    """Clean up Gemini response by removing internal content.

    Removes:
    - Tool markers [Tool: name | time] (only for live updates, not final output)
    - "thought" blocks (Gemini's internal reasoning that leaked)
    - Internal Python analysis code blocks
    """
    import re

    lines = response.split('\n')
    clean_lines = []
    skip_until_header = False
    skip_code_block = False

    for line in lines:
        # Skip tool markers (e.g. "[Tool: get_file_info | 0.0s]")
        if re.match(r'^\s*\[Tool:\s*\S+.*\]\s*$', line):
            continue

        # Detect "thought" marker - skip until next markdown header
        if line.strip() == 'thought':
            skip_until_header = True
            continue

        # In skip mode, look for markdown header to resume
        if skip_until_header:
            # Resume at markdown headers (actual user content)
            if re.match(r'^#{1,3}\s+', line.strip()):
                skip_until_header = False
                skip_code_block = False
            # Also track code blocks to skip internal Python analysis
            elif line.strip().startswith('```'):
                skip_code_block = not skip_code_block
                continue
            else:
                continue

        clean_lines.append(line)

    # Remove multiple consecutive empty lines
    result = '\n'.join(clean_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


class ThinkingRequiredError(Exception):
    """Raised when model requires thinking mode but budget is 0."""
    pass


def _call_with_retry(client, model: str, contents, config, max_retries: int = MAX_RETRIES,
                     is_cancelled: Optional[Callable[[], bool]] = None,
                     on_chunk: Optional[Callable] = None):
    """Call Gemini API with retry logic, jitter backoff, UI feedback and cancellation support.

    Uses full-jitter exponential backoff (Google/AWS best practice).
    Sends UI feedback via on_chunk during retry delays (from 2nd attempt).
    Shows user-friendly error message when all retries are exhausted.
    Checks for cancellation every 500ms during API call.
    Raises ThinkingRequiredError if model requires thinking mode.
    Raises CancelledException if cancelled by user.

    Args:
        client: Gemini API client
        model: Model name
        contents: Prompt contents
        config: Generation config
        max_retries: Maximum retry attempts
        is_cancelled: Optional cancellation check callback
        on_chunk: Optional streaming callback for UI feedback
                  Signature: on_chunk(token, is_thinking, full_response, anon_stats)
    """
    last_error = None
    cancel_check_interval = 0.5  # Check every 500ms

    def _api_call():
        """Execute the actual API call in a separate thread."""
        return client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )

    for attempt in range(max_retries + 1):
        # Check for cancellation before starting attempt
        if is_cancelled and is_cancelled():
            log("[Gemini] Task cancelled before API call")
            raise CancelledException("Task cancelled by user")

        try:
            # Execute API call in thread pool with cancel-check loop
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_api_call)

                # Wait for result with periodic cancellation checks
                while True:
                    try:
                        result = future.result(timeout=cancel_check_interval)
                        return result
                    except concurrent.futures.TimeoutError:
                        # Check for cancellation during wait
                        if is_cancelled and is_cancelled():
                            log("[Gemini] Task cancelled during API call - aborting")
                            future.cancel()
                            raise CancelledException("Task cancelled during API call")
                        # Continue waiting
                        continue

        except CancelledException:
            # Re-raise cancellation without retry
            raise

        except Exception as e:
            error_str = str(e)

            # Check for thinking mode required error (non-retryable, needs config change)
            if "Budget 0 is invalid" in error_str or "only works in thinking mode" in error_str:
                raise ThinkingRequiredError(f"Model {model} requires thinking mode (thinking_budget > 0)")

            # Check for retryable errors (503, 500, 502, 504 Service errors, 429 Rate Limit)
            if any(code in error_str for code in ("503", "500", "502", "504", "429")) \
               or "UNAVAILABLE" in error_str or "overloaded" in error_str.lower():
                last_error = e
                if attempt < max_retries:
                    # Full-Jitter Backoff (Google/AWS Best Practice)
                    cap = min(60.0, RETRY_DELAY_BASE * (2 ** attempt))
                    delay = max(1.0, random.uniform(0, cap))

                    log(f"[Gemini] API error (attempt {attempt + 1}/{max_retries + 1}): {error_str[:100]}")
                    log(f"[Gemini] Retrying in {delay:.1f}s...")

                    # UI-Feedback ab 2. Versuch (attempt > 0)
                    if on_chunk and attempt > 0:
                        retry_msg = f"\n*Gemini API ueberlastet -- Retry {attempt + 1}/{max_retries} in {int(delay)}s...*\n"
                        try:
                            on_chunk(retry_msg, False, "", None)
                        except Exception:
                            pass  # UI feedback is non-critical

                    # Use cancellable sleep
                    sleep_start = time.time()
                    while time.time() - sleep_start < delay:
                        if is_cancelled and is_cancelled():
                            log("[Gemini] Task cancelled during retry delay")
                            raise CancelledException("Task cancelled during retry")
                        time.sleep(min(0.5, max(0.1, delay - (time.time() - sleep_start))))
                    continue
                else:
                    # Last attempt exhausted - fall through to user-friendly error below
                    log(f"[Gemini] All retries exhausted (attempt {attempt + 1}/{max_retries + 1}): {error_str[:100]}")
                    break
            # Non-retryable error, raise immediately
            raise

    # All retries exhausted - user-friendly error message
    error_str = str(last_error)
    if "503" in error_str or "UNAVAILABLE" in error_str or "high demand" in error_str.lower() \
       or "overloaded" in error_str.lower():
        raise Exception(
            f"Das Modell {model} ist derzeit ueberlastet "
            f"(Google meldet hohe Nachfrage, {max_retries + 1} Versuche fehlgeschlagen). "
            f"Bitte in 1-2 Minuten erneut versuchen oder "
            f"ein anderes Modell verwenden (z.B. gemini_flash)."
        )
    raise last_error


def _get_tools(mcp_filter: str = None, allowed_tools: list = None, blocked_tools: list = None, tool_mode: str = None) -> list:
    """Get tools in Gemini format.

    Args:
        mcp_filter: Optional regex pattern to filter MCP servers (e.g., "outlook|billomat")
        allowed_tools: Optional whitelist of tool names (e.g., ["read_file", "list_directory"])
        blocked_tools: Optional blacklist of tool names (e.g., ["delete_email"])
        tool_mode: Optional security mode ("full", "read_only", "write_safe")
    """
    ollama_tools = tool_bridge.get_ollama_tools(mcp_filter, allowed_tools, blocked_tools, tool_mode)

    # Convert Ollama format to Gemini function declarations
    gemini_tools = []
    for tool in ollama_tools:
        func = tool.get("function", {})
        params = func.get("parameters", {"type": "object", "properties": {}})

        # Gemini uses a slightly different format
        gemini_tools.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "parameters": params
        })

    log(f"[Gemini] Loaded {len(gemini_tools)} tools" +
        (f" (filter: {mcp_filter})" if mcp_filter else ""))
    return gemini_tools


def call_gemini_adk(
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
    Call Gemini API with streaming and optional tool support.

    Args:
        prompt: The prompt for the model
        config: Main configuration
        agent_config: Agent-specific configuration
        use_tools: If True, enable tool calling
        on_chunk: Optional callback for streaming updates
                  Signature: on_chunk(token, is_thinking, full_response, anon_stats)
        anon_context: Optional anonymization context for tool results
        knowledge_pattern: Optional regex pattern to filter knowledge files
        is_cancelled: Optional callback that returns True if task should be cancelled
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        # Nuitka standalone: MetaPathBasedLoader blocks runtime import of
        # excluded packages. Fallback via importlib.util bypasses Nuitka's loader.
        # See: https://github.com/Nuitka/Nuitka/issues/1077
        import os as _os
        try:
            import importlib
            import importlib.util

            for _sp in sys.path:
                _genai_init = _os.path.join(_sp, 'google', 'genai', '__init__.py')
                if _os.path.isfile(_genai_init):
                    _google_dir = _os.path.join(_sp, 'google')

                    # Ensure google namespace module exists
                    _gmod = sys.modules.get('google')
                    if _gmod is None:
                        import types as _types_mod
                        _gmod = _types_mod.ModuleType('google')
                        _gmod.__path__ = [_google_dir]
                        _gmod.__package__ = 'google'
                        sys.modules['google'] = _gmod
                    elif hasattr(_gmod, '__path__') and _google_dir not in list(_gmod.__path__):
                        _gmod.__path__.append(_google_dir)

                    # Load google.genai via importlib (bypasses Nuitka loader)
                    _genai_dir = _os.path.join(_google_dir, 'genai')
                    _spec = importlib.util.spec_from_file_location(
                        'google.genai', _genai_init,
                        submodule_search_locations=[_genai_dir]
                    )
                    if _spec and _spec.loader:
                        genai = importlib.util.module_from_spec(_spec)
                        sys.modules['google.genai'] = genai
                        _gmod.genai = genai
                        _spec.loader.exec_module(genai)
                        types = importlib.import_module('google.genai.types')
                        log(f"[Gemini] Loaded google.genai via importlib fallback")
                        break
            else:
                return AgentResponse(
                    success=False,
                    content="",
                    error="google-genai package not installed. Run: pip install google-genai"
                )
        except Exception as _err:
            return AgentResponse(
                success=False,
                content="",
                error=f"google-genai import failed: {_err}"
            )

    api_key = agent_config.get("api_key", "")
    model = agent_config.get("model", "gemini-2.5-pro")
    timeout = agent_config.get("timeout", 300)
    max_tokens = agent_config.get("max_tokens", 8192)
    temperature = agent_config.get("temperature", 0.7)

    # thinking_budget: Model-aware defaults
    # - Gemini 2.5+ and 3.0 models require thinking mode (budget > 0)
    # - Gemini 2.0/1.5 models can disable thinking (budget = 0)
    thinking_budget = agent_config.get("thinking_budget")
    if thinking_budget is None or thinking_budget == 0:
        # Check if model requires thinking mode (2.5 or 3.0 series)
        if "2.5" in model or "2-5" in model or "gemini-3" in model:
            thinking_budget = 8192  # Default for 2.5+ and 3.0 models
            log(f"[Gemini] Auto-set thinking_budget=8192 for {model} (requires thinking mode)")
        else:
            thinking_budget = 0  # Older models can disable thinking

    if not api_key:
        return AgentResponse(
            success=False,
            content="",
            error="No API key configured for gemini_adk. Get one at https://ai.google.dev/"
        )

    # Build system message in parts (static = cacheable, dynamic = date/time)
    static_system, dynamic_system = build_system_prompt_parts(agent_config, knowledge_pattern, config=config)
    system_message = static_system + dynamic_system  # Full prompt for logging/non-cached use

    # Log context with token estimates
    static_tokens = estimate_tokens(static_system)
    dynamic_tokens = estimate_tokens(dynamic_system)
    system_tokens = static_tokens + dynamic_tokens
    prompt_tokens = estimate_tokens(prompt)
    context_limit = get_context_limit(model)
    initial_total = system_tokens + prompt_tokens

    # Token breakdown for UI display
    token_breakdown = {
        "system": system_tokens,
        "prompt": prompt_tokens,
        "tools": 0  # Will be updated as tools execute
    }

    log(f"[Gemini] CONTEXT ESTIMATE:")
    log(f"[Gemini]    Model: {model} ({format_tokens(context_limit)} limit)")
    log(f"[Gemini]    System prompt: {format_tokens(system_tokens)} tokens ({format_tokens(static_tokens)} static + {format_tokens(dynamic_tokens)} dynamic)")
    log(f"[Gemini]    User prompt: {format_tokens(prompt_tokens)} tokens ({len(prompt)} chars)")
    log(f"[Gemini]    Initial total: {format_tokens(initial_total)} tokens ({initial_total/context_limit*100:.1f}% of limit)")
    log(f"[Gemini]    Tools enabled: {use_tools}")
    log(f"[Gemini]    Thinking budget: {thinking_budget if thinking_budget is not None else 'auto'}")

    # Capture context for Developer Mode debugging
    capture_dev_context(system_prompt=system_message, user_prompt=prompt, model=model)

    # Get max_iterations from agent config (default: 30)
    max_iterations = agent_config.get("max_iterations", 30)

    # Send initial context breakdown to UI
    publish_context_event(
        iteration=0, max_iterations=max_iterations,
        system_tokens=system_tokens, prompt_tokens=prompt_tokens, tool_tokens=0
    )

    start_time = time.time()

    try:
        # Initialize client with AFC disabled (we handle tools manually)
        client = genai.Client(
            api_key=api_key,
            http_options={"timeout": timeout * 1000}  # timeout in ms
        )

        # Build tool config if needed
        tools_param = None
        if use_tools:
            # Get MCP filter pattern from agent config
            mcp_filter = agent_config.get("allowed_mcp")
            allowed_tools = agent_config.get("allowed_tools")
            blocked_tools = agent_config.get("blocked_tools")
            tool_mode = agent_config.get("tool_mode", "full")
            if mcp_filter:
                log(f"[Gemini] MCP filter: {mcp_filter}")
                # Set MCP filter in TaskContext for execute_tool() to use
                # (important for hallucinated tool names that need auto-correction)
                tool_bridge.set_mcp_filter(mcp_filter)
            if allowed_tools:
                log(f"[Gemini] Allowed tools (whitelist): {allowed_tools}")
            if blocked_tools:
                log(f"[Gemini] Blocked tools (blacklist): {blocked_tools}")
            if tool_mode != "full":
                log(f"[Gemini] Tool mode: {tool_mode}")

            # Set anonymization context for tool input de-anonymization
            if anon_context is not None:
                tool_bridge.set_anonymization_context(anon_context)

            gemini_tools = _get_tools(mcp_filter, allowed_tools, blocked_tools, tool_mode)
            if gemini_tools:
                tools_param = [types.Tool(function_declarations=[
                    types.FunctionDeclaration(
                        name=t["name"],
                        description=t["description"],
                        parameters=t["parameters"]
                    )
                    for t in gemini_tools
                ])]
                # Write prompt log with tools
                write_prompt_log(system_message, prompt, agent_name="gemini", model=model, tools=gemini_tools)
            else:
                write_prompt_log(system_message, prompt, agent_name="gemini", model=model)
        else:
            # No tools - write prompt log without tools
            write_prompt_log(system_message, prompt, agent_name="gemini", model=model)

        # === CONTEXT CACHING ===
        # Try to cache the static system prompt (knowledge, templates, instructions)
        # Dynamic part (date/time) is appended to each request
        _cleanup_expired_caches()  # Housekeeping

        cache_name = None
        cache_tokens = 0
        is_cache_hit = False

        # Check if caching is enabled in agent config (default: True)
        enable_caching = agent_config.get("enable_caching", True)

        # Disable caching when tools are used - Gemini API doesn't allow
        # tools in GenerateContent when using cached_content
        if enable_caching and static_tokens >= 1000 and not tools_param:
            # Try to get or create cache for static content
            cache_name, cache_tokens, is_cache_hit = _get_or_create_cache(client, model, static_system)

        # Build generation config
        if cache_name:
            # Using cached content - dynamic part goes in the user prompt
            log(f"[Gemini] Using cached system prompt ({cache_tokens} tokens cached)")
            gen_config = types.GenerateContentConfig(
                cached_content=cache_name,
                max_output_tokens=max_tokens,
                temperature=temperature,
                thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget) if thinking_budget is not None else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True  # We handle tools manually via tool_bridge
                ) if use_tools and tools_param else None,
                tools=tools_param,
            )
            # Prepend dynamic system content to user prompt
            effective_prompt = f"{dynamic_system}\n\n---\n\n{prompt}"
        else:
            # No caching - use full system message as before
            log(f"[Gemini] No caching (full system prompt: {system_tokens} tokens)")
            gen_config = types.GenerateContentConfig(
                system_instruction=system_message,
                max_output_tokens=max_tokens,
                temperature=temperature,
                thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget) if thinking_budget is not None else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True  # We handle tools manually via tool_bridge
                ) if use_tools and tools_param else None,
                tools=tools_param,
            )
            effective_prompt = prompt

        # Check for cancellation before API call
        if is_cancelled and is_cancelled():
            log("[Gemini] Task cancelled before API call")
            return AgentResponse(
                success=False,
                content="",
                error="Task cancelled"
            )

        # Make single API call (non-streaming for tool support)
        # Now includes cancellation check every 500ms during API call
        log(f"[Gemini] Calling API...")
        try:
            response = _call_with_retry(client, model, effective_prompt, gen_config, is_cancelled=is_cancelled, on_chunk=on_chunk)
        except CancelledException:
            log("[Gemini] Task cancelled during API call")
            return AgentResponse(
                success=False,
                content="",
                error="Task cancelled",
                cancelled=True
            )
        log(f"[Gemini] API response received")

        # Track token usage
        input_tokens = 0
        output_tokens = 0
        cached_content_token_count = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            input_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0
            # Check for cached content tokens (indicates cache was used)
            if hasattr(response.usage_metadata, 'cached_content_token_count'):
                cached_content_token_count = response.usage_metadata.cached_content_token_count or 0

            if cached_content_token_count > 0:
                log(f"[Gemini] Tokens: {input_tokens} in ({cached_content_token_count} cached = 75% off), {output_tokens} out")
            else:
                log(f"[Gemini] Tokens: {input_tokens} in, {output_tokens} out")

        # Anonymization stats tracking (parallel to anon_context)
        anon_stats = {
            "total_entities": 0,
            "entity_types": {},
            "tool_calls_anonymized": 0,
            "mappings": {}
        }

        def _build_anon_stats():
            """Build anon_stats dict from anon_context for on_chunk callback."""
            if anon_context is None:
                return None
            anon_stats["mappings"] = anon_context.mappings.copy()
            anon_stats["total_entities"] = len(anon_context.mappings)
            # Build entity_types from counters
            anon_stats["entity_types"] = dict(anon_context.counters) if anon_context.counters else {}
            return anon_stats

        # Process response
        full_response = ""
        function_call_parts = []  # Store whole Part objects (preserves thought_signature for Gemini 3)

        if response.candidates:
            for candidate in response.candidates:
                for part in _get_candidate_parts(candidate):
                    # Check for text
                    if hasattr(part, 'text') and part.text:
                        full_response += part.text
                        if on_chunk:
                            try:
                                on_chunk(part.text, False, full_response, _build_anon_stats())
                            except Exception as e:
                                log(f"[Gemini] Callback error: {e}")

                    # Check for function call - store entire Part (includes thought_signature)
                    if hasattr(part, 'function_call') and part.function_call:
                        function_call_parts.append(part)

        # Handle function calls - execute ALL tools, then send ALL results at once
        if function_call_parts:
            log(f"[Gemini] {len(function_call_parts)} function call(s) requested")

            # Execute all tools and collect results
            tool_results = []
            for fc_part in function_call_parts:
                tool_name = fc_part.function_call.name
                tool_args = dict(fc_part.function_call.args) if fc_part.function_call.args else {}

                log(f"[Gemini] Tool: {tool_name}")
                log(f"[Gemini] Args: {tool_args}")

                # Add tool marker to response for UI badge display (before execution)
                # Format matches claude_agent_sdk: [Tool: name ⏳]
                tool_msg = f"\n[Tool: {tool_name} ⏳]\n"
                full_response += tool_msg
                if on_chunk:
                    try:
                        on_chunk(tool_msg, True, full_response, _build_anon_stats())
                    except Exception as e:
                        log(f"[Gemini] Callback error: {e}")

                # Execute tool with timing - send args preview to UI
                args_preview = None
                if tool_args:
                    args_str = str(tool_args)
                    args_preview = args_str[:80] + "..." if len(args_str) > 80 else args_str
                publish_tool_event(tool_name, "executing", args_preview=args_preview)
                tool_start = time.time()
                result = tool_bridge.execute_tool(tool_name, tool_args)
                tool_duration = time.time() - tool_start
                # Send result preview to UI
                result_preview = result[:80] + "..." if len(result) > 80 else result
                publish_tool_event(tool_name, "complete", tool_duration, result_preview=result_preview)

                result_tokens = estimate_tokens(result)
                token_breakdown["tools"] += result_tokens  # Track for UI display
                log(f"[Gemini] Result: {len(result)} chars (+{format_tokens(result_tokens)} tokens) in {tool_duration:.1f}s")

                # Update tool marker with timing (format matches claude_agent_sdk)
                full_response = full_response.replace(
                    f"[Tool: {tool_name} ⏳]",
                    f"[Tool: {tool_name} | {tool_duration:.1f}s]"
                )
                if on_chunk:
                    try:
                        on_chunk("", False, full_response, _build_anon_stats())
                    except (TypeError, ValueError, RuntimeError):
                        pass  # Callback error - non-critical for streaming

                # Anonymize tool result if context provided
                anon_count = 0
                if anon_context is not None:
                    old_count = len(anon_context.mappings)
                    result, anon_context = anonymizer.anonymize_with_context(
                        result, config, anon_context
                    )
                    anon_count = len(anon_context.mappings) - old_count
                    if anon_count > 0:
                        anon_stats["tool_calls_anonymized"] += 1
                        log(f"[Gemini] Tool result anonymized")

                # Log anonymized result (what goes to AI over internet)
                log_tool_call(tool_name, "RESULT", result)

                # Capture for Developer Mode (with anon count and args)
                add_dev_tool_result(tool_name, result, anon_count, args=tool_args)

                tool_results.append({
                    "name": tool_name,
                    "args": tool_args,
                    "result": result
                })

            # Send ALL tool results in ONE continuation call
            # Pass initial_response to preserve content before tool calls
            continuation_response, anon_context = _continue_with_all_tool_results(
                client, model, system_message, max_tokens,
                prompt, function_call_parts, tool_results,
                on_chunk, tools_param,
                anon_context=anon_context, config=config,
                max_iterations=max_iterations,
                is_cancelled=is_cancelled,
                initial_response=full_response,  # Preserve initial content
                thinking_budget=thinking_budget,
                temperature=temperature,
                token_breakdown=token_breakdown,  # Pass for UI token tracking
                anon_stats=anon_stats  # Pass for PII dialog tool count
            )
            # continuation_response already includes initial_response (accumulated)
            # So we just use it directly, don't double-add
            full_response = continuation_response or full_response

        duration = time.time() - start_time

        # Calculate cost (with cache discount if applicable)
        pricing = agent_config.get("pricing", {"input": 1.25, "output": 10})

        # Gemini cache discount: 75% off for cached tokens
        # cached_content_token_count = tokens read from cache (not billed at full rate)
        non_cached_input = input_tokens - cached_content_token_count
        cached_cost = (cached_content_token_count * pricing["input"] * 0.25 / 1_000_000)  # 75% off
        non_cached_cost = (non_cached_input * pricing["input"] / 1_000_000)
        output_cost = (output_tokens * pricing["output"] / 1_000_000)
        cost_usd = cached_cost + non_cached_cost + output_cost

        if cached_content_token_count > 0:
            savings = (cached_content_token_count * pricing["input"] * 0.75 / 1_000_000)
            log(f"[Gemini] Cost: ${cost_usd:.4f} (saved ${savings:.4f} from cache)")
        else:
            log(f"[Gemini] Cost: ${cost_usd:.4f}")
        log(f"[Gemini] Duration: {duration:.1f}s")
        log(f"[Gemini] === RESPONSE ===")
        log(full_response[:500] + "..." if len(full_response) > 500 else full_response)
        log(f"[Gemini] ================")

        if not full_response.strip():
            return AgentResponse(
                success=False,
                content="",
                error="Empty response from Gemini API"
            )

        # Clean up response (remove tool markers, thinking blocks, etc.)
        clean_response = _clean_gemini_response(full_response)
        log(f"[Gemini] Cleaned response: {len(full_response)} -> {len(clean_response)} chars")

        # NOTE: De-anonymization is done CENTRALLY in __init__.py
        # We just pass the mappings through for the final result
        if anon_context and anon_context.mappings:
            log(f"[Gemini] Passing {len(anon_context.mappings)} mappings to central de-anonymization")

        return AgentResponse(
            success=True,
            content=clean_response,
            raw_output=full_response,  # Keep original for debugging
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            anonymization=dict(anon_context.mappings) if anon_context and anon_context.mappings else None
        )

    except Exception as e:
        log(f"[Gemini] Error: {e}")
        import traceback
        log(f"[Gemini] Traceback: {traceback.format_exc()}")
        return AgentResponse(
            success=False,
            content="",
            error=str(e)
        )


def _parse_image_content(result: str) -> tuple[str, list]:
    """Parse tool result for embedded images.

    Detects [IMAGE:mime_type:base64data] format and extracts images.

    Args:
        result: Tool result string

    Returns:
        tuple: (text_without_images, list of {"mime_type": str, "data": str})
    """
    import re

    images = []
    # Pattern: [IMAGE:mime_type:base64data]
    pattern = r'\[IMAGE:(image/[a-z]+):([A-Za-z0-9+/=]+)\]'

    def replace_image(match):
        mime_type = match.group(1)
        b64_data = match.group(2)
        images.append({"mime_type": mime_type, "data": b64_data})
        return f"[Image {len(images)} embedded]"

    text = re.sub(pattern, replace_image, result)
    return text, images


def _continue_with_all_tool_results(
    client,
    model: str,
    system_message: str,
    max_tokens: int,
    original_prompt: str,
    function_call_parts: list,
    tool_results: list,
    on_chunk: callable,
    tools_param: list = None,
    anon_context: "anonymizer.AnonymizationContext" = None,
    config: dict = None,
    max_iterations: int = 30,
    is_cancelled: callable = None,
    initial_response: str = "",
    thinking_budget: int = 0,
    temperature: float = 0.7,
    token_breakdown: dict = None,
    anon_stats: dict = None
) -> tuple:
    """
    Continue conversation with ALL tool results at once.

    This sends all function calls and their results in a single API call,
    allowing the model to see all results and generate a coherent response.

    If the model responds with more function calls, they are executed and
    the loop continues until a text response is received or max_iterations is hit.

    Args:
        initial_response: Text response before tool calls (to preserve in accumulated output)

    Returns:
        tuple: (response_text, anon_context) - the response and updated anonymization context
    """
    from google.genai import types

    log(f"[Gemini] Continuing with {len(tool_results)} tool result(s)")

    # Helper functions to create Part objects (with fallback for different SDK versions)
    def make_text_part(text):
        if hasattr(types.Part, 'from_text'):
            return types.Part.from_text(text=text)
        return types.Part(text=text)

    def make_function_response_part(name, response):
        if hasattr(types.Part, 'from_function_response'):
            return types.Part.from_function_response(name=name, response=response)
        return types.Part(function_response=types.FunctionResponse(name=name, response=response))

    # Build initial conversation history
    contents = [
        types.Content(
            role="user",
            parts=[make_text_part(original_prompt)]
        )
    ]

    # Add initial model function calls (use original Part objects to preserve thought_signature)
    contents.append(types.Content(role="model", parts=list(function_call_parts)))

    # Add initial function responses (with image support)
    response_parts = []
    for tr in tool_results:
        result_text = tr["result"]
        # Check for embedded images in result
        text_only, images = _parse_image_content(result_text)

        if images:
            log(f"[Gemini] Found {len(images)} embedded image(s) in tool result")
            # Add function response with text placeholder
            response_parts.append(make_function_response_part(
                name=tr["name"],
                response={"result": text_only}
            ))
            # Add images as inline data parts (Gemini Vision)
            for img in images:
                try:
                    image_part = types.Part.from_bytes(
                        data=base64.b64decode(img["data"]),
                        mime_type=img["mime_type"]
                    )
                    response_parts.append(image_part)
                    log(f"[Gemini] Added image part: {img['mime_type']}")
                except Exception as e:
                    log(f"[Gemini] Failed to add image: {e}")
        else:
            response_parts.append(make_function_response_part(
                name=tr["name"],
                response={"result": result_text}
            ))
    contents.append(types.Content(role="user", parts=response_parts))

    # Config WITH tools so model understands context, but AFC disabled, optionally limit thinking
    gen_config = types.GenerateContentConfig(
        system_instruction=system_message,
        max_output_tokens=max_tokens,
        temperature=temperature,
        thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget) if thinking_budget is not None else None,
        tools=tools_param,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True
        ) if tools_param else None,
    )

    # Tool calling loop - continues until we get text or hit max iterations
    iteration = 0
    empty_retries = 0  # Track empty response retries (max 1)
    malformed_retries = 0  # Track malformed function call retries (max 3)
    last_attempted_function = None  # Track last function name for better error messages
    # Accumulate all text responses across iterations (start with initial_response if provided)
    accumulated_response = initial_response if initial_response else ""
    # Track total tool calls across all iterations (start with initial tool_results count)
    total_tool_count = len(tool_results) if tool_results else 0
    # Initialize anon_stats if not provided
    if anon_stats is None:
        anon_stats = {"total_entities": 0, "entity_types": {}, "tool_calls_anonymized": 0, "mappings": {}}

    def _build_anon_stats():
        """Build anon_stats dict from anon_context for on_chunk callback."""
        if anon_context is None:
            return None
        anon_stats["mappings"] = anon_context.mappings.copy()
        anon_stats["total_entities"] = len(anon_context.mappings)
        anon_stats["entity_types"] = dict(anon_context.counters) if anon_context.counters else {}
        return anon_stats

    while iteration < max_iterations:
        # Check for cancellation at start of each iteration
        if is_cancelled and is_cancelled():
            log("[Gemini] Task cancelled during tool loop")
            # Return accumulated response so far, not just cancel message
            if accumulated_response.strip():
                return accumulated_response + "\n\n[Task cancelled]", anon_context
            return "[Task cancelled]", anon_context

        iteration += 1
        update_dev_iteration(iteration, max_iterations)
        # Publish context event for UI update (with token breakdown if available)
        if token_breakdown:
            publish_context_event(
                iteration=iteration, max_iterations=max_iterations,
                tool_count=total_tool_count,
                system_tokens=token_breakdown.get("system", 0),
                prompt_tokens=token_breakdown.get("prompt", 0),
                tool_tokens=token_breakdown.get("tools", 0)
            )
        else:
            publish_context_event(iteration=iteration, max_iterations=max_iterations,
                                  tool_count=total_tool_count)
        log(f"[Gemini] Conversation: {len(contents)} messages")
        log(f"[Gemini] Calling continuation API (iteration {iteration})...")

        try:
            response = _call_with_retry(client, model, contents, gen_config, is_cancelled=is_cancelled, on_chunk=on_chunk)
        except CancelledException:
            log("[Gemini] Task cancelled during continuation API call")
            if accumulated_response.strip():
                return accumulated_response + "\n\n[Task cancelled]", anon_context
            return "[Task cancelled]", anon_context
        log(f"[Gemini] Continuation response received")

        # Debug: Log response structure
        if response.candidates:
            log(f"[Gemini] Candidates: {len(response.candidates)}")
            for i, candidate in enumerate(response.candidates):
                finish_reason = getattr(candidate, 'finish_reason', 'unknown')
                log(f"[Gemini] Candidate {i}: finish_reason={finish_reason}")

                # Log extra details for malformed function calls
                if 'MALFORMED' in str(finish_reason):
                    log(f"[Gemini] ⚠️ MALFORMED_FUNCTION_CALL detected!")
                    # Try to extract what function was attempted
                    for part in _get_candidate_parts(candidate):
                        if hasattr(part, 'function_call') and part.function_call:
                            fc = part.function_call
                            last_attempted_function = fc.name
                            log(f"[Gemini] Attempted function: {fc.name}")
                            log(f"[Gemini] Attempted args: {dict(fc.args) if fc.args else 'None'}")

                parts = _get_candidate_parts(candidate)
                if parts:
                    log(f"[Gemini] Candidate {i}: {len(parts)} parts")
                    for j, part in enumerate(parts):
                        part_types = []
                        if hasattr(part, 'text') and part.text:
                            part_types.append(f"text({len(part.text)} chars)")
                        if hasattr(part, 'function_call') and part.function_call:
                            part_types.append(f"function_call({part.function_call.name})")
                        log(f"[Gemini] Part {j}: {', '.join(part_types) or 'empty'}")
                else:
                    log(f"[Gemini] Candidate {i}: no content/parts")
        else:
            log(f"[Gemini] No candidates in response!")
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                log(f"[Gemini] Prompt feedback: {response.prompt_feedback}")

        # Extract text and function calls from response
        iteration_text = ""
        new_function_call_parts = []  # Store whole Part objects (preserves thought_signature)

        if response.candidates:
            for candidate in response.candidates:
                for part in _get_candidate_parts(candidate):
                    if hasattr(part, 'text') and part.text:
                        iteration_text += part.text
                        # Add to accumulated response (no extra newlines - just concatenate)
                        accumulated_response += part.text
                        if on_chunk:
                            try:
                                on_chunk(part.text, False, accumulated_response, _build_anon_stats())
                            except (TypeError, ValueError, RuntimeError):
                                pass  # Callback error - non-critical for streaming
                    if hasattr(part, 'function_call') and part.function_call:
                        new_function_call_parts.append(part)

        # If we got text response (and no more function calls), we're done
        if iteration_text.strip() and not new_function_call_parts:
            log(f"[Gemini] Final response: {len(accumulated_response)} chars (accumulated)")
            return accumulated_response, anon_context

        # If we got function calls, execute them and continue the loop
        if new_function_call_parts:
            total_tool_count += len(new_function_call_parts)
            log(f"[Gemini] Model requested {len(new_function_call_parts)} more tool call(s) (total: {total_tool_count})")

            # Execute all tool calls
            new_tool_results = []
            for fc_part in new_function_call_parts:
                tool_name = fc_part.function_call.name
                tool_args = dict(fc_part.function_call.args) if fc_part.function_call.args else {}

                log(f"[Gemini] Tool: {tool_name}")
                log(f"[Gemini] Args: {tool_args}")

                # Add tool marker to response for UI badge display (before execution)
                # Format matches claude_agent_sdk: [Tool: name ⏳]
                tool_msg = f"\n[Tool: {tool_name} ⏳]\n"
                accumulated_response += tool_msg
                if on_chunk:
                    try:
                        on_chunk(tool_msg, True, accumulated_response, _build_anon_stats())
                    except (TypeError, ValueError, RuntimeError):
                        pass  # Callback error - non-critical for streaming

                # Execute tool with timing - send args preview to UI
                args_preview = None
                if tool_args:
                    args_str = str(tool_args)
                    args_preview = args_str[:80] + "..." if len(args_str) > 80 else args_str
                publish_tool_event(tool_name, "executing", args_preview=args_preview)
                tool_start = time.time()
                result = tool_bridge.execute_tool(tool_name, tool_args)
                tool_duration = time.time() - tool_start
                # Send result preview to UI
                result_preview = result[:80] + "..." if len(result) > 80 else result
                publish_tool_event(tool_name, "complete", tool_duration, result_preview=result_preview)

                result_tokens = estimate_tokens(result)
                if token_breakdown:
                    token_breakdown["tools"] += result_tokens  # Track for UI display
                log(f"[Gemini] Result: {len(result)} chars (+{format_tokens(result_tokens)} tokens) in {tool_duration:.1f}s")

                # Update tool marker with timing (format matches claude_agent_sdk)
                accumulated_response = accumulated_response.replace(
                    f"[Tool: {tool_name} ⏳]",
                    f"[Tool: {tool_name} | {tool_duration:.1f}s]"
                )
                if on_chunk:
                    try:
                        on_chunk("", False, accumulated_response, _build_anon_stats())
                    except (TypeError, ValueError, RuntimeError):
                        pass  # Callback error - non-critical for streaming

                # Anonymize if context provided
                anon_count = 0
                if anon_context is not None and config is not None:
                    old_count = len(anon_context.mappings)
                    result, anon_context = anonymizer.anonymize_with_context(
                        result, config, anon_context
                    )
                    anon_count = len(anon_context.mappings) - old_count
                    if anon_count > 0:
                        anon_stats["tool_calls_anonymized"] += 1
                        log(f"[Gemini] Tool result anonymized")

                # Log anonymized result (what goes to AI over internet)
                log_tool_call(tool_name, "RESULT", result)

                # Capture for Developer Mode (with anon count and args)
                add_dev_tool_result(tool_name, result, anon_count, args=tool_args)

                new_tool_results.append({
                    "name": tool_name,
                    "args": tool_args,
                    "result": result
                })

            # Add model's function calls to conversation (use original Parts to preserve thought_signature)
            contents.append(types.Content(role="model", parts=list(new_function_call_parts)))

            # Add function responses to conversation (with image support)
            new_response_parts = []
            for tr in new_tool_results:
                result_text = tr["result"]
                # Check for embedded images in result
                text_only, images = _parse_image_content(result_text)

                if images:
                    log(f"[Gemini] Found {len(images)} embedded image(s) in tool result")
                    new_response_parts.append(make_function_response_part(
                        name=tr["name"],
                        response={"result": text_only}
                    ))
                    # Add images as inline data parts
                    for img in images:
                        try:
                            image_part = types.Part.from_bytes(
                                data=base64.b64decode(img["data"]),
                                mime_type=img["mime_type"]
                            )
                            new_response_parts.append(image_part)
                            log(f"[Gemini] Added image part: {img['mime_type']}")
                        except Exception as e:
                            log(f"[Gemini] Failed to add image: {e}")
                else:
                    new_response_parts.append(make_function_response_part(
                        name=tr["name"],
                        response={"result": result_text}
                    ))
            contents.append(types.Content(role="user", parts=new_response_parts))

            # Continue loop for next iteration
            continue

        # No text and no function calls - check for issues and retry
        if not iteration_text.strip() and not new_function_call_parts:
            if response.candidates:
                finish_reason = getattr(response.candidates[0], 'finish_reason', None)

                # Check if it was a malformed function call
                if finish_reason and 'MALFORMED' in str(finish_reason):
                    malformed_retries += 1
                    if malformed_retries > 2:  # Stop after 3 retries (1, 2, 3)
                        log(f"[Gemini] ❌ Max malformed retries (3) reached, trying text-only fallback")

                        # Try text-only fallback - ask model to generate text without tools
                        try:
                            fallback_message = types.Content(
                                role="user",
                                parts=[make_text_part(
                                    "WICHTIG: Die Datensammlung ist abgeschlossen. "
                                    "Generiere jetzt KEINE weiteren Tool-Aufrufe. "
                                    "Erstelle stattdessen die Zusammenfassung basierend auf den bereits abgerufenen Daten. "
                                    "Antworte nur mit Text im erwarteten Markdown-Format."
                                )]
                            )

                            # API call WITHOUT tools parameter
                            fallback_response = client.models.generate_content(
                                model=model,
                                contents=contents + [fallback_message],
                                config=types.GenerateContentConfig(
                                    system_instruction=system_message,
                                    temperature=0.3,  # Lower for deterministic output
                                    max_output_tokens=max_tokens
                                    # NO tools parameter - force text-only response
                                )
                            )

                            # Extract text from response
                            if fallback_response.candidates:
                                parts = _get_candidate_parts(fallback_response.candidates[0])
                                fallback_text = "".join(p.text for p in parts if hasattr(p, "text") and p.text)
                                if fallback_text.strip():
                                    log(f"[Gemini] Text-only fallback successful ({len(fallback_text)} chars)")
                                    combined = accumulated_response + "\n\n" + fallback_text if accumulated_response.strip() else fallback_text
                                    return combined, anon_context

                            log(f"[Gemini] Text-only fallback returned no text")
                        except Exception as e:
                            log(f"[Gemini] Text-only fallback failed: {e}")

                        # If fallback also fails, return with error note as before
                        error_note = (
                            f"\n\n---\n"
                            f"⚠️ **Agent gestoppt: Wiederholte fehlerhafte Tool-Aufrufe**\n\n"
                            f"Das Modell konnte nach 3 Versuchen keinen gültigen Tool-Aufruf generieren."
                        )
                        if last_attempted_function:
                            error_note += f"\nLetzter versuchter Tool: `{last_attempted_function}`"
                        return (accumulated_response + error_note) if accumulated_response.strip() else error_note, anon_context

                    log(f"[Gemini] Malformed function call (retry {malformed_retries}/3), asking model to retry")

                    # Build more helpful error message
                    error_msg = "Der letzte Funktionsaufruf war fehlerhaft (MALFORMED_FUNCTION_CALL). "
                    if last_attempted_function:
                        error_msg += f"Die Funktion '{last_attempted_function}' konnte nicht ausgeführt werden. "
                    error_msg += (
                        "Bitte versuche es erneut und achte auf:\n"
                        "1. Alle erforderlichen Parameter müssen angegeben sein\n"
                        "2. Parameter-Typen müssen korrekt sein (string, number, array, etc.)\n"
                        "3. JSON-Syntax muss gültig sein\n\n"
                        "Falls das Tool nicht funktioniert, fahre ohne diesen Tool-Aufruf fort und gib eine Antwort basierend auf den bereits gesammelten Daten."
                    )

                    contents.append(types.Content(
                        role="user",
                        parts=[make_text_part(error_msg)]
                    ))
                    continue  # Retry

                # Empty response with STOP - model may have "forgotten" to respond
                # This can happen after many tool calls when model loses context
                if finish_reason and 'STOP' in str(finish_reason):
                    # Only retry once to avoid infinite loop
                    if empty_retries < 1:
                        empty_retries += 1
                        log(f"[Gemini] Empty STOP response after tool calls, prompting for summary (retry {empty_retries})")
                        contents.append(types.Content(
                            role="user",
                            parts=[make_text_part(
                                "Du hast alle benötigten Daten gesammelt. "
                                "Bitte erstelle jetzt die Zusammenfassung basierend auf den Tool-Ergebnissen. "
                                "Gib eine vollständige Antwort im gewünschten Format aus."
                            )]
                        ))
                        continue  # Retry with prompt to summarize

            log(f"[Gemini] Empty response with no function calls, stopping")
            break

    # Check if we hit max iterations (agent still working) vs no response
    if iteration >= max_iterations:
        log(f"[Gemini] ⚠️ Max iterations ({max_iterations}) reached - agent was still working")
        iteration_warning = (
            f"\n\n---\n"
            f"⚠️ **Agent wurde nach {max_iterations} Tool-Aufrufen gestoppt**\n\n"
            f"Der Agent war noch nicht fertig, aber das Iterations-Limit wurde erreicht.\n\n"
            f"**Was du tun kannst:**\n"
            f"- Aufgabe in kleinere Teile aufteilen\n"
            f"- `max_iterations` in der Agent-Config erhöhen (z.B. auf 50 oder 60)\n"
            f"- Den Prompt präziser formulieren"
        )
    else:
        log(f"[Gemini] No response from model")
        iteration_warning = ""

    # Return accumulated response (includes initial_response + all iteration texts)
    final_response = accumulated_response if accumulated_response.strip() else "[No response from model after tool execution]"
    return final_response + iteration_warning, anon_context
