# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Shared utilities for link_ref generation across all MCPs."""

import hashlib
from typing import Optional


def make_link_ref(item_id: str, item_type: str) -> str:
    """
    Generate a short, collision-resistant link reference.

    Args:
        item_id: The full ID (message_id, ticket_id, event_id, etc.)
        item_type: Type prefix for namespace separation (email, ticket, event, doc, etc.)

    Returns:
        8-character hash string, e.g., "a3f2b1c8"

    Examples:
        make_link_ref("AAMkAGFl...", "email")   -> "a3f2b1c8"
        make_link_ref("12345", "ticket")        -> "7d4e9f21"
        make_link_ref("AAMkAGFl...", "event")   -> "b2c4d6e8"
    """
    if not item_id:
        return ""
    hash_input = f"{item_type}:{item_id}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:8]


# Predefined type constants for consistency
LINK_TYPE_EMAIL = "email"
LINK_TYPE_EVENT = "event"
LINK_TYPE_TICKET = "ticket"
LINK_TYPE_DOCUMENT = "doc"
LINK_TYPE_INVOICE = "invoice"
LINK_TYPE_CONTACT = "contact"
LINK_TYPE_OFFER = "offer"
LINK_TYPE_CONFIRMATION = "confirmation"
