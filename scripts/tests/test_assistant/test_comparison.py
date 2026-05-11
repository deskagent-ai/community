# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for assistant.routes.testing module.
Tests multi-backend comparison functionality.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestCompareRequest:
    """Tests for CompareRequest model."""

    def test_valid_request_with_all_fields(self):
        """Test creating a valid CompareRequest with all fields."""
        from assistant.routes.testing import CompareRequest

        request = CompareRequest(
            agent_name="daily_check",
            backends=["claude_sdk", "gemini"],
            dry_run=True,
            test_folder="TestData"
        )

        assert request.agent_name == "daily_check"
        assert request.backends == ["claude_sdk", "gemini"]
        assert request.dry_run is True
        assert request.test_folder == "TestData"

    def test_request_with_defaults(self):
        """Test that CompareRequest has correct defaults."""
        from assistant.routes.testing import CompareRequest

        request = CompareRequest(agent_name="test_agent")

        assert request.agent_name == "test_agent"
        assert request.backends is None  # Default: use all enabled
        assert request.dry_run is True  # Default: dry-run for safety
        assert request.test_folder is None


class TestRunSingleBackend:
    """Tests for run_single_backend function."""

    @pytest.mark.asyncio
    async def test_returns_result_dict(self):
        """Test that run_single_backend returns expected dict structure."""
        from assistant.routes.testing import run_single_backend

        # Mock config and agent
        mock_config = {
            "ai_backends": {
                "test_backend": {"type": "test", "enabled": True}
            }
        }

        # Mock load_agent
        mock_agent = {"content": "Test agent content"}

        with patch("assistant.routes.testing.load_config", return_value=mock_config), \
             patch("assistant.routes.testing.load_agent", return_value=mock_agent), \
             patch("ai_agent.call_agent") as mock_call:

            # Setup mock response
            mock_response = MagicMock()
            mock_response.success = True
            mock_response.content = "Test response"
            mock_response.input_tokens = 100
            mock_response.output_tokens = 50
            mock_response.cost_usd = 0.001
            mock_response.error = None
            mock_call.return_value = mock_response

            result = await run_single_backend(
                "test_agent",
                "test_backend",
                dry_run=True,
                config=mock_config
            )

            assert isinstance(result, dict)
            assert "backend" in result
            assert "success" in result
            assert "duration_sec" in result
            assert "tokens" in result
            assert "cost_usd" in result

    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_backend(self):
        """Test that unknown backend returns error."""
        from assistant.routes.testing import run_single_backend

        mock_config = {
            "ai_backends": {
                "existing_backend": {"type": "test"}
            }
        }

        result = await run_single_backend(
            "test_agent",
            "nonexistent_backend",
            dry_run=True,
            config=mock_config
        )

        assert result["success"] is False
        assert result["error"] is not None
        assert "unknown" in result["error"].lower() or "nonexistent" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_agent(self):
        """Test that unknown agent returns error."""
        from assistant.routes.testing import run_single_backend

        mock_config = {
            "ai_backends": {
                "test_backend": {"type": "test", "enabled": True}
            }
        }

        with patch("assistant.routes.testing.load_config", return_value=mock_config), \
             patch("assistant.routes.testing.load_agent", return_value=None):

            result = await run_single_backend(
                "nonexistent_agent",
                "test_backend",
                dry_run=True,
                config=mock_config
            )

            assert result["success"] is False
            assert result["error"] is not None
            assert "not found" in result["error"].lower()


