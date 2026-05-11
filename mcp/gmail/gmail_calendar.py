# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Gmail MCP - Calendar Module
===========================
Google Calendar operations: view, create events and meetings.
"""

import json
from datetime import datetime, timedelta

from gmail.base import (
    mcp, gmail_tool, require_auth,
    get_calendar_service, system_log
)


@mcp.tool()
@gmail_tool
@require_auth
def gcal_get_today_events() -> str:
    """Get today's calendar events.

    Returns:
        List of today's events with time, subject, location
    """
    service = get_calendar_service()

    # Get today's date range
    now = datetime.now()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    time_min = start_of_day.isoformat() + 'Z'
    time_max = end_of_day.isoformat() + 'Z'

    events_result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])

    if not events:
        return f"No events today ({now.strftime('%d.%m.%Y')})."

    output_lines = [f"Events for today ({now.strftime('%d.%m.%Y')}):\n"]

    for event in events:
        output_lines.append(_format_event(event))

    return "\n".join(output_lines)


@mcp.tool()
@gmail_tool
@require_auth
def gcal_get_upcoming_events(days: int = 7) -> str:
    """Get upcoming calendar events for the next N days.

    Args:
        days: Number of days to look ahead (default: 7)

    Returns:
        List of upcoming events
    """
    service = get_calendar_service()

    now = datetime.now()
    time_min = now.isoformat() + 'Z'
    time_max = (now + timedelta(days=days)).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime',
        maxResults=100
    ).execute()

    events = events_result.get('items', [])

    if not events:
        return f"No events in the next {days} days."

    output_lines = [f"Upcoming events (next {days} days):\n"]

    current_date = None
    for event in events:
        # Get event date for grouping
        start = event.get('start', {})
        event_date = start.get('dateTime', start.get('date', ''))[:10]

        if event_date != current_date:
            current_date = event_date
            try:
                date_obj = datetime.fromisoformat(event_date)
                output_lines.append(f"\n--- {date_obj.strftime('%A, %d.%m.%Y')} ---")
            except ValueError:
                output_lines.append(f"\n--- {event_date} ---")

        output_lines.append(_format_event(event))

    return "\n".join(output_lines)


@mcp.tool()
@gmail_tool
@require_auth
def gcal_get_event_details(event_id: str) -> str:
    """Get detailed information about a specific event.

    Args:
        event_id: Event ID (from event list)

    Returns:
        Full event details
    """
    service = get_calendar_service()

    event = service.events().get(
        calendarId='primary',
        eventId=event_id
    ).execute()

    return _format_event_details(event)


@mcp.tool()
@gmail_tool
@require_auth
def gcal_check_availability(
    date_str: str,
    start_time: str,
    end_time: str
) -> str:
    """Check if a time slot is available.

    Args:
        date_str: Date in format DD.MM.YYYY
        start_time: Start time in format HH:MM
        end_time: End time in format HH:MM

    Returns:
        Availability status and any conflicting events
    """
    service = get_calendar_service()

    # Parse date and times
    try:
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
    except ValueError:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return f"ERROR: Invalid date format. Use DD.MM.YYYY or YYYY-MM-DD"

    try:
        start_dt = datetime.strptime(f"{date_obj.strftime('%Y-%m-%d')} {start_time}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{date_obj.strftime('%Y-%m-%d')} {end_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "ERROR: Invalid time format. Use HH:MM"

    # Query events in the time range
    time_min = start_dt.isoformat() + 'Z'
    time_max = end_dt.isoformat() + 'Z'

    events_result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True
    ).execute()

    events = events_result.get('items', [])

    if not events:
        return f"""Time slot is AVAILABLE!

Date: {date_str}
Time: {start_time} - {end_time}

No conflicting events found."""

    # List conflicting events
    conflicts = []
    for event in events:
        summary = event.get('summary', '(No title)')
        start = event.get('start', {})
        event_start = start.get('dateTime', start.get('date', ''))
        conflicts.append(f"  - {summary} ({event_start})")

    return f"""Time slot is NOT available.

Date: {date_str}
Time: {start_time} - {end_time}

