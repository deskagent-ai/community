# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Microsoft Graph MCP - Calendar Module
======================================
Calendar tools for reading events via Graph API.
"""

from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    requests = None

from msgraph.base import (
    mcp, require_auth,
    graph_request, MessageFormatter,
    mcp_log
)
from _link_utils import make_link_ref, LINK_TYPE_EVENT
from _mcp_api import register_link


# =============================================================================
# Helper Functions
# =============================================================================

def _format_event(event: dict) -> dict:
    """Format calendar event for JSON output."""
    start = event.get("start", {})
    end = event.get("end", {})

    # Parse start/end times
    start_dt = start.get("dateTime", "")
    end_dt = end.get("dateTime", "")
    is_all_day = event.get("isAllDay", False)

    # Format times
    if is_all_day:
        start_formatted = start_dt[:10] if start_dt else ""
        end_formatted = end_dt[:10] if end_dt else ""
        time_display = "Ganztägig"
    else:
        start_formatted = start_dt[:16].replace("T", " ") if start_dt else ""
        end_formatted = end_dt[:16].replace("T", " ") if end_dt else ""
        time_display = f"{start_dt[11:16]} - {end_dt[11:16]}" if start_dt and end_dt else ""

    # Location
    location = event.get("location", {})
    location_str = location.get("displayName", "") if isinstance(location, dict) else str(location)

    # Online meeting
    is_online = event.get("isOnlineMeeting", False)
    online_url = ""
    if is_online:
        online_meeting = event.get("onlineMeeting", {}) or {}
        online_url = online_meeting.get("joinUrl", "")

    event_id = event.get("id", "")

    # V2 Link System: Register URL, only expose link_ref to AI
    link_ref = make_link_ref(event_id, LINK_TYPE_EVENT)
    web_link = event.get("webLink", "")
    if web_link:
        register_link(link_ref, web_link)

    return {
        "id": event_id,
        "link_ref": link_ref,
        "subject": event.get("subject", "(Kein Betreff)"),
        "start": start_formatted,
        "end": end_formatted,
        "time": time_display,
        "is_all_day": is_all_day,
        "location": location_str,
        "is_online": is_online,
        "online_url": online_url,
        "organizer": event.get("organizer", {}).get("emailAddress", {}).get("name", ""),
        "response_status": event.get("responseStatus", {}).get("response", ""),
    }


# =============================================================================
# MCP Tools - Calendar
# =============================================================================

@mcp.tool()
@require_auth
def graph_get_upcoming_events(days: int = 2, mailbox: str = None) -> str:
    """Get upcoming calendar events via Microsoft Graph API.

    Args:
        days: Number of days to look ahead (default: 2 for today and tomorrow)
        mailbox: Optional mailbox to query (default: signed-in user)

    Returns:
        JSON array of calendar events with subject, time, location, etc.
    """
    import json

    try:
        # Calculate time range
        now = datetime.utcnow()
        start_time = now.strftime("%Y-%m-%dT00:00:00Z")
        end_time = (now + timedelta(days=days)).strftime("%Y-%m-%dT23:59:59Z")

        # Build endpoint
        if mailbox:
            endpoint = f"/users/{mailbox}/calendarView"
        else:
            endpoint = "/me/calendarView"

        # Query parameters
        params = {
            "startDateTime": start_time,
            "endDateTime": end_time,
            "$select": "id,subject,start,end,location,isAllDay,isOnlineMeeting,onlineMeeting,organizer,responseStatus,webLink",
            "$orderby": "start/dateTime",
            "$top": 50
        }

        mcp_log(f"[MsGraph] Getting events for next {days} days")

        response = graph_request(endpoint, params=params)

        if "error" in response:
            error = response["error"]
            return f"ERROR: {error.get('message', 'Unknown error')}"

        events = response.get("value", [])

        if not events:
            return json.dumps({"events": [], "message": "Keine Termine gefunden."})

        # Format events
        formatted = [_format_event(e) for e in events]

        return json.dumps({
            "events": formatted,
            "count": len(formatted),
            "range": f"{start_time[:10]} bis {end_time[:10]}"
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        mcp_log(f"[MsGraph] Calendar error: {e}")
        return f"ERROR: {str(e)}"


@mcp.tool()
@require_auth
def graph_get_today_events(mailbox: str = None) -> str:
    """Get today's calendar events via Microsoft Graph API.

    Args:
        mailbox: Optional mailbox to query (default: signed-in user)

    Returns:
        JSON array of today's calendar events
    """
    return graph_get_upcoming_events(days=1, mailbox=mailbox)


@mcp.tool()
@require_auth
def graph_create_calendar_event(
    subject: str,
    start_datetime: str,
    end_datetime: str,
    attendees: str = "",
    body: str = "",
    location: str = "",
    is_online_meeting: bool = True,
    send_invites: bool = True,
    mailbox: str = None
) -> str:
    """Create a calendar event (with optional Teams meeting) via Microsoft Graph API.

    Args:
        subject: Event subject/title
        start_datetime: Start time in ISO format (YYYY-MM-DDTHH:MM:SS), local timezone
        end_datetime: End time in ISO format (YYYY-MM-DDTHH:MM:SS), local timezone
        attendees: Comma-separated email addresses of attendees
        body: Event description/agenda (plain text)
        location: Physical location (ignored for online meetings)
        is_online_meeting: Create as Teams meeting with join link (default: True)
        send_invites: Send meeting invitations to attendees (default: True).
                      Set to False to create draft - review in Outlook before sending.
        mailbox: Optional mailbox to create event in (default: signed-in user)

    Returns:
        JSON with created event details including Teams link if online meeting
    """
    import json

    try:
        # Build endpoint
        if mailbox:
            endpoint = f"/users/{mailbox}/events"
        else:
            endpoint = "/me/events"

        # Parse attendees
        attendee_list = []
        if attendees:
            for email in attendees.split(","):
                email = email.strip()
                if email:
                    attendee_list.append({
                        "emailAddress": {"address": email},
                        "type": "required"
                    })

        # Build event body
        event_data = {
            "subject": subject,
            "start": {
                "dateTime": start_datetime,
                "timeZone": "Europe/Berlin"
            },
            "end": {
                "dateTime": end_datetime,
                "timeZone": "Europe/Berlin"
            },
            "isOnlineMeeting": is_online_meeting
        }

        # Add optional fields
        if attendee_list:
            event_data["attendees"] = attendee_list

        if body:
            event_data["body"] = {
                "contentType": "text",
                "content": body
            }

        if location and not is_online_meeting:
            event_data["location"] = {"displayName": location}

        if is_online_meeting:
            event_data["onlineMeetingProvider"] = "teamsForBusiness"

        mcp_log(f"[MsGraph] Creating calendar event: {subject}")

        response = graph_request(endpoint, method="POST", json_body=event_data)

        if "error" in response:
            error = response["error"]
            return f"ERROR: {error.get('message', 'Unknown error')}"

        # Format response
        result = _format_event(response)

        # Add success message
        if send_invites:
            base_msg = "Termin erfolgreich erstellt"
            teams_msg = "Teams Meeting erfolgreich erstellt"
        else:
            base_msg = "Termin als Entwurf erstellt - bitte in Outlook prüfen und manuell senden"
            teams_msg = "Teams Meeting als Entwurf erstellt - bitte in Outlook prüfen und manuell senden"

        output = {
            "success": True,
            "message": base_msg,
            "event": result,
            "invites_sent": send_invites
        }

        if is_online_meeting and result.get("online_url"):
            output["teams_link"] = result["online_url"]
            output["message"] = teams_msg

        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as e:
        mcp_log(f"[MsGraph] Create event error: {e}")
        return f"ERROR: {str(e)}"
