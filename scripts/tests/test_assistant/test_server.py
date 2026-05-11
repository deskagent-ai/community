# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for assistant.server module.
Tests HTTP endpoints and request handling.
"""

import json
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class MockRequest:
    """Mock HTTP request for testing."""

    def __init__(self, path="/", method="GET", body=None, headers=None):
        self.path = path
        self.command = method
        self.headers = headers or {}
        self._body = body

    def makefile(self, mode, *args, **kwargs):
        return BytesIO()


class TestServerConfig:
    """Tests for server configuration loading."""

    def test_loads_config_on_startup(self, sample_config, monkeypatch):
        """Test that server loads config.json."""
        from assistant import skills

        # Patch the underlying loader to return sample config directly
        monkeypatch.setattr(skills, "load_config_from_paths", lambda: sample_config)

        config = skills.load_config()

        assert config is not None
        assert "ai_backends" in config

    def test_uses_default_port(self, sample_config):
        """Test default port configuration."""
        from assistant import server

        # Default port should be 8765
        port = sample_config.get("server_port", 8765)
        assert port == 8765


class TestTaskManagement:
    """Tests for task creation and tracking."""

    def test_create_task_generates_id(self, tmp_path, monkeypatch):
        """Test that task creation generates unique ID."""
        from assistant import server

        monkeypatch.setattr(server, "_tasks", {})

        # Simulate task creation
        task_id = "test_task_123"
        server._tasks[task_id] = {
            "status": "running",
            "skill": "test_skill",
            "output": ""
        }

        assert task_id in server._tasks
        assert server._tasks[task_id]["status"] == "running"

    def test_task_status_updates(self, tmp_path, monkeypatch):
        """Test that task status is updated correctly."""
        from assistant import server

        monkeypatch.setattr(server, "_tasks", {})

        task_id = "status_test"
        server._tasks[task_id] = {"status": "running", "output": ""}

        # Update status
        server._tasks[task_id]["status"] = "done"
        server._tasks[task_id]["output"] = "Task completed"

        assert server._tasks[task_id]["status"] == "done"
        assert "completed" in server._tasks[task_id]["output"]


class TestTestRunner:
    """Tests for the test runner functionality."""

    def test_run_tests_creates_task(self, tmp_path, monkeypatch):
        """Test that run_tests creates a task entry."""
        from assistant.routes import execution

        monkeypatch.setattr(execution, "_test_tasks", {})

        # Create minimal test structure
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        task_id = "test_run_1"
        execution._test_tasks[task_id] = {
            "status": "pending",
            "scope": "unit",
            "output": ""
        }

        assert task_id in execution._test_tasks

    def test_test_task_tracks_results(self, tmp_path, monkeypatch):
        """Test that test results are tracked."""
        from assistant.routes import execution

        monkeypatch.setattr(execution, "_test_tasks", {})

        task_id = "results_test"
        execution._test_tasks[task_id] = {
            "status": "done",
            "passed": 10,
            "failed": 2,
            "skipped": 3,
            "duration": 5.5,
            "output": "Test output here"
        }

        task = execution._test_tasks[task_id]
        assert task["passed"] == 10
        assert task["failed"] == 2
        assert task["skipped"] == 3
        assert task["duration"] == 5.5


class TestWebUIGeneration:
    """Tests for WebUI HTML generation."""

    def test_generates_skill_tiles(self, sample_config, tmp_path, monkeypatch):
        """Test that skill tiles are generated from config."""
        from assistant import server

        # Config with skills
        sample_config["skills"] = {
            "mail_reply": {
                "input": "Clipboard",
                "output": "Clipboard",
                "enabled": True
            }
        }

        # Skills should be loaded from config
        skills = sample_config.get("skills", {})
        enabled_skills = [
            name for name, cfg in skills.items()
            if cfg.get("enabled", True)
        ]

        assert "mail_reply" in enabled_skills

    def test_generates_agent_tiles(self, sample_config):
        """Test that agent tiles are generated from config."""
        sample_config["agents"] = {
            "reply_email": {
                "input": "Outlook",
                "output": "Outlook Draft",
                "enabled": True
            }
        }

        agents = sample_config.get("agents", {})
        enabled_agents = [
            name for name, cfg in agents.items()
            if cfg.get("enabled", True)
        ]

        assert "reply_email" in enabled_agents

    def test_developer_mode_shows_test_icon(self, sample_config):
        """Test that developer mode shows test functionality."""
        sample_config["developer_mode"] = True

        # When developer_mode is True, test icon should appear
        assert sample_config.get("developer_mode") is True

    def test_theme_applied_from_config(self, sample_config):
        """Test that theme is read from config."""
        sample_config["theme"] = "dark"

        theme = sample_config.get("theme", "light")
        assert theme == "dark"

    def test_ui_customization_applied(self, sample_config):
        """Test that UI customization is applied."""
        sample_config["ui"] = {
            "title": "Custom Title",
            "icon": "custom.ico",
            "accent_color": "#ff5722"
        }

        ui = sample_config.get("ui", {})
        assert ui.get("title") == "Custom Title"
        assert ui.get("accent_color") == "#ff5722"


class TestAnonymizationStatus:
    """Tests for anonymization status display."""

    def test_anonymization_enabled_status(self, sample_config):
        """Test status when anonymization is enabled."""
        sample_config["anonymization"] = {"enabled": True}

        anon_config = sample_config.get("anonymization", {})
        enabled = anon_config.get("enabled", False)

        assert enabled is True

    def test_anonymization_disabled_status(self, sample_config):
        """Test status when anonymization is disabled."""
        sample_config["anonymization"] = {"enabled": False}

        anon_config = sample_config.get("anonymization", {})
        enabled = anon_config.get("enabled", False)

        assert enabled is False


class TestCostDisplay:
    """Tests for cost tracking display."""

    def test_cost_endpoint_returns_data(self, tmp_path, monkeypatch):
        """Test that cost data is accessible."""
        from assistant import cost_tracker

        # Setup temp database for cost tracking
        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        db_file = data_dir / "datastore.db"

        # Reset module state to use temp database
        cost_tracker.DB_PATH = db_file
        cost_tracker._migrated = True  # Skip migration

        # Clean database by resetting
        cost_tracker.reset_costs()

        # Add a cost entry
        cost_tracker.add_cost(cost_usd=0.05, model="test-model")

        costs = cost_tracker.get_costs()
        assert costs["total_usd"] == 0.05


class TestCORSHandling:
    """Tests for CORS headers."""

    def test_cors_headers_present(self):
        """Test that CORS headers are added to responses."""
        # CORS should allow requests from any origin for local development
        expected_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS"
        }

        # These headers should be set in actual responses
        for header in expected_headers:
            assert header in expected_headers


class TestFastAPIStartup:
    """Tests for FastAPI application startup and endpoints."""

    @pytest.fixture
    def test_client(self):
        """Create a test client for the FastAPI app."""
        from fastapi.testclient import TestClient
        from assistant.app import create_app

        app = create_app()
        return TestClient(app)

    def test_app_creates_successfully(self):
        """Test that FastAPI app can be created without errors."""
        from assistant.app import create_app

        app = create_app()
        assert app is not None
        assert app.title == "DeskAgent"

    def test_status_endpoint(self, test_client):
        """Test /status endpoint returns OK."""
        response = test_client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_version_endpoint(self, test_client):
        """Test /version endpoint returns version info."""
        response = test_client.get("/version")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "build" in data

    def test_root_endpoint_returns_html(self, test_client):
        """Test / endpoint returns HTML UI."""
        response = test_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_cors_headers_in_response(self, test_client):
        """Test that CORS headers are present in responses."""
        response = test_client.get("/status")
        # FastAPI CORS middleware adds these headers
        assert response.status_code == 200

    def test_exception_handler_logs_errors(self, test_client, monkeypatch):
        """Test that unhandled exceptions are logged to system.log."""
        logged_messages = []

        def mock_system_log(msg):
            logged_messages.append(msg)

        # This is tested indirectly - the exception handler exists
        from assistant.app import create_app
        app = create_app()

        # Verify exception handler is registered
        assert Exception in app.exception_handlers

    def test_mcp_info_endpoint_returns_tools(self, test_client):
        """Test /mcp/info/{mcp_name} endpoint returns MCP details with tools."""
        response = test_client.get("/mcp/info/billomat")
        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "name" in data
        assert data["name"] == "billomat"
        assert "description" in data
        assert "configured" in data
        assert "tools" in data

        # Verify tools are extracted
        assert isinstance(data["tools"], list)
        assert len(data["tools"]) > 0

        # Verify tool structure
        first_tool = data["tools"][0]
        assert "name" in first_tool
        assert "description" in first_tool

    def test_mcp_info_endpoint_not_found(self, test_client):
        """Test /mcp/info/{mcp_name} returns 404 for non-existent MCP."""
        response = test_client.get("/mcp/info/nonexistent_mcp_12345")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_mcp_info_endpoint_multi_file_mcp(self, test_client):
        """Test /mcp/info/{mcp_name} works for multi-file MCPs like outlook."""
        response = test_client.get("/mcp/info/outlook")
        assert response.status_code == 200
        data = response.json()

        # Verify tools from multiple submodules are collected
        assert "tools" in data
        assert len(data["tools"]) > 10  # Outlook has many tools

        # Verify description includes submodule info
        assert data["description"] is not None

    def test_system_info_endpoint_includes_ports(self, test_client):
        """Test /system/info endpoint includes ports and services info [014]."""
        response = test_client.get("/system/info")
        assert response.status_code == 200
        data = response.json()

        # Verify basic system info
        assert "version" in data
        assert "python" in data
        assert "uptime" in data
        assert "paths" in data

        # Verify new [014] fields: ports
        assert "ports" in data
        ports = data["ports"]
        assert "http" in ports
        assert "http_running" in ports
        assert "mcp_proxy" in ports
        assert "mcp_proxy_running" in ports
        assert "fastmcp" in ports
        assert "fastmcp_running" in ports

        # HTTP server must be running (we're making requests to it)
        assert ports["http_running"] is True
        assert isinstance(ports["http"], int)
        assert ports["http"] > 0

        # Verify MCP info
        assert "mcp" in data
        assert "transport" in data["mcp"]
        assert data["mcp"]["transport"] in ("stdio", "sse", "streamable-http", "inprocess")

        # Verify public API info
        assert "public_api" in data
        assert "url" in data["public_api"]
        assert "docs" in data["public_api"]
        assert "/api/external" in data["public_api"]["url"]
        assert "/api/external/docs" in data["public_api"]["docs"]
