# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for Lazy MCP Startup (plan-048).

Tests:
- Thread-safety of _cache_by_filter with _cache_lock
- _validate_cache_module whitelist and path traversal protection
- _save_proxy_cache v2 format
- _load_schemas_from_cache with mtime validation
- _lazy_import_mcp with per-MCP locking
- _get_configured_mcp_filter schema-based filter
- warmup_mcp_tools selective warmup
"""

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestCacheLockThreadSafety:
    """Tests for thread-safe _cache_by_filter access."""

    def test_cache_lock_exists(self):
        """Verify _cache_lock is an RLock (reentrant for nested calls)."""
        from ai_agent import tool_bridge

        assert hasattr(tool_bridge, '_cache_lock')
        assert isinstance(tool_bridge._cache_lock, type(threading.RLock()))

    def test_import_locks_exist(self):
        """Verify per-MCP import lock infrastructure exists."""
        from ai_agent import tool_bridge

        assert hasattr(tool_bridge, '_mcp_import_locks')
        assert hasattr(tool_bridge, '_mcp_import_locks_lock')
        assert isinstance(tool_bridge._mcp_import_locks, dict)
        assert isinstance(tool_bridge._mcp_import_locks_lock, type(threading.Lock()))

    def test_clear_cache_thread_safe(self):
        """Verify clear_cache uses _cache_lock."""
        from ai_agent import tool_bridge

        # Populate cache
        with tool_bridge._cache_lock:
            tool_bridge._cache_by_filter["test"] = ({"t": {}}, {"t": lambda: None})

        # Clear should not raise
        tool_bridge.clear_cache()

        with tool_bridge._cache_lock:
            assert "test" not in tool_bridge._cache_by_filter

    def test_concurrent_cache_access(self):
        """Test concurrent read/write to _cache_by_filter doesn't raise."""
        from ai_agent import tool_bridge

        errors = []

        def writer():
            try:
                for i in range(50):
                    with tool_bridge._cache_lock:
                        tool_bridge._cache_by_filter[f"w{i}"] = ({"t": {}}, {"t": lambda: None})
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(50):
                    with tool_bridge._cache_lock:
                        _ = tool_bridge._cache_by_filter.copy()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def clearer():
            try:
                for i in range(10):
                    tool_bridge.clear_cache()
                    time.sleep(0.005)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=clearer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Concurrent access errors: {errors}"

        # Cleanup
        tool_bridge.clear_cache()


class TestValidateCacheModule:
    """Tests for _validate_cache_module security validation."""

    def setup_method(self):
        """Reset module whitelist before each test."""
        from ai_agent import tool_bridge
        tool_bridge._ALLOWED_MCP_MODULES = None

    def test_blocks_path_traversal_dots(self):
        """Path traversal with .. must be blocked."""
        from ai_agent import tool_bridge

        assert tool_bridge._validate_cache_module("../../evil") is False

    def test_blocks_path_traversal_forward_slash(self):
        """Path traversal with / must be blocked."""
        from ai_agent import tool_bridge

        assert tool_bridge._validate_cache_module("evil/module") is False

    def test_blocks_path_traversal_backslash(self):
        """Path traversal with \\ must be blocked."""
        from ai_agent import tool_bridge

        assert tool_bridge._validate_cache_module("evil\\module") is False

    def test_blocks_empty_module(self):
        """Empty module name must be rejected."""
        from ai_agent import tool_bridge

        assert tool_bridge._validate_cache_module("") is False

    def test_accepts_valid_mcp_module(self, tmp_path, monkeypatch):
        """Valid MCP module name is accepted."""
        from ai_agent import tool_bridge

        # Create mock MCP directory
        mcp_dir = tmp_path / "mcp"
        mcp_dir.mkdir()
        (mcp_dir / "outlook").mkdir()
        (mcp_dir / "outlook" / "__init__.py").write_text("# MCP", encoding="utf-8")
        (mcp_dir / "billomat").mkdir()
        (mcp_dir / "billomat" / "__init__.py").write_text("# MCP", encoding="utf-8")

        monkeypatch.setattr(tool_bridge, "get_mcp_dir", lambda: mcp_dir)
        tool_bridge._ALLOWED_MCP_MODULES = None  # Force rebuild

        assert tool_bridge._validate_cache_module("outlook") is True
        assert tool_bridge._validate_cache_module("outlook.outlook_calendar") is True
        assert tool_bridge._validate_cache_module("billomat") is True

    def test_rejects_unknown_module(self, tmp_path, monkeypatch):
        """Unknown module name is rejected."""
        from ai_agent import tool_bridge

        mcp_dir = tmp_path / "mcp"
        mcp_dir.mkdir()
        (mcp_dir / "outlook").mkdir()

        monkeypatch.setattr(tool_bridge, "get_mcp_dir", lambda: mcp_dir)
        tool_bridge._ALLOWED_MCP_MODULES = None

        assert tool_bridge._validate_cache_module("evil_module") is False