Conflicting events:
{chr(10).join(conflicts)}"""


@mcp.tool()
@gmail_tool
@require_auth
def gcal_create_event(
    subject: str,
    date_str: str,
    start_time: str,
    end_time: str,
    location: str = "",
    description: str = "",
    reminder_minutes: int = 15
) -> str:
    """Create a calendar event (without attendees).

    Args:
        subject: Event title/subject
        date_str: Date in format DD.MM.YYYY
        start_time: Start time in format HH:MM
        end_time: End time in format HH:MM
        location: Event location (optional)
        description: Event description/notes (optional)
        reminder_minutes: Reminder in minutes before event (default: 15)

    Returns:
        Created event details
    """
    service = get_calendar_service()

    # Parse date and times
    try:
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
    except ValueError:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return f"ERROR: Invalid date format. Use DD.MM.YYYY or YYYY-MM-DD"

    try:
        start_dt = datetime.strptime(f"{date_obj.strftime('%Y-%m-%d')} {start_time}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{date_obj.strftime('%Y-%m-%d')} {end_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "ERROR: Invalid time format. Use HH:MM"

    # Build event body
    event_body = {
        'summary': subject,
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'Europe/Berlin',
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'Europe/Berlin',
        },
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': reminder_minutes},
            ],
        },
    }

    if location:
        event_body['location'] = location

    if description:
        event_body['description'] = description

    # Create event
    event = service.events().insert(
        calendarId='primary',
        body=event_body
    ).execute()

    return f"""Event created successfully!

Subject: {subject}
Date: {date_str}
Time: {start_time} - {end_time}
Location: {location or '(none)'}

Event ID: {event.get('id')}
Link: {event.get('htmlLink')}"""


@mcp.tool()
@gmail_tool
@require_auth
def gcal_create_meeting(
    subject: str,
    date_str: str,
    start_time: str,
    end_time: str,
    attendees: str,
    description: str = "",
    location: str = "",
    send_updates: bool = True,
    add_meet_link: bool = True
) -> str:
    """Create a meeting with attendees (optionally with Google Meet link).

    Args:
        subject: Meeting title/subject
        date_str: Date in format DD.MM.YYYY
        start_time: Start time in format HH:MM
        end_time: End time in format HH:MM
        attendees: Comma-separated email addresses
        description: Meeting agenda/description (optional)
        location: Location (optional, overridden if Google Meet)
        send_updates: Send invitation emails to attendees (default: True)
        add_meet_link: Add Google Meet video conferencing link (default: True)

    Returns:
        Created meeting details with Meet link
    """
    service = get_calendar_service()

    # Parse date and times
    try:
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
    except ValueError:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return f"ERROR: Invalid date format. Use DD.MM.YYYY or YYYY-MM-DD"

    try:
        start_dt = datetime.strptime(f"{date_obj.strftime('%Y-%m-%d')} {start_time}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{date_obj.strftime('%Y-%m-%d')} {end_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "ERROR: Invalid time format. Use HH:MM"

    # Parse attendees
    attendee_list = []
    for email in attendees.split(','):
        email = email.strip()
        if email:
            attendee_list.append({'email': email})

    if not attendee_list:
        return "ERROR: At least one attendee email is required."

    # Build event body
    event_body = {
        'summary': subject,
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'Europe/Berlin',
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'Europe/Berlin',
        },
        'attendees': attendee_list,
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 24 * 60},  # 1 day before
                {'method': 'popup', 'minutes': 15},
            ],
        },
    }

    if description:
        event_body['description'] = description

    if location and not add_meet_link:
        event_body['location'] = location

    # Add Google Meet conferencing
    if add_meet_link:
        event_body['conferenceData'] = {
            'createRequest': {
                'requestId': f"meet-{datetime.now().timestamp()}",
                'conferenceSolutionKey': {'type': 'hangoutsMeet'}
            }
        }

    # Create event
    event = service.events().insert(
        calendarId='primary',
        body=event_body,
        conferenceDataVersion=1 if add_meet_link else 0,
        sendUpdates='all' if send_updates else 'none'
    ).execute()

    # Extract Meet link
    meet_link = ""
    if add_meet_link:
        conference_data = event.get('conferenceData', {})
        entry_points = conference_data.get('entryPoints', [])
        for ep in entry_points:
            if ep.get('entryPointType') == 'video':
                meet_link = ep.get('uri', '')
                break

    attendee_str = ", ".join(a['email'] for a in attendee_list)

    result = f"""Meeting created successfully!

Subject: {subject}
Date: {date_str}
Time: {start_time} - {end_time}
Attendees: {attendee_str}
Invitations sent: {'Yes' if send_updates else 'No'}"""

    if meet_link:
        result += f"\n\nGoogle Meet Link: {meet_link}"

    result += f"""

