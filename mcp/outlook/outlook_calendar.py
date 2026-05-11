# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Outlook MCP - Calendar Module
============================
Functions for calendar operations: events, appointments, meetings.

Version: 2026-02-04-v5 (German date format fix for recurring appointments)
"""

# Module version for debugging - increment this on each change!
_CALENDAR_MODULE_VERSION = "2026-02-04-v5"

from datetime import datetime, timedelta

from outlook.base import (
    mcp, outlook_tool, mcp_log,
    get_outlook
)


def _format_outlook_date(dt: datetime) -> str:
    """Format datetime for Outlook Jet filter.

    IMPORTANT: Despite Microsoft documentation claiming ISO format works,
    testing shows German Windows requires German date format (DD.MM.YYYY).
    The ISO format returns wrong results with recurring appointments.

    Tested 2026-02-04:
    - ISO '2026/02/04' -> Returns April dates (WRONG)
    - US '02/04/2026' -> Returns April dates (WRONG)
    - DE '04.02.2026' -> Returns correct February dates (CORRECT)
    """
    # German format: DD.MM.YYYY HH:MM - required for German Windows locale
    return dt.strftime('%d.%m.%Y %H:%M')


def _get_all_calendar_items(namespace, start_date: datetime, end_date: datetime) -> list:
    """Get calendar items from all stores/accounts.

    CRITICAL ORDER (per Microsoft docs):
    1. Sort by [Start]
    2. Set IncludeRecurrences = True
    3. Apply Restrict filter

    Reference: https://learn.microsoft.com/en-us/office/vba/api/outlook.items.includerecurrences
    """
    all_items = []
    seen = set()  # Track seen items to avoid duplicates

    # Build Jet filter string with US date format
    filter_str = (
        f"[Start] >= '{_format_outlook_date(start_date)}' "
        f"AND [Start] < '{_format_outlook_date(end_date)}'"
    )

    mcp_log(f"[Outlook] [Calendar] Version: {_CALENDAR_MODULE_VERSION}")
    mcp_log(f"[Outlook] [Calendar] Filter: {filter_str}")
    mcp_log(f"[Outlook] [Calendar] Scanning {namespace.Stores.Count} stores...")

    for store in namespace.Stores:
        mcp_log(f"[Outlook] [Calendar] Checking store: {store.DisplayName}")
        try:
            calendar = None

            # Method 1: Try to get calendar from store's root folder
            try:
                root_folder = store.GetRootFolder()
                for folder in root_folder.Folders:
                    if folder.DefaultItemType == 1:  # olAppointmentItem
                        calendar = folder
                        break
            except Exception:
                pass

            # Method 2: Try default calendar folder (only works for primary store)
            if calendar is None:
                try:
                    calendar = namespace.GetDefaultFolder(9)
                except Exception:
                    continue

            if calendar is None:
                mcp_log(f"[Outlook] [Calendar] No calendar found in store: {store.DisplayName}")
                continue

            mcp_log(f"[Outlook] [Calendar] Found calendar: {calendar.Name} in {store.DisplayName}")
            appointments = calendar.Items
            mcp_log(f"[Outlook] [Calendar] Total items (before filter): {appointments.Count}")

            # CRITICAL ORDER per Microsoft documentation:
            # 1. Sort first
            appointments.Sort("[Start]")
            # 2. Then enable recurring items expansion
            appointments.IncludeRecurrences = True
            # 3. Then apply filter
            filtered = appointments.Restrict(filter_str)

            # Use GetFirst/GetNext pattern - do NOT use Count with IncludeRecurrences!
            # (Count returns undefined value with recurring items)
            try:
                appt = filtered.GetFirst()
                max_items = 200  # Safety limit to prevent infinite loop
                count = 0

                while appt and count < max_items:
                    count += 1
                    try:
                        # Get the actual datetime of this occurrence
                        appt_start_dt = None
                        start_str = ""
                        if hasattr(appt, 'Start') and appt.Start:
                            if hasattr(appt.Start, 'year'):
                                # COM datetime object - extract Python datetime
                                appt_start_dt = datetime(
                                    appt.Start.year, appt.Start.month, appt.Start.day,
                                    appt.Start.hour, appt.Start.minute, appt.Start.second
                                )
                                start_str = appt_start_dt.strftime('%Y-%m-%d %H:%M')
                            else:
                                start_str = str(appt.Start)[:16]

                        # CRITICAL: Double-check date is within requested range
                        # IncludeRecurrences can return wrong occurrences
                        if appt_start_dt:
                            if appt_start_dt < start_date or appt_start_dt >= end_date:
                                # Skip events outside our requested range
                                appt = filtered.GetNext()
                                continue

                        subject = str(appt.Subject) if appt.Subject else ""
                        key = f"{subject}|{start_str}"

                        if key not in seen:
                            seen.add(key)
                            all_items.append(appt)

                    except Exception as e:
                        mcp_log(f"[Outlook] [Calendar] Error processing item: {e}")

                    # Get next item
                    try:
                        appt = filtered.GetNext()
                    except Exception:
                        break

            except Exception as e:
                mcp_log(f"[Outlook] [Calendar] Error iterating filtered items: {e}")

        except Exception as e:
            mcp_log(f"[Outlook] [Calendar] Error reading store {store.DisplayName}: {e}")
            continue

    # Sort all items by start time
    def get_sort_key(item):
        try:
            if hasattr(item.Start, 'year'):
                return datetime(item.Start.year, item.Start.month, item.Start.day,
                               item.Start.hour, item.Start.minute)
            return datetime.max
        except Exception:
            return datetime.max

    all_items.sort(key=get_sort_key)
    mcp_log(f"[Outlook] [Calendar] Found {len(all_items)} items")
    return all_items


@mcp.tool()
@outlook_tool
def outlook_get_today_events() -> str:
    """Zeigt alle Termine für heute."""
    try:
        outlook = get_outlook()
        namespace = outlook.GetNamespace("MAPI")

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        # Get items from all calendars
        appointments = _get_all_calendar_items(namespace, today, tomorrow)

        result = []
        for appt in appointments:
            start = appt.Start.strftime("%H:%M") if hasattr(appt.Start, 'strftime') else str(appt.Start)
            end = appt.End.strftime("%H:%M") if hasattr(appt.End, 'strftime') else str(appt.End)
            location = f" @ {appt.Location}" if appt.Location else ""
            result.append(f"- {start}-{end}: {appt.Subject}{location}")

        if not result:
            return f"Keine Termine heute ({today.strftime('%d.%m.%Y')})"

        return f"Termine heute ({today.strftime('%d.%m.%Y')}):\n" + "\n".join(result)

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_get_upcoming_events(days: int = 7) -> str:
    """Zeigt Termine für die nächsten Tage.

    Args:
        days: Anzahl Tage voraus (Standard: 7)
    """
    try:
        outlook = get_outlook()
        namespace = outlook.GetNamespace("MAPI")

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = today + timedelta(days=days)

        # Get items from all calendars
        appointments = _get_all_calendar_items(namespace, today, end_date)

        result = []
        current_date = None

        for appt in appointments:
            appt_date = appt.Start.strftime("%d.%m.%Y") if hasattr(appt.Start, 'strftime') else str(appt.Start)[:10]

            if appt_date != current_date:
                current_date = appt_date
                weekday = appt.Start.strftime("%A") if hasattr(appt.Start, 'strftime') else ""
                result.append(f"\n**{appt_date} ({weekday})**")

            start = appt.Start.strftime("%H:%M") if hasattr(appt.Start, 'strftime') else str(appt.Start)
            end = appt.End.strftime("%H:%M") if hasattr(appt.End, 'strftime') else str(appt.End)
            location = f" @ {appt.Location}" if appt.Location else ""
            result.append(f"  - {start}-{end}: {appt.Subject}{location}")

        if not result:
            return f"Keine Termine in den nächsten {days} Tagen"

        return f"Termine ({days} Tage):" + "\n".join(result)

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_get_calendar_event_details(subject_query: str, days_ahead: int = 14) -> str:
    """Zeigt Details eines Termins anhand des Betreffs.

    Args:
        subject_query: Suchbegriff im Betreff
        days_ahead: Tage voraus zum Suchen (Standard: 14)
    """
    try:
        outlook = get_outlook()
        namespace = outlook.GetNamespace("MAPI")

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = today + timedelta(days=days_ahead)

        # Get items from all calendars
        appointments = _get_all_calendar_items(namespace, today, end_date)

        for appt in appointments:
            if subject_query.lower() in appt.Subject.lower():
                start = appt.Start.strftime("%d.%m.%Y %H:%M") if hasattr(appt.Start, 'strftime') else str(appt.Start)
                end = appt.End.strftime("%d.%m.%Y %H:%M") if hasattr(appt.End, 'strftime') else str(appt.End)

                return f"""Termin gefunden:

