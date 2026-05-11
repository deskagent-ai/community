# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for assistant.cost_tracker module.
Tests cost tracking and persistence using SQLite.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def cost_tracker_setup(tmp_path, monkeypatch):
    """Setup cost_tracker with temp database."""
    from assistant import cost_tracker

    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db_file = data_dir / "datastore.db"

    # Reset module state
    cost_tracker.DB_PATH = db_file
    cost_tracker._migrated = True  # Skip migration

    # Clean database by resetting
    cost_tracker.reset_costs()

    return cost_tracker, db_file, data_dir


@pytest.fixture
def sample_costs_data():
    """Sample cost data for testing."""
    return {
        "total_usd": 1.5,
        "total_input_tokens": 10000,
        "total_output_tokens": 5000,
        "total_audio_seconds": 0,
        "task_count": 5,
        "by_model": {
            "claude-sonnet-4": {"cost_usd": 1.0, "input_tokens": 8000, "output_tokens": 4000, "task_count": 3},
            "gemini-2.5-pro": {"cost_usd": 0.5, "input_tokens": 2000, "output_tokens": 1000, "task_count": 2}
        }
    }


class TestAddCost:
    """Tests for add_cost function."""

    def test_add_cost_simple(self, cost_tracker_setup):
        """Test adding a simple cost entry."""
        cost_tracker, db_file, data_dir = cost_tracker_setup

        cost_tracker.add_cost(
            cost_usd=0.01,
            input_tokens=1000,
            output_tokens=500,
            model="claude-sonnet-4"
        )

        costs = cost_tracker.get_costs()
        assert costs["total_usd"] == 0.01
        assert costs["total_input_tokens"] == 1000
        assert costs["total_output_tokens"] == 500
        assert costs["task_count"] == 1

    def test_add_cost_accumulates(self, cost_tracker_setup):
        """Test that costs accumulate correctly."""
        cost_tracker, db_file, data_dir = cost_tracker_setup

        cost_tracker.add_cost(cost_usd=0.01)
        cost_tracker.add_cost(cost_usd=0.02)
        cost_tracker.add_cost(cost_usd=0.03)

        costs = cost_tracker.get_costs()
        assert costs["total_usd"] == pytest.approx(0.06, abs=0.001)
        assert costs["task_count"] == 3

    def test_add_cost_tracks_by_model(self, cost_tracker_setup):
        """Test that costs are tracked per model."""
        cost_tracker, db_file, data_dir = cost_tracker_setup

        cost_tracker.add_cost(cost_usd=0.01, model="claude-sonnet-4")
        cost_tracker.add_cost(cost_usd=0.02, model="gemini-2.5-pro")
        cost_tracker.add_cost(cost_usd=0.01, model="claude-sonnet-4")

        costs = cost_tracker.get_costs()
        assert "claude-sonnet-4" in costs["by_model"]
        assert "gemini-2.5-pro" in costs["by_model"]
        assert costs["by_model"]["claude-sonnet-4"]["cost_usd"] == pytest.approx(0.02, abs=0.001)
        assert costs["by_model"]["claude-sonnet-4"]["task_count"] == 2


class TestGetCosts:
    """Tests for get_costs function."""

    def test_get_costs_empty(self, cost_tracker_setup):
        """Test getting costs when no data exists."""
        cost_tracker, db_file, data_dir = cost_tracker_setup

        costs = cost_tracker.get_costs()

        assert costs["total_usd"] == 0.0
        assert costs["task_count"] == 0


class TestResetCosts:
    """Tests for reset_costs function."""

    def test_reset_clears_all(self, cost_tracker_setup):
        """Test that reset clears all cost data."""
        cost_tracker, db_file, data_dir = cost_tracker_setup

        # Add some costs
        cost_tracker.add_cost(cost_usd=1.0, input_tokens=10000)

        # Reset
        cost_tracker.reset_costs()

        # Verify reset
        costs = cost_tracker.get_costs()
        assert costs["total_usd"] == 0.0
        assert costs["total_input_tokens"] == 0
        assert costs["task_count"] == 0


class TestPersistence:
    """Tests for cost data persistence."""

    def test_costs_saved_to_database(self, cost_tracker_setup):
        """Test that costs are persisted to database."""
        cost_tracker, db_file, data_dir = cost_tracker_setup

        cost_tracker.add_cost(cost_usd=0.05, model="test-model")

        # Verify database was created and contains data
        assert db_file.exists()

        # Get costs from a fresh query
        costs = cost_tracker.get_costs()
        assert costs["total_usd"] == 0.05

    def test_costs_persist_across_calls(self, cost_tracker_setup):
        """Test that costs persist across multiple get_costs calls."""
        cost_tracker, db_file, data_dir = cost_tracker_setup

        # Add cost
        cost_tracker.add_cost(cost_usd=1.5, input_tokens=10000, output_tokens=5000)

        # Get costs multiple times
        costs1 = cost_tracker.get_costs()
        costs2 = cost_tracker.get_costs()

        assert costs1["total_usd"] == 1.5
        assert costs2["total_usd"] == 1.5
        assert costs1["task_count"] == 1


class TestGetSummary:
    """Tests for get_summary function."""

    def test_summary_format(self, cost_tracker_setup):
        """Test summary returns expected format."""
        cost_tracker, db_file, data_dir = cost_tracker_setup

        cost_tracker.add_cost(cost_usd=0.1, input_tokens=1000, output_tokens=500)

        summary = cost_tracker.get_summary()

        assert "total_usd" in summary
        assert "today_usd" in summary
        assert "total_tasks" in summary
        assert "total_tokens" in summary
        assert summary["total_tokens"] == 1500


class TestByBackend:
    """Tests for backend tracking."""

    def test_tracks_by_backend(self, cost_tracker_setup):
        """Test that costs are tracked per backend."""
        cost_tracker, db_file, data_dir = cost_tracker_setup

        cost_tracker.add_cost(cost_usd=0.01, backend="claude_sdk")
        cost_tracker.add_cost(cost_usd=0.02, backend="gemini")
        cost_tracker.add_cost(cost_usd=0.01, backend="claude_sdk")

        costs = cost_tracker.get_costs()
        assert "claude_sdk" in costs["by_backend"]
        assert "gemini" in costs["by_backend"]
        assert costs["by_backend"]["claude_sdk"]["cost_usd"] == pytest.approx(0.02, abs=0.001)
        assert costs["by_backend"]["claude_sdk"]["task_count"] == 2


class TestAudioTracking:
    """Tests for audio/transcription tracking."""

    def test_tracks_audio_seconds(self, cost_tracker_setup):
        """Test that audio seconds are tracked."""
        cost_tracker, db_file, data_dir = cost_tracker_setup

        cost_tracker.add_cost(cost_usd=0.01, audio_seconds=60.5, model="whisper-1")

        costs = cost_tracker.get_costs()
        assert costs["total_audio_seconds"] == 60.5
        assert costs["by_model"]["whisper-1"]["audio_seconds"] == 60.5
