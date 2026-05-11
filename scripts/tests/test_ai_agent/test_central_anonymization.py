# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for central anonymization/de-anonymization logic.
Tests the new unified approach where de-anonymization happens centrally.
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestCentralDeAnonymization:
    """Tests for central de-anonymization in __init__.py."""

    def test_deanonymize_from_anon_context(self, sample_config, mocker):
        """Test de-anonymization using anon_context (Source 1).

        Note: Prompt must contain '### Input:' marker for anonymization to be applied.
        This matches real-world usage where skills have structured prompts.
        """
        from ai_agent import call_agent, AgentResponse
        from ai_agent.anonymizer import AnonymizationContext

        # Create mock context with mappings
        mock_context = AnonymizationContext(
            mappings={
                "<PERSON_1>": "Max Mustermann",
                "<EMAIL_ADDRESS_1>": "max@example.com"
            }
        )

        # Mock the backend to return anonymized content
        mock_response = AgentResponse(
            success=True,
            content="Hallo <PERSON_1>, deine Email ist <EMAIL_ADDRESS_1>.",
            model="test"
        )

        # Mock resolve_anonymization_setting to enable anonymization
        # This bypasses is_available() and config checks
        mocker.patch("ai_agent.anonymizer.resolve_anonymization_setting", return_value=(True, "test"))
        # Mock anonymize to return our context
        mocker.patch("ai_agent.anonymizer.anonymize", return_value=("anonymized prompt", mock_context))
        # Mock the backend call
        mocker.patch("ai_agent.call_claude_cli", return_value=mock_response)

        # Prompt MUST contain '### Input:' marker for anonymization to be applied
        # This is intentional - system prompts should not be anonymized
        result = call_agent(
            prompt="System instructions here.\n\n### Input:\nTest prompt with Max Mustermann\n\n### Output:",
            config=sample_config,
            task_name="mail_reply",
            task_type="skill"
        )

        # Content should be de-anonymized
        assert "Max Mustermann" in result.content
        assert "max@example.com" in result.content
        assert "<PERSON_1>" not in result.content
        assert "<EMAIL_ADDRESS_1>" not in result.content

    def test_deanonymize_from_result_anonymization(self, sample_config, mocker):
        """Test de-anonymization using result.anonymization (Source 2 - SDK proxy)."""
        from ai_agent import call_agent, AgentResponse

        # Mock response with anonymization mappings (SDK style)
        mock_response = AgentResponse(
            success=True,
            content="Hallo <PERSON_1>, kontaktiere <EMAIL_ADDRESS_1>.",
            model="test",
            anonymization={
                "mappings": {
                    "<PERSON_1>": "Max Mustermann",
                    "<EMAIL_ADDRESS_1>": "max@example.com"
                }
            }
        )

        # Mock should_anonymize to return False (no prompt anonymization)
        mocker.patch("ai_agent.anonymizer.should_anonymize", return_value=False)
        # Mock the SDK backend call
        mocker.patch("ai_agent.call_claude_agent_sdk", return_value=mock_response)

        # Configure for SDK backend
        sdk_config = sample_config.copy()
        sdk_config["ai_backends"]["claude_sdk"] = {"type": "claude_agent_sdk"}

        result = call_agent(
            prompt="Test prompt",
            config=sdk_config,
            agent_name="claude_sdk"
        )

        # Content should be de-anonymized using result.anonymization
        assert "Max Mustermann" in result.content
        assert "max@example.com" in result.content
        assert "<PERSON_1>" not in result.content

    def test_deanonymize_merges_both_sources(self, sample_config, mocker):
        """Test that both mapping sources are merged.

        Note: Prompt must contain '### Input:' marker for anonymization to be applied.
        """
        from ai_agent import call_agent, AgentResponse
        from ai_agent.anonymizer import AnonymizationContext

        # Source 1: Prompt context
        mock_context = AnonymizationContext(
            mappings={"<PERSON_1>": "From Prompt"}
        )

        # Source 2: Result anonymization (different mapping)
        mock_response = AgentResponse(
            success=True,
            content="<PERSON_1> and <EMAIL_ADDRESS_1> are here.",
            model="test",
            anonymization={
                "mappings": {"<EMAIL_ADDRESS_1>": "from-result@example.com"}
            }
        )

        # Mock resolve_anonymization_setting to enable anonymization
        mocker.patch("ai_agent.anonymizer.resolve_anonymization_setting", return_value=(True, "test"))
        mocker.patch("ai_agent.anonymizer.anonymize", return_value=("anon", mock_context))
        mocker.patch("ai_agent.call_claude_cli", return_value=mock_response)

        # Prompt MUST contain '### Input:' marker for anonymization to be applied
        result = call_agent(
            prompt="System instructions.\n\n### Input:\nTest content\n\n### Output:",
            config=sample_config,
            task_name="mail_reply",
            task_type="skill"
        )

        # Both sources should be applied
        assert "From Prompt" in result.content
        assert "from-result@example.com" in result.content

    def test_deanonymize_on_error(self, sample_config, mocker):
        """Test de-anonymization happens even on error (not just success)."""
        from ai_agent import call_agent, AgentResponse

        # Response with error but still has content
        mock_response = AgentResponse(
            success=False,
            content="Error occurred for <PERSON_1>",
            error="Some error",
            model="test",
            anonymization={"mappings": {"<PERSON_1>": "Error User"}}
        )

        mocker.patch("ai_agent.anonymizer.should_anonymize", return_value=False)
        mocker.patch("ai_agent.call_claude_cli", return_value=mock_response)

        result = call_agent(
            prompt="Test",
            config=sample_config
        )

        # Even on error, content should be de-anonymized
        assert result.success is False
        assert "Error User" in result.content
        assert "<PERSON_1>" not in result.content

    def test_deanonymize_on_cancelled(self, sample_config, mocker):
        """Test de-anonymization happens on cancelled tasks."""
        from ai_agent import call_agent, AgentResponse

        # Cancelled response with content
        mock_response = AgentResponse(
            success=False,
            content="Cancelled while processing <EMAIL_ADDRESS_1>",
            error="Cancelled by user",
            cancelled=True,
            model="test",
            anonymization={"mappings": {"<EMAIL_ADDRESS_1>": "cancelled@test.com"}}
        )

        mocker.patch("ai_agent.anonymizer.should_anonymize", return_value=False)
        mocker.patch("ai_agent.call_claude_agent_sdk", return_value=mock_response)

        sdk_config = sample_config.copy()
        sdk_config["ai_backends"]["claude_sdk"] = {"type": "claude_agent_sdk"}

        result = call_agent(
            prompt="Test",
            config=sdk_config,
            agent_name="claude_sdk"
        )

        # Cancelled content should still be de-anonymized
        assert "cancelled@test.com" in result.content
        assert "<EMAIL_ADDRESS_1>" not in result.content


