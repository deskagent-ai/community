# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for MCP package imports.

Ensures all MCP packages with multiple modules can be imported correctly,
especially when loaded dynamically via importlib.import_module().

This tests the fix for "attempted relative import with no known parent package"
which occurs when packages use relative imports but are loaded dynamically.
"""

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

# Get paths
SCRIPTS_DIR = Path(__file__).parent.parent.parent
DESKAGENT_DIR = SCRIPTS_DIR.parent
MCP_DIR = DESKAGENT_DIR / "mcp"


# List of MCP packages that have multiple modules (not single-file MCPs)
MCP_PACKAGES_WITH_SUBMODULES = [
    "outlook",
    "gmail",
    "msgraph",
    "imap",
    "instagram",
]


def import_mcp_package(package_name: str):
    """Import an MCP package the same way the proxy does.

    This adds the MCP directory to sys.path and imports the package.
    This simulates what anonymization_proxy_mcp.load_mcp_package() does.
    """
    package_dir = MCP_DIR / package_name

    if not package_dir.exists():
        raise ImportError(f"Package directory not found: {package_dir}")

    # Add MCP directory to path (same as proxy does)
    mcp_path = str(MCP_DIR)
    if mcp_path not in sys.path:
        sys.path.insert(0, mcp_path)

    # Clear any cached version of the module
    modules_to_clear = [k for k in list(sys.modules.keys()) if k.startswith(package_name)]
    for mod in modules_to_clear:
        del sys.modules[mod]

    # Import the package
    return importlib.import_module(package_name)


class TestMcpPackageImports:
    """Tests that all MCP packages can be imported correctly."""

    @pytest.mark.parametrize("package_name", MCP_PACKAGES_WITH_SUBMODULES)
    def test_package_imports_via_importlib(self, package_name):
        """Test that package can be imported via importlib.import_module().

        This simulates how the anonymization proxy loads MCP packages.
        """
        try:
            module = import_mcp_package(package_name)
        except ImportError as e:
            pytest.fail(f"Failed to import {package_name}: {e}")

        # Should have the mcp instance
        assert hasattr(module, "mcp"), f"{package_name} should export 'mcp'"

        # Should not raise ImportError
        assert module is not None

    @pytest.mark.parametrize("package_name", MCP_PACKAGES_WITH_SUBMODULES)
    def test_package_has_no_relative_imports(self, package_name):
        """Test that package files don't use relative imports.

        Relative imports (from .base import) don't work with dynamic loading.
        All imports should be absolute (from package.base import).
        """
        package_dir = MCP_DIR / package_name

        if not package_dir.exists():
            pytest.skip(f"Package {package_name} not found at {package_dir}")

        for py_file in package_dir.glob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            lines = content.split("\n")

            for i, line in enumerate(lines, 1):
                # Skip comments
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue

                # Check for relative imports at start of line
                if stripped.startswith("from ."):
                    pytest.fail(
                        f"{py_file.name}:{i} has relative import: {stripped}\n"
                        f"Should use absolute import: from {package_name}.xxx import ..."
                    )

    @pytest.mark.parametrize("package_name", MCP_PACKAGES_WITH_SUBMODULES)
    def test_package_submodules_import_correctly(self, package_name):
        """Test that submodules are properly registered after import."""
        try:
            module = import_mcp_package(package_name)
        except ImportError as e:
            pytest.skip(f"Could not import {package_name}: {e}")

        # After importing the main package, submodules should be accessible
        # Check that we can access common submodules
        if hasattr(module, "__all__"):
            for exported in module.__all__:
                assert hasattr(module, exported), f"{package_name} should export {exported}"


class TestMcpToolDiscovery:
    """Tests for MCP tool discovery from packages."""

    @pytest.mark.parametrize("package_name", MCP_PACKAGES_WITH_SUBMODULES)
    def test_package_has_tools(self, package_name):
        """Test that package exposes tools via FastMCP."""
        try:
            module = import_mcp_package(package_name)
        except ImportError as e:
            pytest.skip(f"Could not import {package_name}: {e}")

        # Should have mcp instance
        assert hasattr(module, "mcp"), f"{package_name} should have 'mcp' attribute"

        mcp = module.mcp

        # FastMCP stores tools in _tool_manager._tools
        if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
            tools = mcp._tool_manager._tools
            assert len(tools) > 0, f"{package_name} should have at least one tool"


class TestMcpHighRiskTools:
    """Tests for HIGH_RISK_TOOLS definition in MCP packages."""

    @pytest.mark.parametrize("package_name", ["outlook", "gmail", "msgraph", "imap"])
    def test_high_risk_tools_defined(self, package_name):
        """Test that packages handling external data define HIGH_RISK_TOOLS."""
        try:
            module = import_mcp_package(package_name)
        except ImportError as e:
            pytest.skip(f"Could not import {package_name}: {e}")

        # Packages that handle external content should define HIGH_RISK_TOOLS
        if hasattr(module, "HIGH_RISK_TOOLS"):
            assert isinstance(module.HIGH_RISK_TOOLS, set), "HIGH_RISK_TOOLS should be a set"


class TestNoRelativeImportsInAllMcps:
    """Comprehensive test that scans all MCP packages for relative imports."""

    def test_all_mcp_packages_use_absolute_imports(self):
        """Scan all MCP packages and verify no relative imports are used."""
        if not MCP_DIR.exists():
            pytest.skip(f"MCP directory not found: {MCP_DIR}")

        errors = []

        for package_dir in MCP_DIR.iterdir():
            if not package_dir.is_dir():
                continue
            if package_dir.name.startswith("_"):
                continue
            if not (package_dir / "__init__.py").exists():
                continue

            # This is a package
            for py_file in package_dir.glob("*.py"):
                content = py_file.read_text(encoding="utf-8")
                lines = content.split("\n")

                for i, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue

                    if stripped.startswith("from ."):
                        errors.append(
                            f"{package_dir.name}/{py_file.name}:{i}: {stripped}"
                        )

        if errors:
            error_msg = "Found relative imports that should be absolute:\n"
            error_msg += "\n".join(f"  - {e}" for e in errors)
            pytest.fail(error_msg)


class TestMcpApiStub:
    """Tests for _mcp_api.py stub module importability."""

    def test_mcp_api_stub_importable(self):
        """_mcp_api.py is importable from mcp directory."""
        # Ensure MCP directory is in path
        mcp_path = str(MCP_DIR)
        if mcp_path not in sys.path:
            sys.path.insert(0, mcp_path)

        # Clear any cached import
        if "_mcp_api" in sys.modules:
            del sys.modules["_mcp_api"]

        # Import the stub module
        mod = importlib.import_module("_mcp_api")

        # Verify expected functions exist
        assert hasattr(mod, "load_config"), "_mcp_api should have load_config"
        assert hasattr(mod, "mcp_log"), "_mcp_api should have mcp_log"
        assert hasattr(mod, "get_config_dir"), "_mcp_api should have get_config_dir"
        assert hasattr(mod, "get_temp_dir"), "_mcp_api should have get_temp_dir"
        assert hasattr(mod, "get_exports_dir"), "_mcp_api should have get_exports_dir"
        assert hasattr(mod, "get_data_dir"), "_mcp_api should have get_data_dir"
        assert hasattr(mod, "get_workspace_dir"), "_mcp_api should have get_workspace_dir"
        assert hasattr(mod, "get_logs_dir"), "_mcp_api should have get_logs_dir"
        assert hasattr(mod, "anonymize"), "_mcp_api should have anonymize"
        assert hasattr(mod, "deanonymize"), "_mcp_api should have deanonymize"
        assert hasattr(mod, "cleanup_session"), "_mcp_api should have cleanup_session"
        assert hasattr(mod, "get_task_context"), "_mcp_api should have get_task_context"
        assert hasattr(mod, "is_anonymizer_available"), "_mcp_api should have is_anonymizer_available"
        assert hasattr(mod, "log_tool_call"), "_mcp_api should have log_tool_call"
        assert hasattr(mod, "clear_cache"), "_mcp_api should have clear_cache"
        assert hasattr(mod, "get_workspace_subdir"), "_mcp_api should have get_workspace_subdir"

    def test_mcp_api_stub_has_state_dir_alias(self):
        """_mcp_api.py has get_state_dir as alias for get_data_dir."""
        mcp_path = str(MCP_DIR)
        if mcp_path not in sys.path:
            sys.path.insert(0, mcp_path)

        if "_mcp_api" in sys.modules:
            del sys.modules["_mcp_api"]

        mod = importlib.import_module("_mcp_api")

        assert hasattr(mod, "get_state_dir"), "_mcp_api should have get_state_dir alias"
        assert mod.get_state_dir == mod.get_data_dir, "get_state_dir should be alias for get_data_dir"

    def test_mcp_api_file_exists(self):
        """_mcp_api.py file exists in mcp directory."""
        api_file = MCP_DIR / "_mcp_api.py"
        assert api_file.exists(), f"_mcp_api.py not found at {api_file}"

    def test_mcp_api_has_docstring(self):
        """_mcp_api.py has a module docstring."""
        api_file = MCP_DIR / "_mcp_api.py"
        content = api_file.read_text(encoding="utf-8")
        assert '"""' in content, "_mcp_api.py should have docstrings"