class TestComparisonResultStructure:
    """Tests for comparison result data structure."""

    def test_result_has_required_fields(self):
        """Test that comparison result contains all required fields."""
        # Simulate a comparison result
        result = {
            "agent": "test_agent",
            "timestamp": "2025-01-03T10:30:00",
            "dry_run": True,
            "test_folder": None,
            "backends": {
                "claude_sdk": {
                    "success": True,
                    "duration_sec": 12.5,
                    "tokens": {"input": 1500, "output": 800},
                    "cost_usd": 0.045
                },
                "gemini": {
                    "success": True,
                    "duration_sec": 8.3,
                    "tokens": {"input": 1500, "output": 750},
                    "cost_usd": 0.018
                }
            },
            "winner": {
                "fastest": "gemini",
                "cheapest": "gemini",
                "most_tokens": "claude_sdk"
            },
            "summary": {
                "total_backends": 2,
                "successful": 2,
                "failed": 0
            }
        }

        # Verify structure
        assert "agent" in result
        assert "timestamp" in result
        assert "dry_run" in result
        assert "backends" in result
        assert "winner" in result
        assert "summary" in result

        # Verify backend result structure
        for backend_name, backend_data in result["backends"].items():
            assert "success" in backend_data
            assert "duration_sec" in backend_data
            assert "tokens" in backend_data
            assert "cost_usd" in backend_data

        # Verify winner structure
        assert "fastest" in result["winner"]
        assert "cheapest" in result["winner"]
        assert "most_tokens" in result["winner"]

        # Verify summary structure
        assert "total_backends" in result["summary"]
        assert "successful" in result["summary"]
        assert "failed" in result["summary"]

    def test_winner_calculation_fastest(self):
        """Test that fastest backend is correctly identified."""
        backends = {
            "backend_a": {"success": True, "duration_sec": 15.0},
            "backend_b": {"success": True, "duration_sec": 8.0},
            "backend_c": {"success": True, "duration_sec": 12.0}
        }

        successful = {k: v for k, v in backends.items() if v.get("success")}
        fastest = min(successful.items(), key=lambda x: x[1].get("duration_sec", float("inf")))

        assert fastest[0] == "backend_b"

    def test_winner_calculation_cheapest(self):
        """Test that cheapest backend is correctly identified."""
        backends = {
            "backend_a": {"success": True, "cost_usd": 0.05},
            "backend_b": {"success": True, "cost_usd": 0.02},
            "backend_c": {"success": True, "cost_usd": 0.03}
        }

        successful = {k: v for k, v in backends.items() if v.get("success")}
        with_cost = {k: v for k, v in successful.items() if v.get("cost_usd", 0) > 0}
        cheapest = min(with_cost.items(), key=lambda x: x[1].get("cost_usd", float("inf")))

        assert cheapest[0] == "backend_b"


class TestCompareEndpointRequiresDeveloperMode:
    """Tests for developer mode requirement."""

    @pytest.mark.asyncio
    async def test_compare_requires_developer_mode(self):
        """Test that /test/compare requires developer_mode to be enabled."""
        from fastapi import HTTPException
        from assistant.routes.testing import compare_backends, CompareRequest

        # Config with developer_mode disabled
        mock_config = {"developer_mode": False}

        with patch("assistant.routes.testing.load_config", return_value=mock_config):
            request = CompareRequest(agent_name="test_agent")

            with pytest.raises(HTTPException) as exc_info:
                await compare_backends(request)

            assert exc_info.value.status_code == 403
            assert "developer mode" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_list_comparisons_requires_developer_mode(self):
        """Test that /test/comparisons requires developer_mode."""
        from fastapi import HTTPException
        from assistant.routes.testing import list_comparisons

        mock_config = {"developer_mode": False}

        with patch("assistant.routes.testing.load_config", return_value=mock_config):
            with pytest.raises(HTTPException) as exc_info:
                await list_comparisons()

            assert exc_info.value.status_code == 403


class TestBackendsEndpoint:
    """Tests for /backends endpoint in system routes."""

    def test_backends_response_structure(self):
        """Test that /backends response has expected structure."""
        # Simulate expected response
        response = {
            "enabled": ["claude_sdk", "gemini"],
            "all": ["claude_sdk", "gemini", "qwen", "mistral"],
            "default": "claude_sdk"
        }

        assert "enabled" in response
        assert "all" in response
        assert "default" in response
        assert isinstance(response["enabled"], list)
        assert isinstance(response["all"], list)