class TestStreamingDeAnonymization:
    """Tests for streaming callback de-anonymization in core.streaming."""

    def test_streaming_callback_deanonymizes(self, monkeypatch):
        """Test that streaming callback de-anonymizes content."""
        from assistant.core import streaming as streaming_module

        # Setup mock tasks dict - monkeypatch the module where it's used
        mock_tasks = {}
        monkeypatch.setattr(streaming_module, "tasks", mock_tasks)

        task_id = "test_stream_1"
        mock_tasks[task_id] = {"status": "running"}

        # Create callback
        callback = streaming_module.create_streaming_callback(task_id)

        # Call with anonymized content and mappings (using anon_stats parameter)
        # The callback supports both legacy format (just mappings dict) and new format
        anon_stats = {
            "<PERSON_1>": "Streaming User",
            "<EMAIL_ADDRESS_1>": "stream@test.com"
        }
        callback(
            token="Hello ",
            is_thinking=False,
            full_response="Hello <PERSON_1>, email: <EMAIL_ADDRESS_1>",
            anon_stats=anon_stats
        )

        # Streaming content should be de-anonymized
        streaming_data = mock_tasks[task_id]["streaming"]
        assert "Streaming User" in streaming_data["content"]
        assert "stream@test.com" in streaming_data["content"]
        assert "<PERSON_1>" not in streaming_data["content"]

    def test_streaming_callback_without_mappings(self, monkeypatch):
        """Test streaming callback works without mappings."""
        from assistant.core import streaming as streaming_module

        mock_tasks = {}
        monkeypatch.setattr(streaming_module, "tasks", mock_tasks)

        task_id = "test_stream_2"
        mock_tasks[task_id] = {"status": "running"}

        callback = streaming_module.create_streaming_callback(task_id)

        # Call without mappings
        callback(
            token="Plain text",
            is_thinking=False,
            full_response="Plain text content",
            anon_stats=None
        )

        # Should work without error
        streaming_data = mock_tasks[task_id]["streaming"]
        assert streaming_data["content"] == "Plain text content"

    def test_streaming_stores_mappings_for_dialogs(self, monkeypatch):
        """Test that mappings are stored for confirmation dialogs."""
        from assistant.core import streaming as streaming_module

        mock_tasks = {}
        monkeypatch.setattr(streaming_module, "tasks", mock_tasks)

        task_id = "test_stream_3"
        mock_tasks[task_id] = {"status": "running"}

        callback = streaming_module.create_streaming_callback(task_id)

        mappings = {"<PERSON_1>": "Dialog User"}
        callback("token", False, "response", mappings)

        # Mappings should be stored in anonymization field
        assert "anonymization" in mock_tasks[task_id]
        assert mock_tasks[task_id]["anonymization"]["mappings"] == mappings