Event ID: {event.get('id')}
Calendar Link: {event.get('htmlLink')}"""

    return result


@mcp.tool()
@gmail_tool
@require_auth
def gcal_list_calendars() -> str:
    """List all calendars the user has access to.

    Returns:
        List of calendars with ID and name
    """
    service = get_calendar_service()

    calendar_list = service.calendarList().list().execute()
    calendars = calendar_list.get('items', [])

    if not calendars:
        return "No calendars found."

    output_lines = ["Available calendars:\n"]

    for cal in calendars:
        summary = cal.get('summary', '(Unnamed)')
        cal_id = cal.get('id', '')
        primary = " [PRIMARY]" if cal.get('primary') else ""
        access_role = cal.get('accessRole', '')

        output_lines.append(f"- {summary}{primary}")
        output_lines.append(f"  ID: {cal_id}")
        output_lines.append(f"  Access: {access_role}")

    return "\n".join(output_lines)


@mcp.tool()
@gmail_tool
@require_auth
def gcal_delete_event(event_id: str) -> str:
    """Delete a calendar event.

    Args:
        event_id: Event ID to delete

    Returns:
        Confirmation
    """
    service = get_calendar_service()

    # Get event first to show what was deleted
    try:
        event = service.events().get(
            calendarId='primary',
            eventId=event_id
        ).execute()
        summary = event.get('summary', '(No title)')
    except Exception:
        summary = "(Unknown event)"

    service.events().delete(
        calendarId='primary',
        eventId=event_id
    ).execute()

    return f"Deleted event: {summary} (ID: {event_id})"


# =============================================================================
# Helper Functions
# =============================================================================

def _format_event(event: dict) -> str:
    """Format event for list display."""
    summary = event.get('summary', '(No title)')
    start = event.get('start', {})
    location = event.get('location', '')
    event_id = event.get('id', '')

    # Get time or "all day"
    if 'dateTime' in start:
        try:
            dt = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
            time_str = dt.strftime('%H:%M')
        except ValueError:
            time_str = start['dateTime'][:5]
    else:
        time_str = "All day"

    # Check for Meet link
    has_meet = ""
    conference_data = event.get('conferenceData', {})
    if conference_data:
        has_meet = " [Meet]"

    # Check for attendees
    attendees = event.get('attendees', [])
    attendee_str = f" ({len(attendees)} attendees)" if attendees else ""

    line = f"  {time_str} - {summary}{has_meet}{attendee_str}"
    if location:
        line += f"\n         📍 {location}"

    return line


def _format_event_details(event: dict) -> str:
    """Format full event details."""
    summary = event.get('summary', '(No title)')
    description = event.get('description', '')
    location = event.get('location', '')
    status = event.get('status', '')
    event_id = event.get('id', '')
    html_link = event.get('htmlLink', '')

    # Time
    start = event.get('start', {})
    end = event.get('end', {})

    if 'dateTime' in start:
        start_dt = start['dateTime']
        end_dt = end.get('dateTime', '')
        try:
            s = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
            e = datetime.fromisoformat(end_dt.replace('Z', '+00:00'))
            time_str = f"{s.strftime('%d.%m.%Y %H:%M')} - {e.strftime('%H:%M')}"
        except ValueError:
            time_str = f"{start_dt} - {end_dt}"
    else:
        time_str = f"{start.get('date', '')} (All day)"

    # Attendees
    attendees = event.get('attendees', [])
    attendee_lines = []
    for att in attendees:
        email = att.get('email', '')
        response = att.get('responseStatus', 'needsAction')
        status_emoji = {
            'accepted': '✅',
            'declined': '❌',
            'tentative': '❓',
            'needsAction': '⏳'
        }.get(response, '❓')
        attendee_lines.append(f"  {status_emoji} {email}")

    # Meet link
    meet_link = ""
    conference_data = event.get('conferenceData', {})
    if conference_data:
        for ep in conference_data.get('entryPoints', []):
            if ep.get('entryPointType') == 'video':
                meet_link = ep.get('uri', '')
                break

    result = f"""Event Details
{'=' * 50}

Subject: {summary}
Time: {time_str}
Location: {location or '(none)'}
Status: {status}"""

    if meet_link:
        result += f"\n\nGoogle Meet: {meet_link}"

    if attendee_lines:
        result += f"\n\nAttendees:\n" + "\n".join(attendee_lines)

    if description:
        result += f"\n\nDescription:\n{description}"

    result += f"""

Event ID: {event_id}
Link: {html_link}"""

    return result
