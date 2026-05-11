# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for resolve_anonymization_setting() - Central Anonymization Decision.

This tests the 8 priority scenarios as defined in planfeature-009:

| # | Global UI | Agent Frontmatter | Backend Default | Presidio | Expected | Source |
|---|-----------|-------------------|-----------------|----------|----------|--------|
| 1 | OFF | - | true | check | OFF | global-off |
| 2 | OFF | true | true | check | OFF | global-off |
| 3 | OFF | false | true | check | OFF | agent-off |
| 4 | ON | - | true | check | ON | backend |
| 5 | ON | - | false | check | OFF | backend-off |
| 6 | ON | true | false | check | ON | agent-on |
| 7 | ON | false | true | check | OFF | agent-off |
| 8 | ON | true | true | x | OFF | presidio-unavailable |
"""

import pytest
from unittest.mock import patch


class TestResolveAnonymizationSetting:
    """Tests for the central anonymization decision function."""

    @pytest.fixture
    def mock_presidio_available(self):
        """Mock Presidio as available."""
        with patch("ai_agent.anonymizer.is_available", return_value=True):
            yield

    @pytest.fixture
    def mock_presidio_unavailable(self):
        """Mock Presidio as unavailable."""
        with patch("ai_agent.anonymizer.is_available", return_value=False):
            yield

    def test_scenario_1_global_off_no_agent_setting(self, mock_presidio_available):
        """Scenario 1: Global OFF, no agent setting, backend true -> OFF (global-off)."""
        from ai_agent.anonymizer import resolve_anonymization_setting

        config = {"anonymization": {"enabled": False}}
        agent_config = {"anonymize": True}  # Backend default
        task_config = {}  # No agent setting

        result, source = resolve_anonymization_setting(
            config, agent_config, task_config, "test_agent", "agent", "claude_sdk"
        )

        assert result is False
        assert source == "global-off"

    def test_scenario_2_global_off_agent_true(self, mock_presidio_available):
        """Scenario 2: Global OFF, agent explicitly true -> OFF (global-off)."""
        from ai_agent.anonymizer import resolve_anonymization_setting

        config = {"anonymization": {"enabled": False}}
        agent_config = {"anonymize": True}
        task_config = {"anonymize": True}  # Agent wants ON

        result, source = resolve_anonymization_setting(
            config, agent_config, task_config, "test_agent", "agent", "claude_sdk"
        )

        assert result is False
        assert source == "global-off"

    def test_scenario_3_global_off_agent_false(self, mock_presidio_available):
        """Scenario 3: Global OFF, agent explicitly false -> OFF (agent-off)."""
        from ai_agent.anonymizer import resolve_anonymization_setting

        config = {"anonymization": {"enabled": False}}
        agent_config = {"anonymize": True}
        task_config = {"anonymize": False}  # Agent explicitly OFF

        result, source = resolve_anonymization_setting(
            config, agent_config, task_config, "test_agent", "agent", "claude_sdk"
        )

        assert result is False
        assert source == "agent-off"

    def test_scenario_4_global_on_backend_true(self, mock_presidio_available):
        """Scenario 4: Global ON, no agent setting, backend true -> ON (backend)."""
        from ai_agent.anonymizer import resolve_anonymization_setting

        config = {"anonymization": {"enabled": True}}
        agent_config = {"anonymize": True}
        task_config = {}  # No agent setting

        result, source = resolve_anonymization_setting(
            config, agent_config, task_config, "test_agent", "agent", "claude_sdk"
        )

        assert result is True
        assert source == "backend"

    def test_scenario_5_global_on_backend_false(self, mock_presidio_available):
        """Scenario 5: Global ON, no agent setting, backend false -> OFF (backend-off)."""
        from ai_agent.anonymizer import resolve_anonymization_setting

        config = {"anonymization": {"enabled": True}}
        agent_config = {"anonymize": False}  # Backend says OFF
        task_config = {}  # No agent setting

        result, source = resolve_anonymization_setting(
            config, agent_config, task_config, "test_agent", "agent", "claude_sdk"
        )

        assert result is False
        assert source == "backend-off"

    def test_scenario_6_global_on_agent_true_backend_false(self, mock_presidio_available):
        """Scenario 6: Global ON, agent true, backend false -> ON (agent-on)."""
        from ai_agent.anonymizer import resolve_anonymization_setting

        config = {"anonymization": {"enabled": True}}
        agent_config = {"anonymize": False}  # Backend says OFF
        task_config = {"anonymize": True}  # Agent wants ON

        result, source = resolve_anonymization_setting(
            config, agent_config, task_config, "test_agent", "agent", "claude_sdk"
        )

        assert result is True
        assert source == "agent-on"

    def test_scenario_7_global_on_agent_false_backend_true(self, mock_presidio_available):
        """Scenario 7: Global ON, agent false, backend true -> OFF (agent-off)."""
        from ai_agent.anonymizer import resolve_anonymization_setting

        config = {"anonymization": {"enabled": True}}
        agent_config = {"anonymize": True}  # Backend says ON
        task_config = {"anonymize": False}  # Agent explicitly OFF

        result, source = resolve_anonymization_setting(
            config, agent_config, task_config, "test_agent", "agent", "claude_sdk"
        )

        assert result is False
        assert source == "agent-off"

    def test_scenario_8_presidio_unavailable(self, mock_presidio_unavailable):
        """Scenario 8: Presidio not available -> OFF (presidio-unavailable)."""
        from ai_agent.anonymizer import resolve_anonymization_setting

        config = {"anonymization": {"enabled": True}}
        agent_config = {"anonymize": True}
        task_config = {"anonymize": True}

        result, source = resolve_anonymization_setting(
            config, agent_config, task_config, "test_agent", "agent", "claude_sdk"
        )

        assert result is False
        assert source == "presidio-unavailable"


class TestShouldAnonymizeBackwardCompatibility:
    """Tests for backward compatibility of should_anonymize()."""

    @pytest.fixture
    def mock_presidio_available(self):
        """Mock Presidio as available."""
        with patch("ai_agent.anonymizer.is_available", return_value=True):
            yield

    def test_should_anonymize_global_off(self, mock_presidio_available):
        """should_anonymize returns False when global is off."""
        from ai_agent.anonymizer import should_anonymize

        config = {
            "anonymization": {"enabled": False},
            "ai_backends": {"claude_sdk": {"anonymize": True}}
        }

        result = should_anonymize(config, "test_agent", "agent", "claude_sdk")
        assert result is False

    def test_should_anonymize_global_on_backend_true(self, mock_presidio_available):
        """should_anonymize returns True when global is on and backend is true."""
        from ai_agent.anonymizer import should_anonymize

        config = {
            "anonymization": {"enabled": True},
            "ai_backends": {"claude_sdk": {"anonymize": True}}
        }

        result = should_anonymize(config, "test_agent", "agent", "claude_sdk")
        assert result is True

    def test_should_anonymize_global_on_backend_false(self, mock_presidio_available):
        """should_anonymize returns False when global is on but backend is false."""
        from ai_agent.anonymizer import should_anonymize

        config = {
            "anonymization": {"enabled": True},
            "ai_backends": {"claude_sdk": {"anonymize": False}}
        }

        result = should_anonymize(config, "test_agent", "agent", "claude_sdk")
        assert result is False