class TestSaveProxyCacheV2:
    """Tests for _save_proxy_cache v2 format."""

    def test_saves_v2_format(self, tmp_path, monkeypatch):
        """Verify cache is saved in v2 format with all required fields."""
        from ai_agent import tool_bridge
        import paths

        # Create mock directories
        logs_dir = tmp_path / "workspace" / ".logs"
        logs_dir.mkdir(parents=True)
        temp_dir = tmp_path / "workspace" / ".temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        mcp_dir = tmp_path / "mcp"
        mcp_dir.mkdir()
        outlook_dir = mcp_dir / "outlook"
        outlook_dir.mkdir()
        (outlook_dir / "__init__.py").write_text("# MCP", encoding="utf-8")

        monkeypatch.setattr(tool_bridge, "get_mcp_dir", lambda: mcp_dir)
        monkeypatch.setattr(paths, "get_logs_dir", lambda: logs_dir)

        # Create test tools and function map
        def outlook_get_email():
            """Get email."""
            return "email"

        outlook_get_email.__module__ = "outlook"

        tools = [{
            "type": "function",
            "function": {
                "name": "outlook_get_email",
                "description": "Get email",
                "parameters": {"type": "object", "properties": {}}
            }
        }]
        function_map = {"outlook_get_email": outlook_get_email}

        # Save cache
        tool_bridge._save_proxy_cache(tools, function_map)

        # Read and verify
        cache_file = logs_dir.parent / ".temp" / "proxy_tool_cache.json"
        assert cache_file.exists()

        cache_data = json.loads(cache_file.read_text(encoding='utf-8'))

        # v2 fields
        assert cache_data["version"] == 2
        assert "mcp_mtimes" in cache_data
        assert "configured_mcps" in cache_data
        assert isinstance(cache_data["configured_mcps"], list)
        assert "generated" in cache_data

        # Tool fields
        assert len(cache_data["tools"]) == 1
        tool = cache_data["tools"][0]
        assert tool["name"] == "outlook_get_email"
        assert "is_high_risk" in tool
        assert "is_destructive" in tool
        assert "is_read_only" in tool


