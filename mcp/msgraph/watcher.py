# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Microsoft Graph MCP - Teams Watcher Module
===========================================
Teams channel watcher setup and polling.
"""

import json
import re
from pathlib import Path
from urllib.parse import quote

from msgraph.base import (
    mcp, require_auth,
    graph_request, get_access_token, mcp_log
)


# =============================================================================
# MCP Tools - Teams Watcher Setup
# =============================================================================

@mcp.tool()
@require_auth
def teams_setup_watcher(channel_name: str) -> str:
    """Setup Teams watcher by finding and saving team/channel IDs.

    Searches all teams for a channel matching the given name and saves
    the IDs to triggers.json for the watcher to use.

    Args:
        channel_name: The name of the channel to watch (e.g., "deskagent", "General")

    Returns:
        Confirmation with found IDs or error
    """
    try:
        # Get all teams
        teams_result = graph_request("/me/joinedTeams")
        teams = teams_result.get("value", [])

        if not teams:
            return "ERROR: No teams found. Make sure you're a member of at least one team."

        found_team_id = None
        found_channel_id = None
        found_team_name = None
        found_channel_name = None

        # Search each team for the channel
        for team in teams:
            team_id = team.get("id")
            team_name = team.get("displayName", "Unknown")

            try:
                channels_result = graph_request(f"/teams/{team_id}/channels")
                channels = channels_result.get("value", [])

                for channel in channels:
                    ch_name = channel.get("displayName", "")
                    if ch_name.lower() == channel_name.lower():
                        found_team_id = team_id
                        found_channel_id = channel.get("id")
                        found_team_name = team_name
                        found_channel_name = ch_name
                        break

                if found_team_id:
                    break

            except Exception:
                continue

        if not found_team_id or not found_channel_id:
            return f"ERROR: Channel '{channel_name}' not found in any team."

        # Update triggers.json
        triggers_path = Path(__file__).parent.parent.parent / "config" / "triggers.json"

        # Load existing or create new
        if triggers_path.exists():
            triggers_config = json.loads(triggers_path.read_text(encoding="utf-8"))
        else:
            triggers_config = {"triggers": []}

        # Find or create teams_channel trigger
        found_trigger = None
        for trigger in triggers_config.get("triggers", []):
            if trigger.get("type") == "teams_channel":
                found_trigger = trigger
                break

        if not found_trigger:
            found_trigger = {
                "id": f"teams_{channel_name.lower()}",
                "type": "teams_channel",
                "name": f"Teams {channel_name} Channel",
                "agent": "chat",
                "poll_interval": 10,
                "response_webhook": "deskagent"
            }
            triggers_config["triggers"].append(found_trigger)

        found_trigger["team_id"] = found_team_id
        found_trigger["channel_id"] = found_channel_id
        found_trigger["enabled"] = True

        # Save triggers.json
        triggers_path.write_text(json.dumps(triggers_config, indent=2, ensure_ascii=False), encoding="utf-8")

        return f"""Teams watcher configured:
Team: {found_team_name} ({found_team_id[:20]}...)
Channel: {found_channel_name} ({found_channel_id[:20]}...)

Config saved to triggers.json. Watcher enabled.
Restart DeskAgent to start polling."""

    except Exception as e:
        return f"ERROR: {e}"


# =============================================================================
# Internal Polling Functions
# =============================================================================

def teams_poll_messages(team_id: str, channel_id: str, since_timestamp: str = None) -> list:
    """Poll for new messages in a Teams channel (internal function).

    Args:
        team_id: Team ID
        channel_id: Channel ID
        since_timestamp: ISO timestamp to get messages after (optional)

    Returns:
        List of new messages as dicts with id, sender, content, timestamp
    """
    try:
        token = get_access_token()
        if not token:
            return []

        encoded_team_id = quote(team_id, safe='')
        encoded_channel_id = quote(channel_id, safe='')

        # Get recent messages (top 10)
        endpoint = f"/teams/{encoded_team_id}/channels/{encoded_channel_id}/messages?$top=10&$orderby=createdDateTime desc"
        result = graph_request(endpoint)

        messages = []
        for msg in result.get("value", []):
            msg_time = msg.get("createdDateTime", "")

            # Skip if older than since_timestamp
            if since_timestamp and msg_time <= since_timestamp:
                continue

            # Get sender info
            from_info = msg.get("from", {})
            user_info = from_info.get("user", {})
            sender = user_info.get("displayName", "Unknown")

            # Skip messages from DeskAgent/Workflows (they have application identity)
            app_info = from_info.get("application", {})
            if app_info:
                continue  # Skip bot/workflow messages

            # Get content
            body = msg.get("body", {})
            content = body.get("content", "")

            # Strip HTML if present
            if body.get("contentType") == "html":
                content = re.sub(r'<[^>]+>', '', content).strip()

            messages.append({
                "id": msg.get("id", ""),
                "sender": sender,
                "content": content,
                "timestamp": msg_time
            })

        return messages

    except Exception as e:
        mcp_log(f"[MsGraph] TeamsWatcher poll error: {e}")
        return []