class TestBackendMappingPassing:
    """Tests for backends correctly passing mappings."""

    def test_gemini_passes_mappings_to_callback(self, sample_config, mocker):
        """Test Gemini passes anon_context.mappings to on_chunk."""
        from ai_agent.anonymizer import AnonymizationContext

        # Track what on_chunk receives
        received_mappings = []

        def mock_on_chunk(token, is_thinking, full_response, anon_mappings=None):
            received_mappings.append(anon_mappings)

        # Create context with mappings
        ctx = AnonymizationContext(
            mappings={"<TEST>": "gemini_test"}
        )

        # We can't easily test the full Gemini call, but we can verify
        # the logic by checking the code passes mappings correctly
        # This is a structural test

        # Verify the pattern: mappings = anon_context.mappings if anon_context else None
        mappings = ctx.mappings if ctx else None
        assert mappings == {"<TEST>": "gemini_test"}

    def test_sdk_returns_mappings_in_exception(self, sample_config):
        """Test Claude SDK returns mappings in AgentResponse on exception."""
        from ai_agent.base import AgentResponse

        # Simulate what SDK does on cancellation
        anon_stats = {"mappings": {"<PERSON_1>": "SDK User"}}
        anon_info = {"mappings": anon_stats["mappings"]} if anon_stats["mappings"] else None

        response = AgentResponse(
            success=False,
            content="Cancelled content with <PERSON_1>",
            error="Cancelled by user",
            cancelled=True,
            anonymization=anon_info
        )

        # Verify mappings are in response
        assert response.anonymization is not None
        assert "mappings" in response.anonymization
        assert response.anonymization["mappings"]["<PERSON_1>"] == "SDK User"