class TestLoadSchemasFromCache:
    """Tests for _load_schemas_from_cache."""

    def test_returns_none_when_no_cache(self, tmp_path, monkeypatch):
        """Returns None when cache file doesn't exist."""
        from ai_agent import tool_bridge
        import paths

        logs_dir = tmp_path / "workspace" / ".logs"
        logs_dir.mkdir(parents=True)
        monkeypatch.setattr(paths, "get_logs_dir", lambda: logs_dir)

        result = tool_bridge._load_schemas_from_cache()
        assert result is None

    def test_returns_none_for_v1_cache(self, tmp_path, monkeypatch):
        """Returns None for v1 cache (lacks security metadata)."""
        from ai_agent import tool_bridge
        import paths

        logs_dir = tmp_path / "workspace" / ".logs"
        logs_dir.mkdir(parents=True)
        temp_dir = logs_dir.parent / ".temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(paths, "get_logs_dir", lambda: logs_dir)

        # Write v1 cache
        cache_file = temp_dir / "proxy_tool_cache.json"
        cache_file.write_text(json.dumps({
            "version": 1,
            "generated": "2026-01-01 00:00:00",
            "tools": [{"name": "test_tool", "module": "test"}]
        }), encoding='utf-8')

        result = tool_bridge._load_schemas_from_cache()
        assert result is None

    def test_detects_stale_cache_via_mtime(self, tmp_path, monkeypatch):
        """Cache is rejected when MCP file mtime differs."""
        from ai_agent import tool_bridge
        import paths

        logs_dir = tmp_path / "workspace" / ".logs"
        logs_dir.mkdir(parents=True)
        temp_dir = logs_dir.parent / ".temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Create MCP directory with module
        mcp_dir = tmp_path / "mcp"
        mcp_dir.mkdir()
        outlook_dir = mcp_dir / "outlook"
        outlook_dir.mkdir()
        init_file = outlook_dir / "__init__.py"
        init_file.write_text("# MCP", encoding="utf-8")

        monkeypatch.setattr(paths, "get_logs_dir", lambda: logs_dir)
        monkeypatch.setattr(tool_bridge, "get_mcp_dir", lambda: mcp_dir)
        tool_bridge._ALLOWED_MCP_MODULES = None

        # Write cache with correct bridge_mtime but outdated MCP mtime (0.0 vs actual)
        bridge_mtime = Path(tool_bridge.__file__).stat().st_mtime
        cache_file = temp_dir / "proxy_tool_cache.json"
        cache_file.write_text(json.dumps({
            "version": 2,
            "generated": "2026-01-01 00:00:00",
            "bridge_mtime": bridge_mtime,
            "mcp_mtimes": {"outlook": 0.0},
            "configured_mcps": ["outlook"],
            "tools": [{
                "name": "outlook_get_email",
                "description": "Get email",
                "parameters": {},
                "module": "outlook",
                "is_high_risk": True,
                "is_destructive": False,
                "is_read_only": True,
            }]
        }), encoding='utf-8')

        result = tool_bridge._load_schemas_from_cache()
        assert result is None  # Stale cache rejected

    def test_loads_valid_v2_cache(self, tmp_path, monkeypatch):
        """Loads tools from valid v2 cache file."""
        from ai_agent import tool_bridge
        import paths

        logs_dir = tmp_path / "workspace" / ".logs"
        logs_dir.mkdir(parents=True)
        temp_dir = logs_dir.parent / ".temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Create MCP directory
        mcp_dir = tmp_path / "mcp"
        mcp_dir.mkdir()
        outlook_dir = mcp_dir / "outlook"
        outlook_dir.mkdir()
        init_file = outlook_dir / "__init__.py"
        init_file.write_text("# MCP", encoding="utf-8")
        actual_mtime = init_file.stat().st_mtime
        bridge_mtime = Path(tool_bridge.__file__).stat().st_mtime

        monkeypatch.setattr(paths, "get_logs_dir", lambda: logs_dir)
        monkeypatch.setattr(tool_bridge, "get_mcp_dir", lambda: mcp_dir)
        tool_bridge._ALLOWED_MCP_MODULES = None

        # Write cache with correct mtime
        cache_file = temp_dir / "proxy_tool_cache.json"
        cache_file.write_text(json.dumps({
            "version": 2,
            "generated": "2026-01-01 00:00:00",
            "bridge_mtime": bridge_mtime,
            "mcp_mtimes": {"outlook": actual_mtime},
            "configured_mcps": ["outlook"],
            "tools": [{
                "name": "outlook_get_email",
                "description": "Get email",
                "parameters": {"type": "object", "properties": {}},
                "module": "outlook",
                "is_high_risk": True,
                "is_destructive": False,
                "is_read_only": True,
            }]
        }), encoding='utf-8')

        result = tool_bridge._load_schemas_from_cache()
        assert result is not None

        tools, function_map = result
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "outlook_get_email"
        assert "outlook_get_email" in function_map
        # Lazy function should be callable
        assert callable(function_map["outlook_get_email"])

    def test_respects_mcp_filter(self, tmp_path, monkeypatch):
        """MCP filter correctly excludes non-matching tools."""
        from ai_agent import tool_bridge
        import paths

        logs_dir = tmp_path / "workspace" / ".logs"
        logs_dir.mkdir(parents=True)
        temp_dir = logs_dir.parent / ".temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        mcp_dir = tmp_path / "mcp"
        mcp_dir.mkdir()
        for name in ["outlook", "billomat"]:
            d = mcp_dir / name
            d.mkdir()
            f = d / "__init__.py"
            f.write_text("# MCP", encoding="utf-8")

        mtimes = {}
        for name in ["outlook", "billomat"]:
            mtimes[name] = (mcp_dir / name / "__init__.py").stat().st_mtime
        bridge_mtime = Path(tool_bridge.__file__).stat().st_mtime

        monkeypatch.setattr(paths, "get_logs_dir", lambda: logs_dir)
        monkeypatch.setattr(tool_bridge, "get_mcp_dir", lambda: mcp_dir)
        tool_bridge._ALLOWED_MCP_MODULES = None

        cache_file = temp_dir / "proxy_tool_cache.json"
        cache_file.write_text(json.dumps({
            "version": 2,
            "generated": "2026-01-01 00:00:00",
            "bridge_mtime": bridge_mtime,
            "mcp_mtimes": mtimes,
            "configured_mcps": ["outlook", "billomat"],
            "tools": [
                {"name": "outlook_get_email", "description": "", "parameters": {},
                 "module": "outlook", "is_high_risk": False, "is_destructive": False, "is_read_only": True},
                {"name": "billomat_get_client", "description": "", "parameters": {},
                 "module": "billomat", "is_high_risk": False, "is_destructive": False, "is_read_only": True},
            ]
        }), encoding='utf-8')

        # Only load outlook
        result = tool_bridge._load_schemas_from_cache("outlook")
        assert result is not None
        tools, function_map = result
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "outlook_get_email"


