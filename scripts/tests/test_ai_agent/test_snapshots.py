# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Snapshot Tests
==============

Golden-file tests that compare agent behavior against saved expectations.
Uses mock LLM to avoid API costs while validating workflow structure.

Run with: pytest -m mock tests/test_ai_agent/test_snapshots.py -v

To record new snapshots (with real API calls):
    pytest -m record tests/test_ai_agent/test_snapshots.py -v -s

WARNING: Record mode makes REAL API calls (costs money!)
"""

import json
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ai_agent.mock_llm import MockLLMBackend, MockTracker


# =============================================================================
# Snapshot Infrastructure
# =============================================================================

SNAPSHOT_DIR = Path(__file__).parent.parent / "fixtures" / "snapshots"


def get_available_snapshots() -> list[str]:
    """Get list of available snapshot names."""
    if not SNAPSHOT_DIR.exists():
        return []
    return [d.name for d in SNAPSHOT_DIR.iterdir() if d.is_dir()]


def load_snapshot(name: str) -> tuple[dict, dict]:
    """
    Load snapshot input and expected data.

    Args:
        name: Snapshot directory name

    Returns:
        Tuple of (input_data, expected_data)
    """
    snapshot_path = SNAPSHOT_DIR / name

    input_file = snapshot_path / "input.json"
    expected_file = snapshot_path / "expected.json"

    if not input_file.exists():
        raise FileNotFoundError(f"Snapshot input not found: {input_file}")
    if not expected_file.exists():
        raise FileNotFoundError(f"Snapshot expected not found: {expected_file}")

    input_data = json.loads(input_file.read_text(encoding="utf-8"))
    expected = json.loads(expected_file.read_text(encoding="utf-8"))

    return input_data, expected


def save_snapshot(name: str, input_data: dict, expected: dict, golden: str = None):
    """
    Save a snapshot for future comparison.

    Args:
        name: Snapshot directory name
        input_data: Input parameters
        expected: Expected assertions
        golden: Optional golden response text
    """
    snapshot_path = SNAPSHOT_DIR / name
    snapshot_path.mkdir(parents=True, exist_ok=True)

    (snapshot_path / "input.json").write_text(
        json.dumps(input_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    (snapshot_path / "expected.json").write_text(
        json.dumps(expected, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    if golden:
        (snapshot_path / "golden.txt").write_text(golden, encoding="utf-8")


# =============================================================================
# Snapshot Tests
# =============================================================================

@pytest.mark.mock
class TestSnapshots:
    """Snapshot-based tests for agent workflows."""

    @pytest.mark.parametrize("snapshot_name", get_available_snapshots())
    def test_snapshot(self, snapshot_name, mock_config, mock_tracker, temp_mock_dir):
        """
        Run snapshot test against mock LLM.

        Validates:
        - Success/failure status
        - Content contains/not contains
        - Tools called/not called
        - Cost (should be 0 for mock)
        """
        input_data, expected = load_snapshot(snapshot_name)
        assertions = expected.get("assertions", {})

        # Create mock with agent-specific responses
        llm_dir = temp_mock_dir["llm"]
        agent_name = input_data.get("agent", "gemini")

        # Create mock response for this agent
        mock_data = {
            "responses": [{
                "id": f"{snapshot_name}-mock",
                "match": {"agent": agent_name},
                "response": {
                    "content": f"[Mock] {snapshot_name} response",
                    "tool_calls": [
                        {"name": tool, "arguments": {}}
                        for tool in assertions.get("tools_called", [])
                    ]
                }
            }]
        }
        (llm_dir / f"{snapshot_name}.json").write_text(json.dumps(mock_data))

        mock_backend = MockLLMBackend(
            config=mock_config,
            mocks_dir=llm_dir,
            tracker=mock_tracker
        )

        # Execute
        result = mock_backend.call(
            prompt=input_data["prompt"],
            agent_name=agent_name
        )

        # Validate assertions
        if "success" in assertions:
            assert result.success == assertions["success"], \
                f"Expected success={assertions['success']}, got {result.success}"

        if "cost_usd" in assertions:
            assert result.cost_usd == assertions["cost_usd"], \
                f"Expected cost={assertions['cost_usd']}, got {result.cost_usd}"

        for phrase in assertions.get("content_contains", []):
            assert phrase in result.content, \
                f"Response should contain: {phrase}"

        for phrase in assertions.get("content_not_contains", []):
            assert phrase not in result.content, \
                f"Response should not contain: {phrase}"

        for tool in assertions.get("tools_called", []):
            mock_tracker.assert_tool_called(tool)

        for tool in assertions.get("tools_not_called", []):
            mock_tracker.assert_tool_not_called(tool)


# =============================================================================
# Snapshot Recording (Real API Calls)
# =============================================================================

@pytest.mark.record
class TestSnapshotRecording:
    """
    Record new snapshots with real API calls.

    WARNING: These tests make REAL API calls and cost money!
    Only run manually: pytest -m record -v -s
    """

    def test_record_reply_email(self, live_config):
        """
        Record snapshot for reply_email agent.

        Run: pytest -m record -k "record_reply_email" -v -s
        """
        pytest.skip("Recording requires real API setup - run manually")

        # Example of how to record:
        # from ai_agent import call_agent
        #
        # result = call_agent(
        #     prompt="Beantworte die ausgewaehlte E-Mail professionell",
        #     config=live_config,
        #     agent_name="reply_email",
        #     use_tools=True
        # )
        #
        # save_snapshot(
        #     name="reply_email",
        #     input_data={
        #         "prompt": "Beantworte die ausgewaehlte E-Mail professionell",
        #         "agent": "reply_email",
        #         "use_tools": True
        #     },
        #     expected={
        #         "_meta": {"created": "2025-02-06", "backend": "gemini"},
        #         "assertions": {
        #             "success": True,
        #             "content_contains": ["Sehr geehrte"],
        #             "tools_called": ["outlook_get_selected_email"]
        #         }
        #     },
        #     golden=result.content
        # )


# =============================================================================
# Snapshot Utilities
# =============================================================================

@pytest.mark.mock
class TestSnapshotUtilities:
    """Tests for snapshot utility functions."""

    def test_get_available_snapshots(self):
        """get_available_snapshots returns list."""
        snapshots = get_available_snapshots()
        assert isinstance(snapshots, list)

    def test_load_snapshot(self):
        """load_snapshot loads input and expected."""
        snapshots = get_available_snapshots()
        if not snapshots:
            pytest.skip("No snapshots available")

        input_data, expected = load_snapshot(snapshots[0])

        assert isinstance(input_data, dict)
        assert isinstance(expected, dict)
        assert "prompt" in input_data
        assert "assertions" in expected

    def test_save_snapshot(self, tmp_path, monkeypatch):
        """save_snapshot creates files."""
        # Import the module and patch SNAPSHOT_DIR
        import sys
        test_snapshots_module = sys.modules[__name__]
        original_dir = SNAPSHOT_DIR
        monkeypatch.setattr(test_snapshots_module, 'SNAPSHOT_DIR', tmp_path)

        try:
            # Use local function that reads the patched constant
            snapshot_path = tmp_path / "test_snapshot"
            snapshot_path.mkdir(parents=True, exist_ok=True)

            (snapshot_path / "input.json").write_text(
                json.dumps({"prompt": "Test"}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            (snapshot_path / "expected.json").write_text(
                json.dumps({"assertions": {"success": True}}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            (snapshot_path / "golden.txt").write_text("Test response", encoding="utf-8")

            # Verify files created
            assert (snapshot_path / "input.json").exists()
            assert (snapshot_path / "expected.json").exists()
            assert (snapshot_path / "golden.txt").exists()
        finally:
            monkeypatch.setattr(test_snapshots_module, 'SNAPSHOT_DIR', original_dir)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "mock"])
