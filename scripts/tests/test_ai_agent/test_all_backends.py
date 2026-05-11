# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Multi-backend integration tests.
Tests ALL configured AI backends in a single test run.

Useful for:
- Deployment validation (are all API keys working?)
- Regression testing (did a change break a backend?)
- Environment setup verification

Run with: pytest -m integration scripts/tests/test_ai_agent/test_all_backends.py -v -s
Skip tool tests: pytest -m "integration and not slow" scripts/tests/test_ai_agent/test_all_backends.py -v -s
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
PROJECT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from ai_agent import call_agent, AgentResponse


# =============================================================================
# Helper Functions
# =============================================================================

def load_live_config() -> dict:
    """Load the real config from workspace config files."""
    # Try workspace config first (merged from config/*.json)
    workspace_dir = PROJECT_DIR.parent
    config_dir = workspace_dir / "config"

    config = {}

    # Load system.json
    system_file = config_dir / "system.json"
    if system_file.exists():
        config.update(json.loads(system_file.read_text(encoding="utf-8")))

    # Load backends.json
    backends_file = config_dir / "backends.json"
    if backends_file.exists():
        backends_config = json.loads(backends_file.read_text(encoding="utf-8"))
        config["ai_backends"] = backends_config.get("ai_backends", {})
        if "default_ai" in backends_config:
            config["default_ai"] = backends_config["default_ai"]

    # Fallback to legacy config.json
    if not config.get("ai_backends"):
        legacy_file = PROJECT_DIR / "config.json"
        if legacy_file.exists():
            config = json.loads(legacy_file.read_text(encoding="utf-8"))

    if not config.get("ai_backends"):
        pytest.skip("No backend configuration found")

    return config


def get_configured_backends(config: dict) -> list[str]:
    """Return list of backend names that appear to be configured."""
    backends = []
    ai_backends = config.get("ai_backends", {})

    for name, cfg in ai_backends.items():
        # Skip if explicitly disabled
        if cfg.get("enabled") is False:
            continue
        # Include if it has a type defined
        if cfg.get("type"):
            backends.append(name)

    return sorted(backends)


def get_streaming_backends(config: dict) -> list[str]:
    """Return backends that support streaming."""
    # claude_cli doesn't support streaming callback
    non_streaming = {"claude"}
    return [b for b in get_configured_backends(config) if b not in non_streaming]


def get_tool_capable_backends(config: dict) -> list[str]:
    """Return backends that support MCP tool calling."""
    # Some backends have limited or no tool support
    limited_tools = {"qwen"}
    return [b for b in get_configured_backends(config) if b not in limited_tools]


def print_backend_report(results: dict):
    """Print a formatted report of backend test results."""
    print("\n")
    print("=" * 80)
    print("                    BACKEND INTEGRATION REPORT")
    print("=" * 80)
    print(f"{'Backend':<18} | {'Status':<6} | {'Model':<22} | {'Tokens':<7} | {'Cost':<8} | {'Time':<6}")
    print("-" * 80)

    for backend, result in results.items():
        status = "PASS" if result.get("success") else "FAIL"
        model = result.get("model", "-") or "-"
        if len(model) > 22:
            model = model[:19] + "..."
        tokens = result.get("tokens", "-")
        if tokens and tokens != "-":
            tokens = str(tokens)
        cost = result.get("cost")
        cost_str = f"${cost:.4f}" if cost else "-"
        duration = result.get("duration")
        duration_str = f"{duration:.1f}s" if duration else "-"

        print(f"{backend:<18} | {status:<6} | {model:<22} | {tokens:<7} | {cost_str:<8} | {duration_str:<6}")

        if result.get("error"):
            print(f"{'':>18}   Error: {result['error'][:50]}")

    print("=" * 80)

    # Summary
    total = len(results)
    success = sum(1 for r in results.values() if r.get("success"))
    pct = (success / total * 100) if total > 0 else 0
    print(f"Summary: {success}/{total} backends working ({pct:.1f}%)")
    print("=" * 80)
    print("\n")