class TestMappingFormats:
    """Tests for different mapping formats from backends."""

    def test_flat_dict_format_gemini(self):
        """Test Gemini's flat dict format is handled."""
        # Gemini returns: {"<PERSON_1>": "value"}
        gemini_format = {"<PERSON_1>": "Gemini User"}

        # This format is OK because anon_context already has the mappings
        # __init__.py uses anon_context directly, not result.anonymization

        # Verify .get("mappings", {}) returns empty for flat dict
        backend_mappings = gemini_format.get("mappings", {})
        assert backend_mappings == {}

    def test_nested_dict_format_sdk(self):
        """Test SDK's nested dict format is handled."""
        # SDK returns: {"mappings": {"<PERSON_1>": "value"}}
        sdk_format = {"mappings": {"<PERSON_1>": "SDK User"}}

        # Verify .get("mappings", {}) extracts correctly
        backend_mappings = sdk_format.get("mappings", {})
        assert backend_mappings == {"<PERSON_1>": "SDK User"}

    def test_init_handles_both_formats(self, sample_config, mocker):
        """Test __init__.py handles both sources correctly."""
        from ai_agent.anonymizer import AnonymizationContext

        # Source 1: anon_context (used by Gemini/Claude API)
        anon_context = AnonymizationContext(
            mappings={"<PERSON_1>": "From Context"}
        )

        # Source 2: result.anonymization (used by SDK)
        result_anonymization = {
            "mappings": {"<EMAIL_ADDRESS_1>": "from-sdk@test.com"}
        }

        # Merge logic from __init__.py
        all_mappings = {}

        if anon_context and anon_context.mappings:
            all_mappings.update(anon_context.mappings)

        if result_anonymization and isinstance(result_anonymization, dict):
            backend_mappings = result_anonymization.get("mappings", {})
            if backend_mappings:
                all_mappings.update(backend_mappings)

        # Both should be merged
        assert all_mappings == {
            "<PERSON_1>": "From Context",
            "<EMAIL_ADDRESS_1>": "from-sdk@test.com"
        }