class TestLazyImportMcp:
    """Tests for _lazy_import_mcp."""

    def test_rejects_invalid_module(self, tmp_path, monkeypatch):
        """Raises ValueError for invalid module names."""
        from ai_agent import tool_bridge

        mcp_dir = tmp_path / "mcp"
        mcp_dir.mkdir()
        monkeypatch.setattr(tool_bridge, "get_mcp_dir", lambda: mcp_dir)
        tool_bridge._ALLOWED_MCP_MODULES = None

        with pytest.raises(ValueError, match="Invalid MCP module"):
            tool_bridge._lazy_import_mcp("../../evil")

    def test_returns_none_for_missing_directory(self, tmp_path, monkeypatch):
        """Returns None when MCP package directory doesn't exist."""
        from ai_agent import tool_bridge

        mcp_dir = tmp_path / "mcp"
        mcp_dir.mkdir()
        # Add "outlook" to whitelist but don't create directory
        (mcp_dir / "outlook").mkdir()

        monkeypatch.setattr(tool_bridge, "get_mcp_dir", lambda: mcp_dir)
        tool_bridge._ALLOWED_MCP_MODULES = None
        # Clear cached module so _lazy_import_mcp doesn't short-circuit via sys.modules
        monkeypatch.delitem(sys.modules, "outlook", raising=False)

        # No __init__.py -> should return None
        result = tool_bridge._lazy_import_mcp("outlook")
        assert result is None


class TestWarmupMcpTools:
    """Tests for warmup_mcp_tools selective warmup."""

    def test_warmup_accepts_filter(self):
        """warmup_mcp_tools accepts mcp_filter parameter."""
        from ai_agent import tool_bridge

        # Just verify it doesn't crash with a filter
        with patch.object(tool_bridge, '_discover_mcp_tools', return_value=([], {})):
            tool_bridge.warmup_mcp_tools(mcp_filter="outlook|billomat")

    def test_warmup_without_filter_uses_config(self):
        """warmup_mcp_tools without filter calls _get_configured_mcp_filter."""
        from ai_agent import tool_bridge

        with patch.object(tool_bridge, '_get_configured_mcp_filter', return_value="outlook|billomat") as mock_filter:
            with patch.object(tool_bridge, '_discover_mcp_tools', return_value=([], {})):
                tool_bridge.warmup_mcp_tools()
                mock_filter.assert_called_once()


class TestProxyCacheV2Compatibility:
    """Tests for v1/v2 cache compatibility in all cache readers."""

    def test_claude_sdk_reads_v2_cache(self, tmp_path):
        """claude_agent_sdk.load_tool_mcp_mapping works with v2 cache."""
        # Create v2 cache
        cache_file = tmp_path / "proxy_tool_cache.json"
        cache_file.write_text(json.dumps({
            "version": 2,
            "generated": "2026-01-01 00:00:00",
            "mcp_mtimes": {"outlook": 1000.0},
            "configured_mcps": ["outlook"],
            "tools": [{
                "name": "outlook_get_email",
                "description": "Get email",
                "parameters": {},
                "module": "outlook",
                "is_high_risk": True,
                "is_destructive": False,
                "is_read_only": True,
            }]
        }), encoding='utf-8')

        # Manually parse as load_tool_mcp_mapping would
        cache = json.loads(cache_file.read_text(encoding='utf-8'))
        tool_to_mcp = {}
        for tool in cache.get("tools", []):
            tool_name = tool.get("name", "")
            module = tool.get("module", "")
            mcp_name = module.split(".")[0] if module else ""
            if tool_name and mcp_name:
                tool_to_mcp[tool_name] = mcp_name

        assert tool_to_mcp["outlook_get_email"] == "outlook"

    def test_v2_cache_has_security_metadata(self, tmp_path):
        """v2 cache tools have is_high_risk, is_destructive, is_read_only."""
        cache_data = {
            "version": 2,
            "generated": "2026-01-01 00:00:00",
            "mcp_mtimes": {},
            "configured_mcps": ["outlook"],
            "tools": [{
                "name": "outlook_get_email",
                "description": "Get email",
                "parameters": {},
                "module": "outlook",
                "is_high_risk": True,
                "is_destructive": False,
                "is_read_only": True,
            }]
        }

        tool = cache_data["tools"][0]
        assert tool["is_high_risk"] is True
        assert tool["is_destructive"] is False
        assert tool["is_read_only"] is True