Betreff: {appt.Subject}
Start: {start}
Ende: {end}
Ort: {appt.Location or '-'}
Organisator: {appt.Organizer or '-'}
Teilnehmer: {appt.RequiredAttendees or '-'}
Optional: {appt.OptionalAttendees or '-'}

Beschreibung:
{appt.Body or '-'}"""

        return f"Kein Termin gefunden mit '{subject_query}' in den nächsten {days_ahead} Tagen"

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_check_availability(date_str: str, start_time: str, end_time: str) -> str:
    """Prüft ob ein Zeitslot frei ist.

    Args:
        date_str: Datum im Format TT.MM.JJJJ
        start_time: Startzeit im Format HH:MM
        end_time: Endzeit im Format HH:MM
    """
    try:
        outlook = get_outlook()
        namespace = outlook.GetNamespace("MAPI")

        # Parse date and times
        date_parts = date_str.split(".")
        day, month, year = int(date_parts[0]), int(date_parts[1]), int(date_parts[2])

        start_parts = start_time.split(":")
        end_parts = end_time.split(":")

        check_start = datetime(year, month, day, int(start_parts[0]), int(start_parts[1]))
        check_end = datetime(year, month, day, int(end_parts[0]), int(end_parts[1]))

        # Get appointments for that day from all calendars
        day_start = check_start.replace(hour=0, minute=0)
        day_end = day_start + timedelta(days=1)

        appointments = _get_all_calendar_items(namespace, day_start, day_end)

        conflicts = []
        for appt in appointments:
            appt_start = appt.Start if hasattr(appt.Start, 'hour') else datetime.strptime(str(appt.Start), '%Y-%m-%d %H:%M:%S')
            appt_end = appt.End if hasattr(appt.End, 'hour') else datetime.strptime(str(appt.End), '%Y-%m-%d %H:%M:%S')

            # Check for overlap
            if appt_start < check_end and appt_end > check_start:
                time_str = f"{appt.Start.strftime('%H:%M')}-{appt.End.strftime('%H:%M')}"
                conflicts.append(f"- {time_str}: {appt.Subject}")

        if conflicts:
            return f"Zeitslot {start_time}-{end_time} am {date_str} ist BELEGT:\n" + "\n".join(conflicts)
        else:
            return f"Zeitslot {start_time}-{end_time} am {date_str} ist FREI"

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_create_appointment(
    subject: str,
    date_str: str,
    start_time: str,
    end_time: str,
    location: str = "",
    body: str = "",
    reminder_minutes: int = 15
) -> str:
    """Erstellt einen neuen Kalendertermin (ohne Teilnehmer).

    Args:
        subject: Betreff des Termins
        date_str: Datum im Format TT.MM.JJJJ
        start_time: Startzeit im Format HH:MM
        end_time: Endzeit im Format HH:MM
        location: Ort (optional)
        body: Beschreibung/Notizen (optional)
        reminder_minutes: Erinnerung in Minuten (Standard: 15)

    Returns:
        Bestätigung mit Termindetails
    """
    try:
        outlook = get_outlook()

        # Create appointment
        appt = outlook.CreateItem(1)  # olAppointmentItem

        appt.Subject = subject

        # Parse date and times
        date_parts = date_str.split(".")
        day, month, year = int(date_parts[0]), int(date_parts[1]), int(date_parts[2])

        start_parts = start_time.split(":")
        end_parts = end_time.split(":")

        appt.Start = datetime(year, month, day, int(start_parts[0]), int(start_parts[1]))
        appt.End = datetime(year, month, day, int(end_parts[0]), int(end_parts[1]))

        if location:
            appt.Location = location
        if body:
            appt.Body = body

        appt.ReminderSet = True
        appt.ReminderMinutesBeforeStart = reminder_minutes

        appt.Save()

        return (
            f"Termin erstellt:\n"
            f"- Betreff: {subject}\n"
            f"- Datum: {date_str}\n"
            f"- Zeit: {start_time} - {end_time}\n"
            f"- Ort: {location or '(keiner)'}\n"
            f"- Erinnerung: {reminder_minutes} Min. vorher"
        )

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_create_meeting(
    subject: str,
    date_str: str,
    start_time: str,
    end_time: str,
    attendees: str,
    location: str = "",
    body: str = "",
    teams_meeting: bool = False,
    reminder_minutes: int = 15,
    send_invites: bool = True,
    display: bool = False
) -> str:
    """Erstellt eine Besprechung mit Teilnehmern (optional mit Teams-Link).

    Args:
        subject: Betreff der Besprechung
        date_str: Datum im Format TT.MM.JJJJ
        start_time: Startzeit im Format HH:MM
        end_time: Endzeit im Format HH:MM
        attendees: Teilnehmer E-Mail-Adressen (kommagetrennt)
        location: Ort (optional, wird bei Teams-Meeting überschrieben)
        body: Beschreibung/Agenda (optional)
        teams_meeting: True für Teams-Meeting mit Beitrittslink
        reminder_minutes: Erinnerung in Minuten (Standard: 15)
        send_invites: Einladungen sofort senden (Standard: True)
        display: True um das Meeting-Fenster in Outlook zu öffnen (Standard: False)

    Returns:
        Bestätigung mit Besprechungsdetails
    """
    try:
        outlook = get_outlook()

        # Create meeting request
        appt = outlook.CreateItem(1)  # olAppointmentItem
        appt.MeetingStatus = 1  # olMeeting

        appt.Subject = subject

        # Parse date and times
        date_parts = date_str.split(".")
        day, month, year = int(date_parts[0]), int(date_parts[1]), int(date_parts[2])

        start_parts = start_time.split(":")
        end_parts = end_time.split(":")

        appt.Start = datetime(year, month, day, int(start_parts[0]), int(start_parts[1]))
        appt.End = datetime(year, month, day, int(end_parts[0]), int(end_parts[1]))

        # Add attendees
        attendee_list = [a.strip() for a in attendees.split(",")]
        for email in attendee_list:
            if email:
                recipient = appt.Recipients.Add(email)
                recipient.Type = 1  # olTo (required attendee)

        appt.Recipients.ResolveAll()

        # Teams meeting
        teams_success = False
        if teams_meeting:
            try:
                # Try to add online meeting (Teams/Skype)
                # This requires Teams add-in to be installed and user logged in

                # Method 1: Use the built-in Teams integration (Outlook 2016+)
                if hasattr(appt, 'IsOnlineMeeting'):
                    appt.IsOnlineMeeting = True
                    appt.Save()  # Save to trigger Teams integration

                    # Check if Teams link was actually generated
                    # After save, check if OnlineMeetingURL was set
                    if hasattr(appt, 'OnlineMeetingURL') and appt.OnlineMeetingURL:
                        teams_success = True
                        location = "Microsoft Teams Meeting"
                        appt.Location = location
                    else:
                        # IsOnlineMeeting was set but no URL generated
                        # This can happen if Teams add-in is not active
                        teams_success = False

                if not teams_success:
                    # Method 2: Try via GetInspector and Teams add-in command
                    try:
                        inspector = appt.GetInspector
                        # Try to find and execute Teams button
                        # CommandBars are deprecated but still work
                        if hasattr(inspector, 'CommandBars'):
                            for cb in inspector.CommandBars:
                                for ctrl in cb.Controls:
                                    if 'Teams' in str(getattr(ctrl, 'Caption', '')):
                                        ctrl.Execute()
                                        teams_success = True
                                        break
                        inspector.Close(0)  # Close without saving (already saved)
                    except Exception:
                        pass

            except Exception as e:
                # Log the error for debugging
                mcp_log(f"[Outlook] Teams integration failed: {e}")

            if not teams_success:
                # Fallback: Add note that Teams link should be added manually
                body = f"[Teams-Meeting bitte manuell hinzufügen]\n\n{body}"
                location = location or "Online (Teams)"
                appt.Location = location
        else:
            if location:
                appt.Location = location

        if body:
            appt.Body = body

        appt.ReminderSet = True
        appt.ReminderMinutesBeforeStart = reminder_minutes

        # Save, display, or send
        if display:
            # Open meeting window in Outlook for user to review/edit
            appt.Display()
            action = "in Outlook geöffnet"
        elif send_invites:
            appt.Send()
            action = "gesendet"
        else:
            appt.Save()
            action = "als Entwurf gespeichert"

        if teams_meeting:
            if teams_success:
                teams_info = " (Teams-Meeting mit Link)"
            else:
                teams_info = " (Teams-Link manuell hinzufügen)"
        else:
            teams_info = ""

        return (
            f"Besprechung {action}{teams_info}:\n"
            f"- Betreff: {subject}\n"
            f"- Datum: {date_str}\n"
            f"- Zeit: {start_time} - {end_time}\n"
            f"- Ort: {location or '(keiner)'}\n"
            f"- Teilnehmer: {', '.join(attendee_list)}\n"
            f"- Erinnerung: {reminder_minutes} Min. vorher"
        )

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_create_teams_meeting(
    subject: str,
    date_str: str,
    start_time: str,
    end_time: str,
    attendees: str,
    body: str = "",
    reminder_minutes: int = 15
) -> str:
    """Erstellt eine Teams-Besprechung und öffnet sie in Outlook zur Bearbeitung.

    WICHTIG: Die Einladung wird NICHT automatisch gesendet!
    Der Benutzer kann in Outlook den Teams-Link hinzufügen und dann manuell senden.

    Args:
        subject: Betreff der Besprechung
        date_str: Datum im Format TT.MM.JJJJ
        start_time: Startzeit im Format HH:MM
        end_time: Endzeit im Format HH:MM
        attendees: Teilnehmer E-Mail-Adressen (kommagetrennt)
        body: Beschreibung/Agenda (optional)
        reminder_minutes: Erinnerung in Minuten (Standard: 15)

    Returns:
        Bestätigung mit Besprechungsdetails
    """
    return outlook_create_meeting(
        subject=subject,
        date_str=date_str,
        start_time=start_time,
        end_time=end_time,
        attendees=attendees,
        location="Microsoft Teams Meeting",
        body=body,
        teams_meeting=True,
        reminder_minutes=reminder_minutes,
        send_invites=False,
        display=True  # Open in Outlook for user to add Teams link and send
    )
