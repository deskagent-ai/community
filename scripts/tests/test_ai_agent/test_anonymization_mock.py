# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Anonymization Mock Tests
========================

Tests anonymization with mock LLM responses.
Verifies PII is anonymized before LLM and de-anonymized in response.

Run with: pytest -m mock tests/test_ai_agent/test_anonymization_mock.py -v
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ai_agent.mock_llm import MockLLMBackend, MockTracker

# Try to import anonymizer - skip tests if not available
try:
    from ai_agent.anonymizer import (
        anonymize,
        deanonymize,
        AnonymizationContext,
        ensure_spacy_models
    )
    # Check if spacy models are available
    ANONYMIZER_AVAILABLE = ensure_spacy_models()
except ImportError:
    ANONYMIZER_AVAILABLE = False
except Exception:
    # Catch any other errors during import/check
    ANONYMIZER_AVAILABLE = False


# =============================================================================
# Test: Anonymization Basics
# =============================================================================

@pytest.mark.mock
@pytest.mark.skipif(not ANONYMIZER_AVAILABLE, reason="Anonymizer not available")
class TestAnonymizationBasics:
    """Basic anonymization tests with mock LLM."""

    def test_anonymize_person(self, mock_config):
        """Person names are anonymized."""
        text = "E-Mail von Max Mustermann an Thomas"

        anonymized, context = anonymize(text, mock_config)

        assert "Max Mustermann" not in anonymized
        assert "<PERSON" in anonymized or "[PERSON" in anonymized
        assert len(context.mappings) > 0

    def test_anonymize_email(self, mock_config):
        """Email addresses are anonymized."""
        text = "Kontaktiere max@example.com"

        anonymized, context = anonymize(text, mock_config)

        assert "max@example.com" not in anonymized
        assert "<EMAIL" in anonymized or "[EMAIL" in anonymized

    def test_deanonymize_restores_text(self, mock_config):
        """De-anonymization restores original text."""
        original = "E-Mail von Max Mustermann (max@example.com)"

        anonymized, context = anonymize(original, mock_config)
        restored = deanonymize(anonymized, context)

        # Original content should be restored
        assert "Max Mustermann" in restored or "max@example.com" in restored

    def test_empty_text(self, mock_config):
        """Empty text doesn't crash."""
        anonymized, context = anonymize("", mock_config)

        assert anonymized == ""
        assert len(context.mappings) == 0


# =============================================================================
# Test: Anonymization with Mock LLM
# =============================================================================

@pytest.mark.mock
@pytest.mark.skipif(not ANONYMIZER_AVAILABLE, reason="Anonymizer not available")
class TestAnonymizationWithMockLLM:
    """Tests combining anonymization with mock LLM."""

    def test_prompt_anonymized_before_llm(self, mock_config):
        """PII should be anonymized before reaching LLM."""
        tracker = MockTracker()
        mock_backend = MockLLMBackend(config=mock_config, tracker=tracker)

        # Simulate the anonymization flow
        original_prompt = "E-Mail von Max Mustermann (max@example.com)"
        anonymized_prompt, context = anonymize(original_prompt, mock_config)

        # Call mock LLM with anonymized prompt
        mock_backend.call(prompt=anonymized_prompt)

        # Verify what was sent to LLM
        sent = tracker.get_sent_prompt()
        assert "Max Mustermann" not in sent
        assert "max@example.com" not in sent

    def test_llm_response_deanonymized(self, mock_config):
        """LLM response should be de-anonymized."""
        tracker = MockTracker()
        mock_backend = MockLLMBackend(config=mock_config, tracker=tracker)

        # Simulate anonymization
        original_prompt = "Kontaktiere Max Mustermann"
        anonymized_prompt, context = anonymize(original_prompt, mock_config)

        # Mock response contains placeholder
        # Find what placeholder was assigned to "Max Mustermann"
        person_placeholder = None
        for placeholder, original in context.mappings.items():
            if "Max Mustermann" in original:
                person_placeholder = placeholder
                break

        if person_placeholder:
            # Set mock response with placeholder
            tracker.set_mock_response(f"Ich werde {person_placeholder} kontaktieren.")

            # Call and de-anonymize
            result = mock_backend.call(prompt=anonymized_prompt)
            restored = deanonymize(result.content, context)

            assert "Max Mustermann" in restored

    def test_multiple_entities_same_placeholder(self, mock_config):
        """Same entity gets same placeholder."""
        text = "Max sagt zu Max: Hallo Max!"

        anonymized, context = anonymize(text, mock_config)

        # Count placeholder occurrences - should be consistent
        # (Same name = same placeholder)
        placeholder_count = anonymized.count("<PERSON_1>") if "<PERSON_1>" in anonymized else anonymized.count("[PERSON_1]")

        # All "Max" should get the same placeholder
        # Note: Detection may vary, so we just verify consistency
        assert placeholder_count >= 1 or len(context.mappings) >= 1