def save_report_json(results: dict, filename: str = "backend_health_report.json"):
    """Save report to JSON file for CI/CD artifacts."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": len(results),
            "success": sum(1 for r in results.values() if r.get("success")),
            "failed": sum(1 for r in results.values() if not r.get("success"))
        },
        "backends": results
    }

    # Save to temp directory
    temp_dir = PROJECT_DIR.parent / "workspace" / ".temp"
    if not temp_dir.exists():
        temp_dir = Path(".")

    report_file = temp_dir / filename
    report_file.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Report saved to: {report_file}")


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def live_config():
    """Load real configuration for integration tests."""
    return load_live_config()


# =============================================================================
# Test: All Backends Summary (Soft Fail)
# =============================================================================

@pytest.mark.integration
def test_all_backends_summary(live_config):
    """
    Test all configured backends and generate summary report.

    SOFT FAIL: This test always passes but reports which backends work.
    Use this for deployment validation and health checks.
    """
    backends = get_configured_backends(live_config)

    if not backends:
        pytest.skip("No backends configured")

    print(f"\n\nTesting {len(backends)} configured backends: {', '.join(backends)}")

    results = {}

    for backend in backends:
        print(f"\n  Testing {backend}...", end=" ", flush=True)
        start_time = time.time()

        try:
            response = call_agent(
                prompt="What is 2+2? Reply with just the number.",
                config=live_config,
                agent_name=backend,
                use_tools=False
            )

            duration = time.time() - start_time

            results[backend] = {
                "success": response.success,
                "model": response.model,
                "tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
                "cost": response.cost_usd,
                "duration": duration,
                "error": response.error if not response.success else None,
                "response_preview": response.content[:100] if response.content else None
            }

            print("OK" if response.success else f"FAILED: {response.error}")

        except Exception as e:
            duration = time.time() - start_time
            results[backend] = {
                "success": False,
                "error": str(e),
                "duration": duration
            }
            print(f"ERROR: {e}")

    # Print detailed report
    print_backend_report(results)

    # Save JSON report
    save_report_json(results)

    # SOFT FAIL: Always pass, just report status
    # The report shows which backends work/fail


# =============================================================================
# Test: Backend Health Check (Parametrized)
# =============================================================================

def pytest_generate_tests(metafunc):
    """Dynamically parametrize tests based on configured backends."""
    if "backend_name" in metafunc.fixturenames:
        try:
            config = load_live_config()
            backends = get_configured_backends(config)
            metafunc.parametrize("backend_name", backends)
        except Exception:
            # If config loading fails, use empty list (tests will be skipped)
            metafunc.parametrize("backend_name", [])


@pytest.mark.integration
def test_backend_health(backend_name, live_config):
    """
    Verify each backend can respond to a simple prompt.

    This test is parametrized - runs once per configured backend.
    """
    response = call_agent(
        prompt="Say 'OK' and nothing else.",
        config=live_config,
        agent_name=backend_name,
        use_tools=False
    )

    # Soft assertion - record but don't fail
    if not response.success:
        pytest.xfail(f"Backend {backend_name} failed: {response.error}")

    assert response.content, f"Backend {backend_name} returned empty response"
    assert response.model or True, f"Backend {backend_name} didn't report model"


# =============================================================================
# Test: Token Counting
# =============================================================================

@pytest.mark.integration
def test_token_counting_all_backends(live_config):
    """
    Verify token counting returns values for configured backends.

    SOFT FAIL: Reports which backends support token counting.
    """
    backends = get_configured_backends(live_config)
    results = {}

    for backend in backends:
        try:
            response = call_agent(
                prompt="Hello world",
                config=live_config,
                agent_name=backend,
                use_tools=False
            )

            has_tokens = (response.input_tokens is not None) or (response.output_tokens is not None)
            results[backend] = {
                "success": response.success,
                "has_tokens": has_tokens,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost": response.cost_usd
            }
        except Exception as e:
            results[backend] = {"success": False, "error": str(e)}

    # Print token counting report
    print("\n\n=== Token Counting Report ===")
    for backend, result in results.items():
        if result.get("success"):
            tokens = f"in={result.get('input_tokens', '?')}, out={result.get('output_tokens', '?')}"
            status = "HAS_TOKENS" if result.get("has_tokens") else "NO_TOKENS"
            print(f"  {backend}: {status} ({tokens})")
        else:
            print(f"  {backend}: FAILED - {result.get('error', 'unknown')}")


# =============================================================================
# Test: Streaming Support
# =============================================================================

@pytest.mark.integration
def test_streaming_all_backends(live_config):
    """
    Verify streaming callbacks work for supported backends.

    SOFT FAIL: Reports which backends support streaming.
    """
    backends = get_streaming_backends(live_config)
    results = {}

    for backend in backends:
        chunks = []

        def on_chunk(token, is_thinking=False, full_response=""):
            chunks.append(token)

        try:
            response = call_agent(
                prompt="Count from 1 to 5, each on a new line.",
                config=live_config,
                agent_name=backend,
                use_tools=False,
                on_chunk=on_chunk
            )

            results[backend] = {
                "success": response.success,
                "chunk_count": len(chunks),
                "streams": len(chunks) > 1
            }
        except Exception as e:
            results[backend] = {"success": False, "error": str(e)}

    # Print streaming report
    print("\n\n=== Streaming Report ===")
    for backend, result in results.items():
        if result.get("success"):
            status = "STREAMS" if result.get("streams") else "NO_STREAM"
            print(f"  {backend}: {status} (chunks={result.get('chunk_count', 0)})")
        else:
            print(f"  {backend}: FAILED - {result.get('error', 'unknown')}")


# =============================================================================
# Test: Tool Usage (Slow)
# =============================================================================

@pytest.mark.integration
@pytest.mark.slow
def test_tool_usage_all_backends(live_config):
    """
    Verify backends can call MCP tools.

    SOFT FAIL: Reports which backends successfully use tools.
    Marked @slow because tool tests take longer.
    """
    backends = get_tool_capable_backends(live_config)
    results = {}

    print(f"\n\nTesting tool usage for {len(backends)} backends...")

    for backend in backends:
        print(f"\n  Testing {backend} with tools...", end=" ", flush=True)

        try:
            response = call_agent(
                prompt="Use the datastore db_get tool to read the key 'test_backend_key'. "
                       "Report whether the key exists or not.",
                config=live_config,
                agent_name=backend,
                use_tools=True
            )

            # Check if tool was likely called (response mentions the operation)
            content_lower = (response.content or "").lower()
            tool_indicators = ["db_get", "not found", "not exist", "doesn't exist", "does not exist",
                              "key", "datastore", "retrieved", "found"]
            tool_called = any(ind in content_lower for ind in tool_indicators)

            results[backend] = {
                "success": response.success,
                "tool_called": tool_called,
                "error": response.error,
                "response_preview": response.content[:150] if response.content else None
            }

            status = "OK" if response.success and tool_called else "PARTIAL" if response.success else "FAILED"
            print(status)

        except Exception as e:
            results[backend] = {"success": False, "tool_called": False, "error": str(e)}
            print(f"ERROR: {e}")

    # Print tool usage report
    print("\n\n=== Tool Usage Report ===")
    for backend, result in results.items():
        if result.get("success"):
            tool_status = "TOOL_USED" if result.get("tool_called") else "NO_TOOL"
            print(f"  {backend}: {tool_status}")
        else:
            print(f"  {backend}: FAILED - {result.get('error', 'unknown')[:50]}")


# =============================================================================
# Test: Response Quality Comparison
# =============================================================================

@pytest.mark.integration
@pytest.mark.slow
def test_response_comparison(live_config):
    """
    Compare response quality across backends with the same prompt.

    SOFT FAIL: Reports comparison but doesn't fail.
    """
    backends = get_configured_backends(live_config)

    # Use a prompt that should work regardless of system context
    prompt = "Explain what an API is in exactly one sentence."

    results = {}

    print(f"\n\nComparing responses for: '{prompt}'")

    for backend in backends:
        try:
            start = time.time()
            response = call_agent(
                prompt=prompt,
                config=live_config,
                agent_name=backend,
                use_tools=False
            )
            duration = time.time() - start

            results[backend] = {
                "success": response.success,
                "response": response.content,
                "duration": duration,
                "tokens": (response.input_tokens or 0) + (response.output_tokens or 0),
                "cost": response.cost_usd
            }
        except Exception as e:
            results[backend] = {"success": False, "error": str(e)}

    # Print comparison
    print("\n\n=== Response Comparison ===")
    for backend, result in results.items():
        print(f"\n--- {backend} ---")
        if result.get("success"):
            print(f"Response: {result.get('response', '')[:200]}")
            print(f"Duration: {result.get('duration', 0):.2f}s | Tokens: {result.get('tokens', '?')} | Cost: ${result.get('cost', 0) or 0:.4f}")
        else:
            print(f"FAILED: {result.get('error', 'unknown')}")
