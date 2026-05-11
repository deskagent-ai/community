# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Microsoft Graph MCP - Teams Module
===================================
Teams chat and channel tools.
"""

from urllib.parse import quote

try:
    import requests
except ImportError:
    requests = None

from msgraph.base import (
    mcp, require_auth,
    graph_request, get_config, MessageFormatter
)


# =============================================================================
# MCP Tools - Teams Chats
# =============================================================================

@mcp.tool()
@require_auth
def teams_get_chats(limit: int = 20, filter_participant: str = None) -> str:
    """Get recent Teams chats (1:1 and group chats).

    Args:
        limit: Maximum number of chats to return (default: 20)
        filter_participant: Optional - filter by participant name or email (case-insensitive partial match)

    Returns:
        List of recent chats with participants and last message preview
    """
    try:
        params = {
            "$top": min(limit, 50),
            "$expand": "lastMessagePreview,members",
            "$orderby": "lastMessagePreview/createdDateTime desc"
        }

        result = graph_request("/me/chats", params=params)
        chats = result.get("value", [])

        if not chats:
            return "No Teams chats found"

        formatted = []
        for chat in chats:
            chat_id = chat.get("id", "")
            chat_type = chat.get("chatType", "unknown")
            topic = chat.get("topic", "")

            # Get members
            members = chat.get("members", [])
            member_names = []
            member_emails = []
            for m in members:
                name = m.get("displayName", "")
                email = m.get("email", "")
                if name:
                    member_names.append(name)
                if email:
                    member_emails.append(email.lower())

            # Filter by participant if specified
            if filter_participant:
                filter_lower = filter_participant.lower()
                match_found = False
                for name in member_names:
                    if filter_lower in name.lower():
                        match_found = True
                        break
                for email in member_emails:
                    if filter_lower in email:
                        match_found = True
                        break
                if not match_found:
                    continue

            # Get last message preview (use 'or {}' to handle null values from API)
            last_msg = chat.get("lastMessagePreview") or {}
            last_msg_body = last_msg.get("body") or {}
            last_msg_from_obj = (last_msg.get("from") or {}).get("user") or {}
            last_msg_text = last_msg_body.get("content", "")[:50] if last_msg_body else ""
            last_msg_from = last_msg_from_obj.get("displayName", "")
            last_msg_time = (last_msg.get("createdDateTime") or "")[:16].replace("T", " ")

            if chat_type == "oneOnOne":
                # Show the other participant for 1:1 chats
                # With 2 members, show both; with only 1 visible, show that one
                if len(member_names) == 2:
                    label = f"1:1 with {member_names[1]}"
                elif member_names:
                    label = f"1:1 with {member_names[0]}"
                else:
                    label = "1:1 Chat"
            elif chat_type == "group":
                label = f"Group: {topic or 'Unnamed'} ({len(members)} members)"
            else:
                label = chat_type

            line = f"- [{chat_id}] {label}"
            if last_msg_time:
                line += f" | {last_msg_time} {last_msg_from}: {last_msg_text}..."

            formatted.append(line)

        if filter_participant and not formatted:
            return f"No chats found with participant matching '{filter_participant}'"

        return f"Teams Chats ({len(formatted)} found):\n" + "\n".join(formatted)

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def teams_get_messages(chat_id: str, limit: int = 20) -> str:
    """Get messages from a Teams chat.

    Args:
        chat_id: The chat ID (from teams_get_chats)
        limit: Maximum messages to return (default: 20)

    Returns:
        List of messages with sender, time, and content
    """
    try:
        params = {
            "$top": min(limit, 50),
            "$orderby": "createdDateTime desc"
        }

        # URL-encode the chat_id (contains special chars like : and @)
        encoded_chat_id = quote(chat_id, safe='')
        result = graph_request(f"/me/chats/{encoded_chat_id}/messages", params=params)
        messages = result.get("value", [])

        if not messages:
            return f"No messages in chat {chat_id}"

        # Format messages using MessageFormatter
        formatted = [MessageFormatter.format_teams_message(msg) for msg in messages]

        return f"Messages (newest first):\n" + "\n".join(formatted)

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def teams_send_message(chat_id: str, message: str) -> str:
    """Send a message to a Teams chat (1:1 or group).

    Args:
        chat_id: The chat ID (from teams_get_chats)
        message: The message text to send

    Returns:
        Confirmation or error
    """
    try:
        if not message or not message.strip():
            return "ERROR: Message cannot be empty"

        # URL-encode the chat_id (contains special chars like : and @)
        encoded_chat_id = quote(chat_id, safe='')
        endpoint = f"/me/chats/{encoded_chat_id}/messages"

        body = {
            "body": {
                "contentType": "text",
                "content": message
            }
        }

        result = graph_request(endpoint, method="POST", json_body=body)
        msg_id = result.get("id", "")

        return f"Message sent to chat. Message ID: {msg_id[:20]}..."

    except Exception as e:
        return f"ERROR: {e}"


# =============================================================================
# MCP Tools - Teams & Channels
# =============================================================================

@mcp.tool()
@require_auth
def teams_list_teams() -> str:
    """List all Teams the user is a member of.

    Returns:
        List of teams with their IDs and names
    """
    try:
        result = graph_request("/me/joinedTeams")
        teams = result.get("value", [])

        if not teams:
            return "No Teams found"

        formatted = []
        for team in teams:
            team_id = team.get("id", "")
            name = team.get("displayName", "Unknown")
            desc = team.get("description", "")[:50]

            formatted.append(f"- [{team_id[:8]}...] {name}" + (f" - {desc}" if desc else ""))

        return f"Your Teams ({len(teams)} found):\n" + "\n".join(formatted)

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def teams_list_channels(team_id: str) -> str:
    """List channels in a Team.

    Args:
        team_id: The team ID (from teams_list_teams)

    Returns:
        List of channels with their IDs and names
    """
    try:
        result = graph_request(f"/teams/{team_id}/channels")
        channels = result.get("value", [])

        if not channels:
            return f"No channels found in team {team_id[:8]}..."

        formatted = []
        for ch in channels:
            ch_id = ch.get("id", "")
            name = ch.get("displayName", "Unknown")
            desc = ch.get("description", "")[:30]

            formatted.append(f"- [{ch_id[:8]}...] {name}" + (f" - {desc}" if desc else ""))

        return f"Channels ({len(channels)} found):\n" + "\n".join(formatted)

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def teams_get_channel_messages(team_id: str, channel_id: str, limit: int = 20) -> str:
    """Get messages from a Teams channel.

    Args:
        team_id: The team ID (from teams_list_teams)
        channel_id: The channel ID (from teams_list_channels)
        limit: Maximum messages to return (default: 20)

    Returns:
        List of messages with sender, time, and content
    """
    try:
        params = {
            "$top": min(limit, 50),
            "$orderby": "createdDateTime desc"
        }

        # URL-encode IDs (may contain special chars)
        encoded_team_id = quote(team_id, safe='')
        encoded_channel_id = quote(channel_id, safe='')
        result = graph_request(f"/teams/{encoded_team_id}/channels/{encoded_channel_id}/messages", params=params)
        messages = result.get("value", [])

        if not messages:
            return f"No messages in channel"

        # Format messages using MessageFormatter
        formatted = [MessageFormatter.format_teams_message(msg) for msg in messages]

        return f"Channel messages (newest first):\n" + "\n".join(formatted)

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
@require_auth
def teams_post_to_channel(team_id: str, channel_id: str, message: str, subject: str = None) -> str:
    """Post a message to a Teams channel.

    Args:
        team_id: The team ID (from teams_list_teams)
        channel_id: The channel ID (from teams_list_channels)
        message: The message text to send
        subject: Optional subject/title for the message

    Returns:
        Confirmation or error
    """
    try:
        if not message or not message.strip():
            return "ERROR: Message cannot be empty"

        # URL-encode IDs (may contain special chars)
        encoded_team_id = quote(team_id, safe='')
        encoded_channel_id = quote(channel_id, safe='')
        endpoint = f"/teams/{encoded_team_id}/channels/{encoded_channel_id}/messages"

        body = {
            "body": {
                "contentType": "text",
                "content": message
            }
        }

        # Add subject if provided
        if subject:
            body["subject"] = subject

        result = graph_request(endpoint, method="POST", json_body=body)
        msg_id = result.get("id", "")

        return f"Message posted to channel. Message ID: {msg_id[:20]}..."

    except Exception as e:
        return f"ERROR: {e}"


# =============================================================================
# MCP Tools - Webhooks
# =============================================================================

@mcp.tool()
def teams_post_webhook(webhook_url: str, message: str, title: str = None) -> str:
    """Post a message to a Teams channel via Webhook or Power Automate Workflow.

    Messages appear as coming from "DeskAgent" (or configured name).
    No user authentication required - uses the webhook URL directly.

    Args:
        webhook_url: The webhook URL (Incoming Webhook or Power Automate Workflow)
        message: The message text to send
        title: Optional title/header for the message

    Returns:
        Confirmation or error

    Setup (New Teams - Power Automate):
        1. Teams channel → ... → Workflows
        2. Search "Post to a channel when a webhook request is received"
        3. Name: "DeskAgent", select channel
        4. Copy the HTTP POST URL → store in apis.json under msgraph.webhooks

    Setup (Classic Teams - Connectors):
        1. Teams channel → ... → Connectors → Incoming Webhook
        2. Name: "DeskAgent", upload icon
        3. Copy webhook URL → store in apis.json under msgraph.webhooks
    """
    try:
        if not message or not message.strip():
            return "ERROR: Message cannot be empty"

        # Validate URL - accept classic webhooks, Power Automate, and Power Platform
        is_classic_webhook = webhook_url and "webhook.office.com" in webhook_url
        is_power_automate = webhook_url and ("logic.azure.com" in webhook_url or "powerplatform.com" in webhook_url)

        if not (is_classic_webhook or is_power_automate):
            return "ERROR: Invalid webhook URL. Must be a Teams Webhook or Power Automate Workflow URL."

        if is_power_automate:
            # Power Automate expects Adaptive Card format
            payload = {
                "type": "message",
                "attachments": [{
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": title or "DeskAgent",
                                "weight": "Bolder",
                                "size": "Medium"
                            },
                            {
                                "type": "TextBlock",
                                "text": message,
                                "wrap": True
                            }
                        ]
                    }
                }]
            }
        else:
            # Classic Incoming Webhook - MessageCard format
            payload = {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "summary": title or "DeskAgent Message",
                "themeColor": "0076D7",
                "sections": [{
                    "activityTitle": title or "DeskAgent",
                    "text": message
                }]
            }

        response = requests.post(webhook_url, json=payload, timeout=10)

        # Power Automate returns 202 Accepted, classic returns 200 OK
        if response.status_code in (200, 202):
            return "Message posted to channel via webhook"
        else:
            return f"ERROR: Webhook returned {response.status_code}: {response.text}"

    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def teams_post_to_configured_channel(channel_name: str, message: str, title: str = None) -> str:
    """Post a message to a pre-configured Teams channel.

    Uses webhook URLs configured in apis.json. Messages appear as "DeskAgent".

    Args:
        channel_name: The channel key from apis.json (e.g., "deskagent", "general")
        message: The message text to send
        title: Optional title for the message

    Returns:
        Confirmation or error

    Configuration in apis.json:
        "msgraph": {
            "webhooks": {
                "deskagent": "https://...webhook.office.com/...",
                "general": "https://...webhook.office.com/..."
            }
        }
    """
    try:
        config = get_config()
        webhooks = config.get("webhooks", {})

        if not webhooks:
            return "ERROR: No webhooks configured in apis.json under msgraph.webhooks"

        webhook_url = webhooks.get(channel_name.lower())
        if not webhook_url:
            available = ", ".join(webhooks.keys())
            return f"ERROR: Channel '{channel_name}' not found. Available: {available}"

        return teams_post_webhook(webhook_url, message, title)

    except Exception as e:
        return f"ERROR: {e}"