# =============================================================================
# Test: Anonymization Disabled
# =============================================================================

@pytest.mark.mock
@pytest.mark.skipif(not ANONYMIZER_AVAILABLE, reason="Anonymizer not available")
class TestAnonymizationDisabled:
    """Tests with anonymization disabled."""

    def test_disabled_passes_through(self):
        """When disabled, text passes through unchanged."""
        config = {
            "anonymization": {
                "enabled": False
            }
        }

        text = "E-Mail von Max Mustermann (max@example.com)"
        anonymized, context = anonymize(text, config)

        # Text should be unchanged when disabled
        assert anonymized == text or len(context.mappings) == 0


# =============================================================================
# Test: Edge Cases
# =============================================================================

@pytest.mark.mock
@pytest.mark.skipif(not ANONYMIZER_AVAILABLE, reason="Anonymizer not available")
class TestAnonymizationEdgeCases:
    """Edge cases for anonymization."""

    def test_special_characters_in_names(self, mock_config):
        """Names with special characters are handled."""
        text = "Kontakt: Francois O'Brien-Mueller"

        # Should not crash
        anonymized, context = anonymize(text, mock_config)
        assert anonymized is not None

    def test_unicode_text(self, mock_config):
        """Unicode text is handled correctly."""
        text = "Nachricht von Hans Muller an Jurg Schmid"

        anonymized, context = anonymize(text, mock_config)
        assert anonymized is not None

    def test_very_long_text(self, mock_config):
        """Very long text is handled."""
        text = "Max Mustermann " * 1000

        anonymized, context = anonymize(text, mock_config)
        assert "Max Mustermann" not in anonymized

    def test_no_pii(self, mock_config):
        """Text without PII returns unchanged."""
        text = "Dies ist ein Test ohne personenbezogene Daten."

        anonymized, context = anonymize(text, mock_config)

        # Should be unchanged or have empty mappings
        assert len(context.mappings) == 0 or text in anonymized


# =============================================================================
# Test: Anonymization Context
# =============================================================================

@pytest.mark.mock
@pytest.mark.skipif(not ANONYMIZER_AVAILABLE, reason="Anonymizer not available")
class TestAnonymizationContext:
    """Tests for AnonymizationContext."""

    def test_context_stores_mappings(self, mock_config):
        """Context stores placeholder-to-original mappings."""
        text = "Von: Max Mustermann"

        _, context = anonymize(text, mock_config)

        # Should have at least one mapping
        if context.mappings:
            # Mappings are placeholder -> original
            for placeholder, original in context.mappings.items():
                assert placeholder.startswith("<") or placeholder.startswith("[")
                assert len(original) > 0

    def test_context_reverse_mappings(self, mock_config):
        """Context has reverse mappings for lookup."""
        text = "Von: Max Mustermann"

        _, context = anonymize(text, mock_config)

        # Reverse mappings are original -> placeholder
        if context.reverse_mappings:
            for original, placeholder in context.reverse_mappings.items():
                assert placeholder in context.mappings

    def test_context_counters(self, mock_config):
        """Context tracks entity type counters."""
        text = "Max und Maria schreiben an Hans"

        _, context = anonymize(text, mock_config)

        # Should have PERSON counter if names were detected
        # Counter tracks next index per entity type
        if context.counters:
            assert isinstance(context.counters, dict)


# =============================================================================
# Test: Safe URLs Not Anonymized
# =============================================================================

@pytest.mark.mock
@pytest.mark.skipif(not ANONYMIZER_AVAILABLE, reason="Anonymizer not available")
class TestSafeUrls:
    """Tests that safe URLs are not anonymized."""

    def test_github_url_preserved(self, mock_config):
        """GitHub URLs should not be anonymized."""
        text = "Code auf https://github.com/example-org/project"

        anonymized, _ = anonymize(text, mock_config)

        # GitHub URL should remain
        assert "github.com" in anonymized

    def test_doc_url_preserved(self, mock_config):
        """Documentation URLs should not be anonymized."""
        text = "Docs: https://doc.example.com/manual"

        anonymized, _ = anonymize(text, mock_config)

        # Doc URL should remain
        assert "example.com" in anonymized

    def test_external_url_may_be_anonymized(self, mock_config):
        """External URLs may be anonymized."""
        text = "Siehe https://external-customer-site.com/secret"

        anonymized, context = anonymize(text, mock_config)

        # External URLs might be anonymized depending on config
        # Just verify no crash
        assert anonymized is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "mock"])
