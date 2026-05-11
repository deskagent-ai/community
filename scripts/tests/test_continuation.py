# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for CONTINUATION_NEEDED parsing in interaction module.
"""
import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock the log function before importing
import ai_agent
ai_agent.log = print

from assistant.interaction import parse_continuation_request


class TestParseContinuationRequest:
    """Tests for parse_continuation_request function."""

    def test_basic_parsing(self):
        """Test parsing a complete CONTINUATION_NEEDED block."""
        content = '''
## Results
Here is some output.

CONTINUATION_NEEDED: {
  "message": "10 von 83 Dokumenten verarbeitet",
  "remaining": 73,
  "processed": 10
}
'''
        result = parse_continuation_request(content)
        assert result is not None
        assert result["message"] == "10 von 83 Dokumenten verarbeitet"
        assert result["remaining"] == 73
        assert result["processed"] == 10

    def test_no_marker_returns_none(self):
        """Test that content without marker returns None."""
        content = "Just some regular output without continuation"
        result = parse_continuation_request(content)
        assert result is None

    def test_message_only(self):
        """Test parsing with only required message field."""
        content = '''
CONTINUATION_NEEDED: {
  "message": "Weiter gehts"
}
'''
        result = parse_continuation_request(content)
        assert result is not None
        assert result["message"] == "Weiter gehts"
        assert "remaining" not in result
        assert "processed" not in result

    def test_missing_message_returns_none(self):
        """Test that missing message field returns None."""
        content = '''
CONTINUATION_NEEDED: {
  "remaining": 50
}
'''
        result = parse_continuation_request(content)
        assert result is None

    def test_marker_at_end_of_content(self):
        """Test parsing when marker is at the end of output."""
        content = '''## Betraege extrahiert

| ID | Titel | Betrag |
|----|-------|--------|
| 101 | Unity Invoice | 400.00 USD |
| 25 | EnBW Nov 2025 | 35.77 |

Bearbeitet: 10 Dokumente

CONTINUATION_NEEDED: {"message": "10 von 83 verarbeitet", "remaining": 73, "processed": 10}'''

        result = parse_continuation_request(content)
        assert result is not None
        assert result["processed"] == 10
        assert result["remaining"] == 73

    def test_inline_json_format(self):
        """Test parsing inline JSON format."""
        content = 'Some output CONTINUATION_NEEDED: {"message": "Done batch", "processed": 5}'
        result = parse_continuation_request(content)
        assert result is not None
        assert result["message"] == "Done batch"
        assert result["processed"] == 5

    def test_string_numbers_converted(self):
        """Test that string numbers are converted to int."""
        content = '''
CONTINUATION_NEEDED: {
  "message": "test",
  "remaining": "50",
  "processed": "10"
}
'''
        # Note: current implementation tries int() but keeps original on failure
        result = parse_continuation_request(content)
        assert result is not None
        # String numbers should be converted
        assert result["remaining"] == 50
        assert result["processed"] == 10


if __name__ == "__main__":
    # Run tests manually
    import traceback

    test = TestParseContinuationRequest()
    tests = [
        ("test_basic_parsing", test.test_basic_parsing),
        ("test_no_marker_returns_none", test.test_no_marker_returns_none),
        ("test_message_only", test.test_message_only),
        ("test_missing_message_returns_none", test.test_missing_message_returns_none),
        ("test_marker_at_end_of_content", test.test_marker_at_end_of_content),
        ("test_inline_json_format", test.test_inline_json_format),
        ("test_string_numbers_converted", test.test_string_numbers_converted),
    ]

    passed = 0
    failed = 0

    for name, func in tests:
        try:
            func()
            print(f"PASSED: {name}")
            passed += 1
        except AssertionError as e:
            print(f"FAILED: {name} - {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {name} - {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed}/{passed+failed} tests passed")