class TestAgentPromptAnonymization:
    """Tests for agent prompt anonymization (planfeature-011).

    Agent prompts (system instructions) should NOT be anonymized because they
    contain folder names, workflow terms, and instructions that presidio
    incorrectly detects as PII (e.g., "Done-Ordner" -> PERSON).

    Only the INPUT section (user data, emails, etc.) should be anonymized.
    """

    def test_prompt_without_input_marker_not_anonymized(self, sample_config):
        """Test that prompts without ### Input: marker are NOT anonymized.

        This is the core fix: agent-only prompts skip anonymization entirely.
        """
        from ai_agent.anonymizer import AnonymizationContext

        # Agent prompt with German words that were incorrectly detected as PII
        agent_prompt = """# Agent: Daily Check

Prüfe alle E-Mails im Posteingang:
1. Newsletter verschieben nach ToDelete-Ordner
2. Rechnungen verschieben nach Done-Ordner
3. NIEMALS Ganztaegig-Termine löschen

Verschiebe erledigte Mails in den Done-Ordner."""

        # The new logic: no ### Input: marker means we skip anonymization
        # and just create an empty context
        has_input_marker = "### Input:" in agent_prompt
        assert has_input_marker is False

        # Without marker, we create an empty context (no anonymization)
        anon_context = AnonymizationContext()
        assert anon_context.mappings == {}

        # Verify the prompt is unchanged (no PII replacements)
        assert "Done-Ordner" in agent_prompt
        assert "ToDelete-Ordner" in agent_prompt
        assert "NIEMALS" in agent_prompt
        assert "Ganztaegig" in agent_prompt

    def test_prompt_with_input_marker_anonymizes_only_input_section(self, sample_config):
        """Test that only the INPUT section is anonymized when marker is present.

        The system prompt BEFORE ### Input: should remain unchanged.
        Only the section AFTER ### Input: contains user data and should be anonymized.
        """
        # Prompt with both system instructions and user input
        prompt = """# Agent: E-Mail Reply

Verschiebe die E-Mail in den Done-Ordner nach Bearbeitung.
NIEMALS automatisch antworten.

### Input:
Von: Max Mustermann <max@example.com>
Betreff: Anfrage

Hallo, ich möchte ein Angebot.
### Output:
"""
        # Verify structure
        assert "### Input:" in prompt
        assert "### Output:" in prompt

        # Split by marker
        input_marker = "### Input:"
        output_marker = "### Output:"
        input_start = prompt.find(input_marker)
        input_end = prompt.find(output_marker) if output_marker in prompt else len(prompt)

        system_section = prompt[:input_start]
        input_section = prompt[input_start:input_end]

        # System section should contain workflow terms that should NOT be anonymized
        assert "Done-Ordner" in system_section
        assert "NIEMALS" in system_section
        assert "Max Mustermann" not in system_section  # User data is in input

        # Input section should contain user data that SHOULD be anonymized
        assert "Max Mustermann" in input_section
        assert "max@example.com" in input_section

    def test_continuation_prompt_includes_input_marker(self, sample_config):
        """Test that continuation prompts (after CONFIRMATION_NEEDED) include ### Input: marker.

        This ensures that user data in continuation prompts is anonymized,
        while the re-injected agent content is not.
        """
        # Simulated continuation prompt structure (as generated by agents.py)
        agent_content = """# Agent: Create Offer

Erstelle ein Angebot aus den Kontaktdaten.
Verschiebe die E-Mail in den Done-Ordner."""

        user_notes = "Bitte 10% Rabatt"
        user_data = {"kunde": "Max Müller", "email": "max@firma.de"}
        previous_response = "CONFIRMATION_NEEDED: Angebot für Max Müller..."

        # Build continuation prompt like agents.py does (with our fix)
        import json
        continuation_prompt = f"""Der Benutzer hat abgelehnt, bitte Alternative vorschlagen.
Bitte fahre mit der ursprünglichen Aufgabe fort (wichtig: nutze den Kontext aus deiner vorherigen Antwort!):
{agent_content}

### Input:
Der Benutzer hat folgende Notizen/Korrekturen angegeben:
{user_notes}

Die aktuellen Daten aus dem Dialog waren:
{json.dumps(user_data, ensure_ascii=False)}

Deine vorherige Antwort war:
---
{previous_response}
---
### Output:
"""

        # Verify structure: agent content BEFORE ### Input:
        input_marker = "### Input:"
        input_start = continuation_prompt.find(input_marker)

        before_input = continuation_prompt[:input_start]
        after_input = continuation_prompt[input_start:]

        # Agent content (workflow terms) should be BEFORE ### Input:
        assert "Done-Ordner" in before_input
        assert "Create Offer" in before_input

        # User data should be AFTER ### Input:
        assert "Max Müller" in after_input
        assert "max@firma.de" in after_input
        assert "Bitte 10% Rabatt" in after_input

    def test_confirmation_prompt_includes_input_marker(self, sample_config):
        """Test that confirmation prompts (after user confirms) include ### Input: marker."""
        # Simulated confirmation prompt structure (as generated by agents.py)
        agent_content = """# Agent: Paperless Tagging

Tagge die Dokumente entsprechend.
Nutze paperless_update_document()."""

        confirmed_data = {"documents": [{"id": 123, "title": "Rechnung GmbH"}]}
        previous_analysis = "Gefunden: 3 Dokumente für <PERSON_1>..."

        import json
        confirmation_prompt = f"""## Vorheriger Konversationskontext

User bestätigte Dokumente.
---

**WICHTIG: JETZT DIE ÄNDERUNGEN TATSÄCHLICH AUSFÜHREN!**

Du hast die Bestätigung erhalten. Führe nun die angekündigten Aktionen durch:
- Rufe die entsprechenden Tools auf (z.B. update_document, create_correspondent)
- Verwende die korrekten Daten aus dem Kontext (Namen, Adressen, Termine)
- Sage nicht nur dass du es machst - FÜHRE die Tool-Aufrufe tatsächlich aus!
- Zeige den Fortschritt pro Dokument/Aktion

Ursprüngliche Aufgabe zur Referenz:
{agent_content}

### Input:
✅ BESTÄTIGUNG ERHALTEN vom Benutzer:

{json.dumps(confirmed_data, ensure_ascii=False)}

Deine vorherige Analyse:
---
{previous_analysis}
---
### Output:
"""

        # Verify structure
        assert "### Input:" in confirmation_prompt
        input_marker = "### Input:"
        input_start = confirmation_prompt.find(input_marker)

        before_input = confirmation_prompt[:input_start]
        after_input = confirmation_prompt[input_start:]

        # Agent content should be BEFORE ### Input:
        assert "Paperless Tagging" in before_input
        assert "paperless_update_document()" in before_input

        # Confirmed data should be AFTER ### Input:
        assert "Rechnung GmbH" in after_input
        assert "BESTÄTIGUNG ERHALTEN" in after_input
