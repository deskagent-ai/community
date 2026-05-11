# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Anthropic Admin API Client
==========================
Fetches real usage and cost data from Anthropic's Admin API.
Requires an Admin API key (sk-ant-admin...).

This is OPTIONAL - if no admin_api_key is configured, DeskAgent
uses local cost tracking as before.

API Endpoints:
- GET /v1/organizations/usage_report/messages - Token usage by model/date
- GET /v1/organizations/cost_report - Daily costs in USD

Documentation: https://docs.anthropic.com/en/api/admin-api/usage-cost
"""

import json
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import urllib.request
import urllib.error

# Import system_log for background logging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): pass

# Cache configuration
_cache: Dict[str, Any] = {
    "usage": None,
    "cost": None,
    "usage_fetched_at": 0,
    "cost_fetched_at": 0,
}
_cache_lock = threading.Lock()
CACHE_TTL = 900  # 15 minutes

BASE_URL = "https://api.anthropic.com/v1/organizations"


def is_configured(config: dict) -> bool:
    """
    Check if any Claude backend has admin_api_key configured.

    Args:
        config: Full config dict with "ai_backends" key

    Returns:
        True if admin_api_key is found and valid format
    """
    backends = config.get("ai_backends", {})
    for name, backend_config in backends.items():
        # Check Claude backends
        backend_type = backend_config.get("type", "")
        if "claude" in name.lower() or backend_type.startswith("claude"):
            admin_key = backend_config.get("admin_api_key", "")
            if admin_key and admin_key.startswith("sk-ant-admin"):
                return True
    return False


def get_admin_api_key(config: dict) -> Optional[str]:
    """
    Get admin API key from first configured Claude backend.

    Args:
        config: Full config dict with "ai_backends" key

    Returns:
        Admin API key string or None
    """
    backends = config.get("ai_backends", {})
    for name, backend_config in backends.items():
        backend_type = backend_config.get("type", "")
        if "claude" in name.lower() or backend_type.startswith("claude"):
            admin_key = backend_config.get("admin_api_key", "")
            if admin_key and admin_key.startswith("sk-ant-admin"):
                return admin_key
    return None


def _api_request(endpoint: str, admin_key: str) -> dict:
    """
    Make authenticated request to Anthropic Admin API.

    Args:
        endpoint: API endpoint path (after /v1/organizations/)
        admin_key: Admin API key

    Returns:
        Parsed JSON response

    Raises:
        Exception on API errors
    """
    url = f"{BASE_URL}/{endpoint}"
    headers = {
        "anthropic-version": "2023-06-01",
        "x-api-key": admin_key,
        "Content-Type": "application/json",
        "User-Agent": "DeskAgent/1.0"
    }

    system_log(f"[AnthropicAdmin] Request: GET {endpoint}")

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            system_log(f"[AnthropicAdmin] Response OK")
            return data
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        system_log(f"[AnthropicAdmin] HTTP Error {e.code}: {error_body[:200]}")
        raise Exception(f"API Error {e.code}: {error_body}")
    except urllib.error.URLError as e:
        system_log(f"[AnthropicAdmin] URL Error: {e.reason}")
        raise Exception(f"Connection Error: {e.reason}")


def get_usage_report(
    config: dict,
    start_date: str = None,
    end_date: str = None,
    granularity: str = "1d",
    group_by: list = None,
    use_cache: bool = True
) -> dict:
    """
    Fetch usage report from Anthropic API.

    Args:
        config: Main config with ai_backends
        start_date: YYYY-MM-DD (default: 30 days ago)
        end_date: YYYY-MM-DD (default: today)
        granularity: "1m", "1h", or "1d"
        group_by: List of dimensions to group by (e.g., ["model"])
        use_cache: Whether to use cached response

    Returns:
        Usage data with token counts or {"error": "message"}
    """
    global _cache

    admin_key = get_admin_api_key(config)
    if not admin_key:
        return {"error": "No admin API key configured"}

    # Check cache
    with _cache_lock:
        if use_cache and _cache["usage"]:
            age = time.time() - _cache["usage_fetched_at"]
            if age < CACHE_TTL:
                system_log(f"[AnthropicAdmin] Using cached usage data (age: {int(age)}s)")
                return _cache["usage"]

    # Default date range: last 30 days
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%dT23:59:59Z")
    else:
        end_date = f"{end_date}T23:59:59Z"

    if not start_date:
        start_dt = datetime.now() - timedelta(days=30)
        start_date = start_dt.strftime("%Y-%m-%dT00:00:00Z")
    else:
        start_date = f"{start_date}T00:00:00Z"

    # Build query params
    params = f"starting_at={start_date}&ending_at={end_date}&bucket_width={granularity}"
    if group_by:
        for gb in group_by:
            params += f"&group_by[]={gb}"

    endpoint = f"usage_report/messages?{params}"

    try:
        result = _api_request(endpoint, admin_key)
        with _cache_lock:
            _cache["usage"] = result
            _cache["usage_fetched_at"] = time.time()
        return result
    except Exception as e:
        return {"error": str(e)}


def get_cost_report(
    config: dict,
    start_date: str = None,
    end_date: str = None,
    group_by: list = None,
    use_cache: bool = True
) -> dict:
    """
    Fetch cost report from Anthropic API.

    Args:
        config: Main config with ai_backends
        start_date: YYYY-MM-DD (default: 30 days ago)
        end_date: YYYY-MM-DD (default: today)
        group_by: List of dimensions (e.g., ["workspace_id"])
        use_cache: Whether to use cached response

    Returns:
        Cost data in USD or {"error": "message"}
    """
    global _cache

    admin_key = get_admin_api_key(config)
    if not admin_key:
        return {"error": "No admin API key configured"}

    # Check cache
    with _cache_lock:
        if use_cache and _cache["cost"]:
            age = time.time() - _cache["cost_fetched_at"]
            if age < CACHE_TTL:
                system_log(f"[AnthropicAdmin] Using cached cost data (age: {int(age)}s)")
                return _cache["cost"]

    # Default date range: last 30 days
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%dT23:59:59Z")
    else:
        end_date = f"{end_date}T23:59:59Z"

    if not start_date:
        start_dt = datetime.now() - timedelta(days=30)
        start_date = start_dt.strftime("%Y-%m-%dT00:00:00Z")
    else:
        start_date = f"{start_date}T00:00:00Z"

    # Build query params
    params = f"starting_at={start_date}&ending_at={end_date}"
    if group_by:
        for gb in group_by:
            params += f"&group_by[]={gb}"

    endpoint = f"cost_report?{params}"

    try:
        result = _api_request(endpoint, admin_key)
        with _cache_lock:
            _cache["cost"] = result
            _cache["cost_fetched_at"] = time.time()
        return result
    except Exception as e:
        return {"error": str(e)}


def _transform_cost_data(cost_data: dict) -> dict:
    """
    Transform Anthropic API cost response to our format.

    Args:
        cost_data: Raw API response

    Returns:
        Transformed data with total_usd, by_date
    """
    total_usd = 0.0
    by_date = {}

    # Anthropic returns data in "data" array with buckets
    if "data" in cost_data:
        for entry in cost_data["data"]:
            # Cost is in cents as string, convert to USD
            cost_cents = float(entry.get("cost_cents", 0))
            cost_usd = cost_cents / 100.0

            # Get date from bucket timestamp
            bucket_start = entry.get("bucket_start_time", "")
            if bucket_start:
                date_str = bucket_start[:10]  # YYYY-MM-DD
            else:
                date_str = "unknown"

            total_usd += cost_usd

            if date_str not in by_date:
                by_date[date_str] = {"cost_usd": 0.0}
            by_date[date_str]["cost_usd"] += cost_usd

    return {
        "total_usd": total_usd,
        "by_date": by_date,
        "source": "anthropic_api",
        "raw_data": cost_data
    }


def _transform_usage_data(usage_data: dict) -> dict:
    """
    Transform Anthropic API usage response to our format.

    Args:
        usage_data: Raw API response

    Returns:
        Transformed data with token counts, by_model, by_date
    """
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0
    by_model = {}
    by_date = {}

    if "data" in usage_data:
        for entry in usage_data["data"]:
            input_tokens = entry.get("input_tokens", 0)
            output_tokens = entry.get("output_tokens", 0)
            cache_read = entry.get("cache_read_input_tokens", 0)
            cache_write = entry.get("cache_creation_input_tokens", 0)
            model = entry.get("model", "unknown")

            bucket_start = entry.get("bucket_start_time", "")
            date_str = bucket_start[:10] if bucket_start else "unknown"

            total_input += input_tokens
            total_output += output_tokens
            total_cache_read += cache_read
            total_cache_write += cache_write

            # By model
            if model not in by_model:
                by_model[model] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0
                }
            by_model[model]["input_tokens"] += input_tokens
            by_model[model]["output_tokens"] += output_tokens
            by_model[model]["cache_read_tokens"] += cache_read
            by_model[model]["cache_write_tokens"] += cache_write

            # By date
            if date_str not in by_date:
                by_date[date_str] = {
                    "input_tokens": 0,
                    "output_tokens": 0
                }
            by_date[date_str]["input_tokens"] += input_tokens
            by_date[date_str]["output_tokens"] += output_tokens

    return {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_write_tokens": total_cache_write,
        "by_model": by_model,
        "by_date": by_date,
        "source": "anthropic_api"
    }


def get_costs_comparison(config: dict) -> dict:
    """
    Get costs comparison between local tracking and Anthropic API.

    Args:
        config: Full config dict

    Returns:
        {
            "local": {...},  # From cost_tracker
            "anthropic": {...},  # From API (transformed)
            "anthropic_available": True/False,
            "anthropic_configured": True/False,
            "cache_age_seconds": 123 or None,
            "last_error": None or "error message"
        }
    """
    from . import cost_tracker

    result = {
        "local": cost_tracker.get_costs(),
        "anthropic": None,
        "anthropic_available": False,
        "anthropic_configured": is_configured(config),
        "cache_age_seconds": None,
        "last_error": None
    }

    if not result["anthropic_configured"]:
        return result

    # Get Anthropic cost data
    cost_data = get_cost_report(config, use_cache=True)

    if "error" in cost_data:
        result["last_error"] = cost_data["error"]
        return result

    # Transform and add
    result["anthropic"] = _transform_cost_data(cost_data)
    result["anthropic_available"] = True

    # Calculate cache age
    with _cache_lock:
        if _cache["cost_fetched_at"]:
            result["cache_age_seconds"] = int(time.time() - _cache["cost_fetched_at"])

    return result


def invalidate_cache():
    """Clear the cache to force fresh API calls."""
    global _cache
    with _cache_lock:
        _cache = {
            "usage": None,
            "cost": None,
            "usage_fetched_at": 0,
            "cost_fetched_at": 0,
        }
    system_log("[AnthropicAdmin] Cache invalidated")


def get_cache_status() -> dict:
    """Get current cache status."""
    with _cache_lock:
        now = time.time()
        return {
            "usage_cached": _cache["usage"] is not None,
            "usage_age_seconds": int(now - _cache["usage_fetched_at"]) if _cache["usage_fetched_at"] else None,
            "cost_cached": _cache["cost"] is not None,
            "cost_age_seconds": int(now - _cache["cost_fetched_at"]) if _cache["cost_fetched_at"] else None,
            "cache_ttl": CACHE_TTL
        }
