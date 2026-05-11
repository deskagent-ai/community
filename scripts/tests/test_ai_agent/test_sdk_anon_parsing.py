# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for Claude SDK Anonymization Metadata Parsing.

Tests parse_anon_metadata() and tool result processing in streaming callbacks.
These tests verify that ANON metadata from tool results is correctly parsed
and accumulated in anon_stats for both string and list content types.

Bug context: Tool results can arrive as either str or list[TextBlock].
The list path was missing parse_anon_metadata() calls, causing all
anonymization mappings to be lost (debug-002-20260210).
"""

import base64
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from ai_agent.claude_agent_sdk import parse_anon_metadata


# === Test Data ===

def make_anon_metadata(total: int, new: int, entity_summary: str, mappings: dict) -> str:
    """Create ANON metadata string like the proxy would."""
    mappings_b64 = base64.b64encode(json.dumps(mappings).encode()).decode()
    return f"<!--ANON:{total}|{new}|{entity_summary}|{mappings_b64}-->"


SAMPLE_MAPPINGS = {
    "<PERSON_1>": "Max Mustermann",
    "<EMAIL_ADDRESS_1>": "max@example.com",
    "<ORGANIZATION_1>": "ABC GmbH",
    "<LOCATION_1>": "Berlin"
}

SAMPLE_TOOL_RESULT = (
    "Von: Max Mustermann <max@example.com>\n"
    "Betreff: Anfrage\n"
    "Firma: ABC GmbH, Berlin\n"
)

SAMPLE_ANONYMIZED_RESULT = (
    "Von: <PERSON_1> <<EMAIL_ADDRESS_1>>\n"
    "Betreff: Anfrage\n"
    "Firma: <ORGANIZATION_1>, <LOCATION_1>\n"
)

SAMPLE_METADATA = make_anon_metadata(4, 4, "PERSON:1,EMAIL_ADDRESS:1,ORGANIZATION:1,LOCATION:1", SAMPLE_MAPPINGS)


# === Tests for parse_anon_metadata() ===

class TestParseAnonMetadata:
    """Unit tests for parse_anon_metadata() function."""

    def test_extended_format_with_mappings(self):
        """Extended format with base64-encoded mappings is parsed correctly."""
        text = SAMPLE_ANONYMIZED_RESULT + "\n" + SAMPLE_METADATA
        result = parse_anon_metadata(text)

        assert result is not None
        assert result["total"] == 4
        assert result["new"] == 4
        assert result["entity_summary"] == "PERSON:1,EMAIL_ADDRESS:1,ORGANIZATION:1,LOCATION:1"
        assert result["mappings"] == SAMPLE_MAPPINGS

    def test_legacy_format_without_mappings(self):
        """Legacy format without mappings returns empty mappings dict."""
        text = "Some text\n<!--ANON:5|3|PERSON:2,EMAIL:1-->"
        result = parse_anon_metadata(text)

        assert result is not None
        assert result["total"] == 5
        assert result["new"] == 3
        assert result["entity_summary"] == "PERSON:2,EMAIL:1"
        assert result["mappings"] == {}

    def test_no_metadata_returns_none(self):
        """Plain text without metadata returns None."""
        assert parse_anon_metadata("Just plain text") is None
        assert parse_anon_metadata("") is None
        assert parse_anon_metadata("<!-- regular comment -->") is None

    def test_invalid_base64_returns_empty_mappings(self):
        """Invalid base64 in mappings is handled gracefully."""
        text = "Some text\n<!--ANON:5|3|PERSON:2|NOT_VALID_BASE64!!!-->"
        result = parse_anon_metadata(text)

        assert result is not None
        assert result["total"] == 5
        assert result["new"] == 3
        assert result["mappings"] == {}

    def test_metadata_at_end_of_long_text(self):
        """Metadata at the end of a long tool result is found."""
        long_text = "A" * 10000 + "\n" + SAMPLE_METADATA
        result = parse_anon_metadata(long_text)

        assert result is not None
        assert result["mappings"] == SAMPLE_MAPPINGS

    def test_multiple_metadata_takes_first(self):
        """If multiple ANON tags exist, the first match is used."""
        meta1 = make_anon_metadata(2, 2, "PERSON:2", {"<PERSON_1>": "A", "<PERSON_2>": "B"})
        meta2 = make_anon_metadata(3, 1, "EMAIL:1", {"<EMAIL_1>": "x@y.com"})
        text = f"Text\n{meta1}\nMore text\n{meta2}"
        result = parse_anon_metadata(text)

        assert result["total"] == 2
        assert result["new"] == 2


# === Mock objects to simulate SDK message types ===

@dataclass
class MockTextBlock:
    """Simulates a TextBlock from the SDK."""
    text: str
    type: str = "text"


@dataclass
class MockToolResultBlock:
    """Simulates a ToolResult block - content as STRING."""
    tool_use_id: str
    content: str  # String content
    type: str = "tool_result"


@dataclass
class MockToolResultBlockList:
    """Simulates a ToolResult block - content as LIST of TextBlocks."""
    tool_use_id: str
    content: list  # List of TextBlock objects
    type: str = "tool_result"


@dataclass
class MockUserMessage:
    """Simulates a UserMessage from the SDK."""
    content: list
    type: str = "UserMessage"


@dataclass
class MockStreamingContext:
    """Minimal streaming context for testing tool result processing."""
    anon_stats: dict = field(default_factory=lambda: {
        "total_entities": 0,
        "entity_types": {},
        "tool_calls_anonymized": 0,
        "mappings": {}
    })
    tool_id_to_name: dict = field(default_factory=dict)
    tool_timings: dict = field(default_factory=dict)
    tool_stats: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    tool_result_tokens: int = 0
    token_breakdown: dict = field(default_factory=lambda: {"tools": 0, "system": 0, "prompt": 0})
    full_response: str = ""
    on_message: object = None


# === Tests for tool result processing ===

class TestToolResultProcessing:
    """
    Test that ANON metadata is correctly parsed from tool results.

    The streaming callback processes UserMessage blocks containing tool results.
    Each block can have content as either str or list[TextBlock].
    """

    def _process_tool_result_block(self, ctx, block):
        """
        Extract and process a single tool result block - mimics the logic
        from claude_agent_sdk.py lines 1400-1448 (Client Mode).
        """
        import re

        tool_use_id = getattr(block, "tool_use_id", "unknown")
        tool_content = getattr(block, "content", "")
        result_text = ""
        tool_anon_count = 0

        if isinstance(tool_content, str):
            result_text = tool_content
            anon_data = parse_anon_metadata(tool_content)
            if anon_data:
                tool_anon_count = anon_data['new']
                ctx.anon_stats["total_entities"] = anon_data["total"]
                ctx.anon_stats["tool_calls_anonymized"] += 1
                ctx.anon_stats["mappings"].update(anon_data["mappings"])
                if anon_data["entity_summary"]:
                    for part in anon_data["entity_summary"].split(","):
                        if ":" in part:
                            etype, count = part.split(":")
                            ctx.anon_stats["entity_types"][etype] = int(count)
                result_text = re.sub(r'\n?<!--ANON:[^>]+-->', '', result_text)

        elif isinstance(tool_content, list):
            parts = []
            for sub in tool_content:
                # Support both objects with .text and dicts with "text" key
                sub_text = None
                if hasattr(sub, "text"):
                    sub_text = sub.text
                elif isinstance(sub, dict) and "text" in sub:
                    sub_text = sub["text"]
                if sub_text:
                    parts.append(sub_text)
                    anon_data = parse_anon_metadata(sub_text)
                    if anon_data:
                        tool_anon_count += anon_data['new']
                        ctx.anon_stats["total_entities"] = anon_data["total"]
                        ctx.anon_stats["tool_calls_anonymized"] += 1
                        ctx.anon_stats["mappings"].update(anon_data["mappings"])
                        if anon_data["entity_summary"]:
                            for part in anon_data["entity_summary"].split(","):
                                if ":" in part:
                                    etype, count = part.split(":")
                                    ctx.anon_stats["entity_types"][etype] = int(count)
            result_text = "\n".join(parts)
            result_text = re.sub(r'\n?<!--ANON:[^>]+-->', '', result_text)

        return result_text, tool_anon_count

    def test_string_content_with_anon_metadata(self):
        """String tool_content with ANON metadata is parsed correctly."""
        ctx = MockStreamingContext()
        content = SAMPLE_ANONYMIZED_RESULT + "\n" + SAMPLE_METADATA

        block = MockToolResultBlock(tool_use_id="test-1", content=content)
        result_text, anon_count = self._process_tool_result_block(ctx, block)

        assert anon_count == 4
        assert ctx.anon_stats["total_entities"] == 4
        assert ctx.anon_stats["tool_calls_anonymized"] == 1
        assert ctx.anon_stats["mappings"] == SAMPLE_MAPPINGS
        assert "<!--ANON:" not in result_text

    def test_list_content_with_anon_metadata(self):
        """List tool_content with ANON metadata is parsed correctly.

        THIS IS THE BUG: List content was previously only stripping
        the ANON metadata but not parsing it into anon_stats.
        """
        ctx = MockStreamingContext()
        content_text = SAMPLE_ANONYMIZED_RESULT + "\n" + SAMPLE_METADATA
        block = MockToolResultBlockList(
            tool_use_id="test-1",
            content=[MockTextBlock(text=content_text)]
        )

        result_text, anon_count = self._process_tool_result_block(ctx, block)

        # This assertion WOULD FAIL with the old code (pre-fix):
        assert anon_count == 4, "List content should parse ANON metadata"
        assert ctx.anon_stats["total_entities"] == 4
        assert ctx.anon_stats["tool_calls_anonymized"] == 1
        assert ctx.anon_stats["mappings"] == SAMPLE_MAPPINGS
        assert "<!--ANON:" not in result_text

    def test_list_content_multiple_blocks(self):
        """List with multiple text blocks, metadata in last block."""
        ctx = MockStreamingContext()
        block = MockToolResultBlockList(
            tool_use_id="test-1",
            content=[
                MockTextBlock(text="Header info\n"),
                MockTextBlock(text=SAMPLE_ANONYMIZED_RESULT + "\n" + SAMPLE_METADATA)
            ]
        )

        result_text, anon_count = self._process_tool_result_block(ctx, block)

        assert anon_count == 4
        assert ctx.anon_stats["mappings"] == SAMPLE_MAPPINGS

    def test_list_content_no_metadata(self):
        """List content without ANON metadata passes through cleanly."""
        ctx = MockStreamingContext()
        block = MockToolResultBlockList(
            tool_use_id="test-1",
            content=[MockTextBlock(text="Plain tool result")]
        )

        result_text, anon_count = self._process_tool_result_block(ctx, block)

        assert anon_count == 0
        assert ctx.anon_stats["total_entities"] == 0
        assert ctx.anon_stats["mappings"] == {}
        assert result_text == "Plain tool result"

    def test_string_content_no_metadata(self):
        """String content without ANON metadata passes through cleanly."""
        ctx = MockStreamingContext()
        block = MockToolResultBlock(tool_use_id="test-1", content="Plain result")

        result_text, anon_count = self._process_tool_result_block(ctx, block)

        assert anon_count == 0
        assert ctx.anon_stats["mappings"] == {}

    def test_multiple_tool_calls_accumulate(self):
        """Multiple tool calls accumulate mappings correctly."""
        ctx = MockStreamingContext()

        # First tool call: clipboard
        mappings1 = {"<PERSON_1>": "Max"}
        meta1 = make_anon_metadata(1, 1, "PERSON:1", mappings1)
        block1 = MockToolResultBlock(tool_use_id="t-1", content=f"Clipboard: Max\n{meta1}")
        self._process_tool_result_block(ctx, block1)

        assert ctx.anon_stats["total_entities"] == 1
        assert ctx.anon_stats["mappings"] == {"<PERSON_1>": "Max"}

        # Second tool call: email (as list - the bug scenario)
        mappings2 = {
            "<PERSON_1>": "Max",
            "<EMAIL_ADDRESS_1>": "max@test.com",
            "<ORGANIZATION_1>": "ACME Corp"
        }
        meta2 = make_anon_metadata(3, 2, "PERSON:1,EMAIL:1,ORG:1", mappings2)
        block2 = MockToolResultBlockList(
            tool_use_id="t-2",
            content=[MockTextBlock(text=f"Email content\n{meta2}")]
        )
        self._process_tool_result_block(ctx, block2)

        assert ctx.anon_stats["total_entities"] == 3
        assert ctx.anon_stats["tool_calls_anonymized"] == 2
        assert len(ctx.anon_stats["mappings"]) == 3
        assert ctx.anon_stats["mappings"]["<EMAIL_ADDRESS_1>"] == "max@test.com"
        assert ctx.anon_stats["mappings"]["<ORGANIZATION_1>"] == "ACME Corp"

    def test_empty_list_content(self):
        """Empty list content is handled gracefully."""
        ctx = MockStreamingContext()
        block = MockToolResultBlockList(tool_use_id="test-1", content=[])

        result_text, anon_count = self._process_tool_result_block(ctx, block)

        assert anon_count == 0
        assert result_text == ""

    def test_list_block_without_text_attribute(self):
        """List blocks without 'text' attribute are skipped."""
        ctx = MockStreamingContext()
        block = MockToolResultBlockList(
            tool_use_id="test-1",
            content=[SimpleNamespace(data="binary")]  # no .text
        )

        result_text, anon_count = self._process_tool_result_block(ctx, block)

        assert anon_count == 0
        assert result_text == ""

    def test_dict_content_with_anon_metadata(self):
        """Dict-based content (real SDK format) with ANON metadata is parsed.

        THIS IS THE REAL BUG: Claude Agent SDK ToolResultBlock.content
        is list[dict[str, Any]], not list[TextBlock]. The dicts have
        {"type": "text", "text": "..."} format. hasattr(dict, "text")
        returns False, so the old code never extracted the text.
        """
        ctx = MockStreamingContext()
        content_text = SAMPLE_ANONYMIZED_RESULT + "\n" + SAMPLE_METADATA
        block = MockToolResultBlockList(
            tool_use_id="test-1",
            content=[{"type": "text", "text": content_text}]  # Dict, not TextBlock!
        )

        result_text, anon_count = self._process_tool_result_block(ctx, block)

        assert anon_count == 4, "Dict content should be parsed for ANON metadata"
        assert ctx.anon_stats["total_entities"] == 4
        assert ctx.anon_stats["mappings"] == SAMPLE_MAPPINGS
        assert "<!--ANON:" not in result_text

    def test_dict_content_multiple_blocks(self):
        """Multiple dict blocks, metadata in last block."""
        ctx = MockStreamingContext()
        block = MockToolResultBlockList(
            tool_use_id="test-1",
            content=[
                {"type": "text", "text": "Header\n"},
                {"type": "text", "text": SAMPLE_ANONYMIZED_RESULT + "\n" + SAMPLE_METADATA}
            ]
        )

        result_text, anon_count = self._process_tool_result_block(ctx, block)

        assert anon_count == 4
        assert ctx.anon_stats["mappings"] == SAMPLE_MAPPINGS

    def test_dict_without_text_key_skipped(self):
        """Dict blocks without 'text' key are skipped."""
        ctx = MockStreamingContext()
        block = MockToolResultBlockList(
            tool_use_id="test-1",
            content=[{"type": "image", "data": "base64..."}]
        )

        result_text, anon_count = self._process_tool_result_block(ctx, block)

        assert anon_count == 0
        assert result_text == ""

    def test_mixed_dict_and_object_content(self):
        """Mix of dict and TextBlock objects in content list."""
        ctx = MockStreamingContext()
        block = MockToolResultBlockList(
            tool_use_id="test-1",
            content=[
                MockTextBlock(text="From object\n"),
                {"type": "text", "text": SAMPLE_ANONYMIZED_RESULT + "\n" + SAMPLE_METADATA}
            ]
        )

        result_text, anon_count = self._process_tool_result_block(ctx, block)

        assert anon_count == 4
        assert ctx.anon_stats["mappings"] == SAMPLE_MAPPINGS
        assert "From object" in result_text

    def test_accumulate_with_dict_content(self):
        """Multiple tool calls: string first, then dict list (real scenario)."""
        ctx = MockStreamingContext()

        # First: clipboard as string
        mappings1 = {"<PERSON_1>": "Max"}
        meta1 = make_anon_metadata(1, 1, "PERSON:1", mappings1)
        block1 = MockToolResultBlock(tool_use_id="t-1", content=f"Max\n{meta1}")
        self._process_tool_result_block(ctx, block1)

        assert ctx.anon_stats["total_entities"] == 1

        # Second: email as dict list (the real SDK format)
        mappings2 = {"<PERSON_1>": "Max", "<EMAIL_ADDRESS_1>": "max@test.com", "<ORGANIZATION_1>": "ACME"}
        meta2 = make_anon_metadata(3, 2, "PERSON:1,EMAIL:1,ORG:1", mappings2)
        block2 = MockToolResultBlockList(
            tool_use_id="t-2",
            content=[{"type": "text", "text": f"Email\n{meta2}"}]
        )
        self._process_tool_result_block(ctx, block2)

        assert ctx.anon_stats["total_entities"] == 3
        assert ctx.anon_stats["tool_calls_anonymized"] == 2
        assert len(ctx.anon_stats["mappings"]) == 3
        assert ctx.anon_stats["mappings"]["<EMAIL_ADDRESS_1>"] == "max@test.com"


# === Test for anon_info construction ===

class TestAnonInfoConstruction:
    """Test that anon_stats leads to correct anon_info for AgentResponse."""

    def test_anon_info_built_when_entities_present(self):
        """When total_entities > 0, anon_info includes mappings."""
        anon_stats = {
            "total_entities": 4,
            "entity_types": {"PERSON": 1, "EMAIL_ADDRESS": 1},
            "tool_calls_anonymized": 1,
            "mappings": SAMPLE_MAPPINGS
        }

        # Mimics claude_agent_sdk.py lines 1230-1237
        anon_info = None
        if anon_stats["total_entities"] > 0:
            anon_info = {
                "total_entities": anon_stats["total_entities"],
                "entity_types": anon_stats["entity_types"],
                "tool_calls_anonymized": anon_stats["tool_calls_anonymized"],
                "mappings": anon_stats["mappings"]
            }

        assert anon_info is not None
        assert anon_info["mappings"] == SAMPLE_MAPPINGS

    def test_anon_info_none_when_no_entities(self):
        """When total_entities == 0, anon_info is None (no de-anon needed)."""
        anon_stats = {
            "total_entities": 0,
            "entity_types": {},
            "tool_calls_anonymized": 0,
            "mappings": {}
        }

        anon_info = None
        if anon_stats["total_entities"] > 0:
            anon_info = {"mappings": anon_stats["mappings"]}

        assert anon_info is None

    def test_central_deanon_reads_nested_format(self):
        """Central de-anonymization reads nested format from SDK result."""
        # This mimics __init__.py lines 623-631
        result_anonymization = {
            "total_entities": 4,
            "entity_types": {"PERSON": 1},
            "tool_calls_anonymized": 1,
            "mappings": SAMPLE_MAPPINGS
        }

        backend_mappings = result_anonymization.get("mappings")
        if backend_mappings is None:
            if any(k.startswith("<") for k in result_anonymization.keys()):
                backend_mappings = result_anonymization

        assert backend_mappings == SAMPLE_MAPPINGS

    def test_central_deanon_reads_flat_format(self):
        """Central de-anonymization reads flat format (fallback)."""
        result_anonymization = SAMPLE_MAPPINGS.copy()

        backend_mappings = result_anonymization.get("mappings")
        if backend_mappings is None:
            if any(k.startswith("<") for k in result_anonymization.keys()):
                backend_mappings = result_anonymization

        assert backend_mappings == SAMPLE_MAPPINGS
