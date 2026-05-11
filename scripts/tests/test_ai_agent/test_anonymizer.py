# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for ai_agent.anonymizer module.
Tests PII detection and anonymization/de-anonymization.
"""

import pytest

# Skip tests if presidio not installed
pytest.importorskip("presidio_analyzer", reason="Presidio not installed")

from ai_agent.anonymizer import (
    AnonymizationContext,
    anonymize,
    deanonymize,
    get_used_mappings,
    should_anonymize,
    _is_safe_url,
    _is_false_positive,
    _extract_counter_from_placeholder,
    _strip_greeting_prefix,
    _normalize_name,
    _find_existing_mapping,
    _filter_service_results,
)


class TestAnonymizationContext:
    """Tests for AnonymizationContext dataclass."""

    def test_empty_context(self):
        """Test empty context initialization."""
        ctx = AnonymizationContext()
        assert ctx.mappings == {}
        assert ctx.reverse_mappings == {}
        assert ctx.counters == {}

    def test_context_with_mappings(self):
        """Test context with pre-populated mappings."""
        ctx = AnonymizationContext(
            mappings={"<PERSON_1>": "Max Mustermann"},
            reverse_mappings={"Max Mustermann": "<PERSON_1>"},
            counters={"PERSON": 1}
        )
        assert ctx.mappings["<PERSON_1>"] == "Max Mustermann"
        assert ctx.reverse_mappings["Max Mustermann"] == "<PERSON_1>"


class TestShouldAnonymize:
    """Tests for should_anonymize function."""

    def test_should_anonymize_enabled(self, sample_config, mocker):
        """Test anonymization when all conditions met."""
        # Mock is_available to return True
        mocker.patch("ai_agent.anonymizer.is_available", return_value=True)

        result = should_anonymize(
            sample_config,
            task_name="mail_reply",
            task_type="skill",
            backend_name="claude"
        )
        assert result is True

    def test_should_anonymize_disabled_global(self, sample_config, mocker):
        """Test when global anonymization is disabled."""
        mocker.patch("ai_agent.anonymizer.is_available", return_value=True)
        sample_config["anonymization"]["enabled"] = False

        result = should_anonymize(
            sample_config,
            task_name="mail_reply",
            task_type="skill",
            backend_name="claude"
        )
        assert result is False

    def test_should_anonymize_task_not_configured(self, sample_config, mocker):
        """Test when task doesn't have explicit anonymize setting.

        Falls back to backend default - cloud backends default to True.
        """
        mocker.patch("ai_agent.anonymizer.is_available", return_value=True)

        result = should_anonymize(
            sample_config,
            task_name="other_skill",  # Not in config
            task_type="skill",
            backend_name="claude"  # Cloud backend, defaults to True
        )
        # Cloud backends default to True if task doesn't override
        assert result is True


class TestSafeUrls:
    """Tests for URL safety checking."""

    def test_safe_url_microsoft(self):
        """Test Microsoft URLs are safe (system URLs)."""
        assert _is_safe_url("https://outlook.office365.com") is True
        assert _is_safe_url("https://teams.microsoft.com") is True

    def test_safe_url_github(self):
        """Test github.com is safe (in system URL list)."""
        assert _is_safe_url("https://github.com/some/repo") is True

    def test_unsafe_url_external(self):
        """Test external company URL is not safe."""
        assert _is_safe_url("https://example-company.com") is False

    def test_unsafe_url_company_domain(self):
        """Test company domains are NOT safe (should be anonymized)."""
        # Company domains should be anonymized, not marked as safe
        assert _is_safe_url("https://doc.example.com") is False


class TestFalsePositives:
    """Tests for false positive detection."""

    def test_low_confidence_skipped(self):
        """Test low confidence results are skipped."""
        assert _is_false_positive("Hello", "PERSON", 0.3) is True

    def test_short_text_skipped(self):
        """Test very short text is skipped."""
        assert _is_false_positive("Hi", "PERSON", 0.9) is True

    def test_common_word_skipped(self):
        """Test common words are skipped."""
        assert _is_false_positive("training", "PERSON", 0.9) is True

    def test_valid_name_kept(self):
        """Test valid names are not skipped."""
        assert _is_false_positive("Max Mustermann", "PERSON", 0.9) is False


class TestDeanonymize:
    """Tests for deanonymize function."""

    def test_deanonymize_restores_values(self):
        """Test de-anonymization restores original values."""
        ctx = AnonymizationContext(
            mappings={
                "<PERSON_1>": "Max Mustermann",
                "<EMAIL_1>": "max@example.com"
            }
        )

        text = "Hallo <PERSON_1>, bitte antworten an <EMAIL_1>."
        result = deanonymize(text, ctx)

        assert "Max Mustermann" in result
        assert "max@example.com" in result
        assert "<PERSON_1>" not in result
        assert "<EMAIL_1>" not in result

    def test_deanonymize_empty_context(self):
        """Test de-anonymization with empty context."""
        ctx = AnonymizationContext()
        text = "Plain text without placeholders."
        result = deanonymize(text, ctx)
        assert result == text


class TestGetUsedMappings:
    """Tests for get_used_mappings function."""

    def test_get_only_used_mappings(self):
        """Test that only used mappings are returned."""
        ctx = AnonymizationContext(
            mappings={
                "<PERSON_1>": "Max",
                "<PERSON_2>": "Unused Person",
                "<EMAIL_1>": "max@example.com"
            }
        )

        text = "Hallo <PERSON_1>, deine Email ist <EMAIL_1>."
        result = get_used_mappings(text, ctx)

        assert "<PERSON_1>" in result
        assert "<EMAIL_1>" in result
        assert "<PERSON_2>" not in result

    def test_get_used_mappings_none_used(self):
        """Test when no mappings are used."""
        ctx = AnonymizationContext(
            mappings={"<PERSON_1>": "Max"}
        )

        text = "Plain text without placeholders."
        result = get_used_mappings(text, ctx)
        assert result == {}


class TestExtractCounterFromPlaceholder:
    """Tests for _extract_counter_from_placeholder function."""

    def test_extract_person_placeholder(self):
        """Test extraction from PERSON placeholder."""
        entity_type, index = _extract_counter_from_placeholder("<PERSON_54>")
        assert entity_type == "PERSON"
        assert index == 54

    def test_extract_email_placeholder(self):
        """Test extraction from EMAIL_ADDRESS placeholder."""
        entity_type, index = _extract_counter_from_placeholder("<EMAIL_ADDRESS_1>")
        assert entity_type == "EMAIL_ADDRESS"
        assert index == 1

    def test_extract_organization_placeholder(self):
        """Test extraction from ORGANIZATION placeholder."""
        entity_type, index = _extract_counter_from_placeholder("<ORGANIZATION_123>")
        assert entity_type == "ORGANIZATION"
        assert index == 123

    def test_extract_invalid_placeholder(self):
        """Test extraction from invalid placeholder returns None."""
        entity_type, index = _extract_counter_from_placeholder("invalid")
        assert entity_type is None
        assert index == 0

    def test_extract_partial_placeholder(self):
        """Test extraction from malformed placeholder."""
        entity_type, index = _extract_counter_from_placeholder("<PERSON>")
        assert entity_type is None
        assert index == 0


class TestStripGreetingPrefix:
    """Tests for _strip_greeting_prefix function."""

    def test_strip_dear(self):
        """Test stripping 'Dear ' prefix."""
        assert _strip_greeting_prefix("Dear Thomas") == "Thomas"

    def test_strip_hi(self):
        """Test stripping 'Hi ' prefix."""
        assert _strip_greeting_prefix("Hi Subarna") == "Subarna"

    def test_strip_hello(self):
        """Test stripping 'Hello ' prefix."""
        assert _strip_greeting_prefix("Hello Max") == "Max"

    def test_strip_german_hallo(self):
        """Test stripping German 'Hallo ' prefix."""
        assert _strip_greeting_prefix("Hallo Thomas") == "Thomas"

    def test_strip_german_lieber(self):
        """Test stripping German 'Lieber ' prefix."""
        assert _strip_greeting_prefix("Lieber Max") == "Max"

    def test_strip_german_liebe(self):
        """Test stripping German 'Liebe ' prefix."""
        assert _strip_greeting_prefix("Liebe Maria") == "Maria"

    def test_no_greeting_unchanged(self):
        """Test name without greeting is unchanged."""
        assert _strip_greeting_prefix("Max Mustermann") == "Max Mustermann"

    def test_greeting_case_insensitive(self):
        """Test greeting detection is case insensitive."""
        assert _strip_greeting_prefix("DEAR Thomas") == "Thomas"
        assert _strip_greeting_prefix("dear Thomas") == "Thomas"


class TestNormalizeName:
    """Tests for _normalize_name function."""

    def test_normalize_lowercase(self):
        """Test name is lowercased."""
        assert _normalize_name("Max Mustermann") == "max mustermann"

    def test_normalize_strip_dr(self):
        """Test Dr. title is stripped."""
        assert _normalize_name("Dr. Max Müller") == "max müller"

    def test_normalize_strip_prof(self):
        """Test Prof. title is stripped."""
        assert _normalize_name("Prof. Schmidt") == "schmidt"

    def test_normalize_strip_mr(self):
        """Test Mr. title is stripped."""
        assert _normalize_name("Mr. Smith") == "smith"

    def test_normalize_strip_mrs(self):
        """Test Mrs. title is stripped."""
        assert _normalize_name("Mrs. Johnson") == "johnson"

    def test_normalize_whitespace(self):
        """Test whitespace is trimmed."""
        assert _normalize_name("  Thomas  ") == "thomas"


class TestFindExistingMapping:
    """Tests for _find_existing_mapping function."""

    def test_exact_match(self):
        """Test finding exact match."""
        ctx = AnonymizationContext(
            reverse_mappings={"Max Mustermann": "<PERSON_1>"}
        )
        result = _find_existing_mapping("Max Mustermann", ctx)
        assert result == "<PERSON_1>"

    def test_normalized_match(self):
        """Test finding match after normalization."""
        ctx = AnonymizationContext(
            reverse_mappings={"Dr. Max Mustermann": "<PERSON_1>"}
        )
        # "Max Mustermann" should match "Dr. Max Mustermann" after normalization
        result = _find_existing_mapping("Max Mustermann", ctx)
        assert result == "<PERSON_1>"

    def test_partial_match_first_name(self):
        """Test partial match finds full name."""
        ctx = AnonymizationContext(
            reverse_mappings={"Subarna Ganguly Marshall": "<PERSON_1>"}
        )
        # "Subarna" should match "Subarna Ganguly Marshall" (partial)
        result = _find_existing_mapping("Subarna", ctx)
        assert result == "<PERSON_1>"

    def test_partial_match_reverse(self):
        """Test partial match when existing is shorter."""
        ctx = AnonymizationContext(
            reverse_mappings={"Subarna": "<PERSON_1>"}
        )
        # "Subarna Ganguly" should match "Subarna" (partial)
        result = _find_existing_mapping("Subarna Ganguly", ctx)
        assert result == "<PERSON_1>"

    def test_no_match(self):
        """Test no match returns None."""
        ctx = AnonymizationContext(
            reverse_mappings={"Max Mustermann": "<PERSON_1>"}
        )
        result = _find_existing_mapping("Max Müller", ctx)
        assert result is None

    def test_empty_context(self):
        """Test empty context returns None."""
        ctx = AnonymizationContext()
        result = _find_existing_mapping("Thomas", ctx)
        assert result is None


class TestFilterServiceResults:
    """Tests for _filter_service_results function."""

    def test_filter_long_sentence_organization(self):
        """Test filtering out long sentences detected as ORGANIZATION."""
        ctx = AnonymizationContext()
        text = "Text with <ORGANIZATION_1> here."
        service_mappings = {
            "<ORGANIZATION_1>": "Machine builders are helping customers"  # 5+ words
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        assert "<ORGANIZATION_1>" not in filtered_mappings
        assert "Machine builders are helping customers" in filtered_text

    def test_filter_sentence_with_indicators(self):
        """Test filtering ORGANIZATION with sentence indicators."""
        ctx = AnonymizationContext()
        text = "Text with <ORGANIZATION_1> here."
        service_mappings = {
            "<ORGANIZATION_1>": "This is a test"  # Contains ' is '
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        assert "<ORGANIZATION_1>" not in filtered_mappings

    def test_keep_valid_organization(self):
        """Test keeping valid organization names."""
        ctx = AnonymizationContext()
        text = "Text with <ORGANIZATION_1> here."
        service_mappings = {
            "<ORGANIZATION_1>": "Unity GmbH"  # Valid company name
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        assert "<ORGANIZATION_1>" in filtered_mappings
        assert filtered_mappings["<ORGANIZATION_1>"] == "Unity GmbH"

    def test_strip_greeting_from_person(self):
        """Test greeting is stripped from PERSON entity."""
        ctx = AnonymizationContext()
        text = "Text with <PERSON_1> here."
        service_mappings = {
            "<PERSON_1>": "Dear Thomas"
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        # Greeting should be stripped, mapping should be just "Thomas"
        assert filtered_mappings.get("<PERSON_1>") == "Thomas"

    def test_deduplicate_same_person(self):
        """Test deduplication of same person with different formats."""
        ctx = AnonymizationContext(
            reverse_mappings={"Max Mustermann": "<PERSON_1>"},
            mappings={"<PERSON_1>": "Max Mustermann"}
        )
        text = "Text with <PERSON_2> here."
        service_mappings = {
            "<PERSON_2>": "Max"  # Should match existing Max Mustermann
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        # Should reuse existing <PERSON_1> instead of creating <PERSON_2>
        assert "<PERSON_2>" not in filtered_mappings
        assert "<PERSON_1>" in filtered_text

    def test_filter_false_positive_person(self):
        """Test filtering false positive PERSON detection."""
        ctx = AnonymizationContext()
        text = "Text with <PERSON_1> here."
        service_mappings = {
            "<PERSON_1>": "More significantly"  # Not a name
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        assert "<PERSON_1>" not in filtered_mappings
        assert "More significantly" in filtered_text

    def test_counter_sync(self):
        """Test that counters are synced from placeholders."""
        ctx = AnonymizationContext()
        text = "Text with <PERSON_54> here."
        service_mappings = {
            "<PERSON_54>": "Max Müller"
        }

        _filter_service_results(text, service_mappings, ctx)

        # Counter should be synced to at least 54
        assert ctx.counters.get("PERSON", 0) >= 54

    # === Bug 6: Double-anonymization prevention ===

    def test_filter_placeholder_name_as_location(self):
        """Test filtering placeholder names like 'EMAIL_1' detected as LOCATION.

        This is the double-anonymization bug: custom anonymization creates
        <EMAIL_1>, then Presidio NER sees 'EMAIL_1' and classifies it as LOCATION.
        """
        ctx = AnonymizationContext()
        text = "Contact at <<LOCATION_3>> for info."
        service_mappings = {
            "<LOCATION_3>": "EMAIL_1"  # This is a placeholder name, not a real location!
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        assert "<LOCATION_3>" not in filtered_mappings
        assert "EMAIL_1" in filtered_text

    def test_filter_url_placeholder_name_as_location(self):
        """Test filtering 'URL_1' detected as LOCATION."""
        ctx = AnonymizationContext()
        text = "See <<LOCATION_5>> for details."
        service_mappings = {
            "<LOCATION_5>": "URL_1"
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        assert "<LOCATION_5>" not in filtered_mappings

    def test_filter_domain_placeholder_name_as_location(self):
        """Test filtering 'DOMAIN_1>/in' (mangled placeholder) as LOCATION."""
        ctx = AnonymizationContext()
        text = "Visit <LOCATION_7> page."
        service_mappings = {
            "<LOCATION_7>": "DOMAIN_1>/in"
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        assert "<LOCATION_7>" not in filtered_mappings

    def test_filter_partial_placeholder_in_person(self):
        """Test filtering entity containing partial placeholder reference.

        E.g., 'electrónico de <EMAIL_4' detected as PERSON.
        """
        ctx = AnonymizationContext()
        text = "correo <PERSON_8> aquí."
        service_mappings = {
            "<PERSON_8>": "electrónico de <EMAIL_4"
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        assert "<PERSON_8>" not in filtered_mappings

    def test_keep_real_location_with_number(self):
        """Test that real locations containing numbers are NOT filtered.

        Only placeholder-like patterns (ALL_CAPS_NUMBER) should be filtered.
        """
        ctx = AnonymizationContext()
        text = "Located at <LOCATION_1>."
        service_mappings = {
            "<LOCATION_1>": "Mannheim"
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        assert "<LOCATION_1>" in filtered_mappings
        assert filtered_mappings["<LOCATION_1>"] == "Mannheim"

    def test_filter_five_word_sentence_as_person(self):
        """Test that 5-word phrases are filtered (threshold changed from >5 to >=5)."""
        ctx = AnonymizationContext()
        text = "Text <PERSON_2> here."
        service_mappings = {
            "<PERSON_2>": "He revisado el foro pero"  # 5 words, Spanish sentence
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        assert "<PERSON_2>" not in filtered_mappings

    def test_filter_spanish_email_header_words(self):
        """Test that Spanish email header words are filtered as false positives."""
        ctx = AnonymizationContext()
        spanish_words = {
            "<LOCATION_8>": "Tel",
            "<LOCATION_10>": "Asunto",
            "<LOCATION_12>": "lunes",
            "<LOCATION_13>": "Enviado",
            "<PERSON_4>": "Mensaje",
        }
        text = " ".join(f"x {p} y" for p in spanish_words.keys())

        filtered_text, filtered_mappings = _filter_service_results(text, spanish_words, ctx)

        for placeholder in spanish_words:
            assert placeholder not in filtered_mappings, \
                f"{placeholder} -> '{spanish_words[placeholder]}' should be filtered"

    def test_multiple_double_anonymization_entities(self):
        """Test full scenario: multiple placeholder names detected as entities.

        Simulates what happens when a Spanish email is processed:
        1. Custom anonymization creates <EMAIL_1>, <URL_1>, etc.
        2. Presidio then detects EMAIL_1, URL_1 as LOCATION entities
        """
        ctx = AnonymizationContext()
        text = "De: <PERSON_1> <<LOCATION_3>> Via <LOCATION_5> Tel <LOCATION_8>"
        service_mappings = {
            "<PERSON_1>": "Andoni Rivera",    # Real person - keep!
            "<LOCATION_3>": "EMAIL_1",         # Placeholder name - filter!
            "<LOCATION_5>": "DOMAIN_1>/in",    # Mangled placeholder - filter!
            "<LOCATION_8>": "Tel",             # Spanish word - filter!
        }

        filtered_text, filtered_mappings = _filter_service_results(text, service_mappings, ctx)

        # Real person should be kept
        assert "<PERSON_1>" in filtered_mappings
        assert filtered_mappings["<PERSON_1>"] == "Andoni Rivera"

        # Placeholder names and false positives should be filtered
        assert "<LOCATION_3>" not in filtered_mappings
        assert "<LOCATION_5>" not in filtered_mappings
        assert "<LOCATION_8>" not in filtered_mappings
