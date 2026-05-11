#!/usr/bin/env python
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Test Anonymization on Recent Emails
====================================
Fetches recent emails from Outlook and tests the anonymization system.

Usage:
    python test_anonymization.py [--count 5] [--folder INBOX]

Output shows:
- Original email snippets
- Anonymized versions
- Detected entities
- Whitelisted terms that were skipped
"""

import sys
import json
import argparse
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config
from ai_agent.anonymizer import (
    anonymize,
    _get_merged_whitelist,
    _load_anonymizer_config,
    AnonymizationContext
)


def get_recent_emails(count: int = 5, folder: str = "INBOX"):
    """Fetch recent emails - tries Outlook local first, then Graph API."""

    # Try 1: Outlook COM (local desktop app)
    try:
        from mcp.outlook.base import OutlookMCP
        mcp = OutlookMCP()
        emails = mcp.get_recent_emails(folder=folder, limit=count)
        if emails:
            print(f"📬 Using: Outlook Desktop (COM)")
            return emails
    except Exception as e:
        print(f"[Info] Outlook Desktop not available: {e}")

    # Try 2: Microsoft Graph API
    try:
        from mcp.msgraph.base import MSGraphMCP
        mcp = MSGraphMCP()
        # Check if authenticated
        status = mcp.graph_status()
        if status.get("authenticated"):
            emails = mcp.graph_get_recent_emails(limit=count)
            if emails:
                print(f"📬 Using: Microsoft Graph API")
                return emails
        else:
            print(f"[Info] Graph API not authenticated")
    except Exception as e:
        print(f"[Info] Graph API not available: {e}")

    print("[Error] No email source available (Outlook Desktop or Graph API)")
    return []


def truncate(text: str, max_len: int = 500) -> str:
    """Truncate text for display."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def test_anonymization(emails: list, config: dict):
    """Test anonymization on email list."""
    whitelist = _get_merged_whitelist(config)
    anon_config = _load_anonymizer_config()

    print("\n" + "=" * 80)
    print("ANONYMIZATION TEST")
    print("=" * 80)

    print(f"\n📋 Whitelist ({len(whitelist)} terms):")
    # Show first 20 terms
    for i, term in enumerate(sorted(whitelist)[:20]):
        print(f"   - {term}")
    if len(whitelist) > 20:
        print(f"   ... and {len(whitelist) - 20} more")

    print("\n" + "-" * 80)

    for i, email in enumerate(emails, 1):
        subject = email.get("subject", "(no subject)")
        sender = email.get("sender", "(unknown)")
        body = email.get("body", email.get("preview", ""))

        print(f"\n📧 Email {i}: {subject}")
        print(f"   From: {sender}")
        print("-" * 40)

        # Combine subject + body for testing
        test_text = f"Subject: {subject}\nFrom: {sender}\n\n{body}"

        # Run anonymization
        anonymized, context = anonymize(test_text, config)

        print(f"\n🔍 Original (truncated):")
        print(truncate(test_text, 300))

        print(f"\n🔒 Anonymized:")
        print(truncate(anonymized, 300))

        if context.mappings:
            print(f"\n📊 Detected Entities ({len(context.mappings)}):")
            for placeholder, original in context.mappings.items():
                # Check if it would have been whitelisted
                was_whitelisted = original.lower() in [w.lower() for w in whitelist]
                status = "⚠️ (in whitelist but detected!)" if was_whitelisted else ""
                print(f"   {placeholder} ← '{original}' {status}")
        else:
            print("\n✅ No PII detected")

        # Check for whitelist hits (terms that appear but weren't anonymized)
        whitelist_hits = []
        for term in whitelist:
            if term.lower() in test_text.lower() and term.lower() in anonymized.lower():
                whitelist_hits.append(term)

        if whitelist_hits:
            print(f"\n🛡️ Whitelist protected ({len(whitelist_hits)} terms):")
            for term in whitelist_hits[:10]:
                print(f"   ✓ {term}")
            if len(whitelist_hits) > 10:
                print(f"   ... and {len(whitelist_hits) - 10} more")

        print("\n" + "-" * 80)

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Test anonymization on recent emails")
    parser.add_argument("--count", "-c", type=int, default=5, help="Number of emails to test (default: 5)")
    parser.add_argument("--folder", "-f", type=str, default="INBOX", help="Outlook folder (default: INBOX)")
    args = parser.parse_args()

    print(f"🔄 Fetching last {args.count} emails from {args.folder}...")

    # Load config
    config = load_config("system.json")

    # Fetch emails
    emails = get_recent_emails(args.count, args.folder)

    if not emails:
        print("❌ No emails found or error fetching emails")
        print("\nAlternative: You can also test with manual text:")
        print('  python -c "from test_anonymization import test_text; test_text()"')
        return 1

    print(f"✅ Found {len(emails)} emails")

    # Run test
    test_anonymization(emails, config)

    return 0


def test_text(text: str = None):
    """Test anonymization on custom text."""
    if text is None:
        text = """
        Hallo Max Mustermann,

        vielen Dank für Ihre E-Mail an info@example.com.

        Unser Produkt bietet Digital Twin Lösungen für die Industrie.
        Wir arbeiten mit Siemens S7 und Beckhoff TwinCAT.

        Ich rufe Sie morgen unter +49 123 456789 an.

        Mit freundlichen Grüßen
        Max Mustermann
        """

    config = load_config("system.json")

    print("\n📝 Testing custom text:")
    print("-" * 40)
    print(text)
    print("-" * 40)

    anonymized, context = anonymize(text, config)

    print("\n🔒 Anonymized:")
    print(anonymized)

    if context.mappings:
        print(f"\n📊 Detected Entities:")
        for placeholder, original in context.mappings.items():
            print(f"   {placeholder} ← '{original}'")
    else:
        print("\n✅ No PII detected")


if __name__ == "__main__":
    sys.exit(main())
