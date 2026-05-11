# MCP Tools Reference

Du hast Zugriff auf folgende Tools:

## Outlook - E-Mails
- `outlook_get_selected_email` - Markierte E-Mail lesen (erste bei Mehrfachauswahl)
- `outlook_get_selected_emails()` - **ALLE markierten E-Mails** als JSON (für Mehrfachauswahl)
- `outlook_delete_selected_email` - Markierte E-Mail löschen (→ Gelöschte Elemente)
- `outlook_delete_email(query, index)` - E-Mail per Suche löschen (index=0 für neueste)
- `outlook_delete_emails_from_sender(sender, mailbox, dry_run)` - **Bulk-Delete von Absender** (AdvancedSearch, schnell!)
- `outlook_move_emails_from_sender(sender, target_folder, mailbox, dry_run)` - **Bulk-Move von Absender** (AdvancedSearch, schnell!)
- `outlook_get_recent_emails(days, date_from, date_to, sender, ...)` - E-Mails mit Datumsfilter aus allen Postfächern
- `outlook_get_unread_emails` - Ungelesene E-Mails
- `outlook_search_emails` - E-Mails suchen (langsam, ohne Index, nur Inbox)
- `outlook_fast_search_emails(query, all_mailboxes)` - **Schnelle E-Mail-Suche** (nutzt Index, alle Ordner inkl. Unterordner)
- `outlook_fast_get_email_content(query, all_mailboxes)` - E-Mail-Inhalt aus schneller Suche (alle Ordner)
- `outlook_get_email_content` - E-Mail-Inhalt aus Suchergebnissen
- `outlook_create_reply_draft(body, reply_all=True)` - Antwort-Entwurf erstellen (Standard: Allen antworten)
- `outlook_create_reply_draft_with_attachment(body, path, reply_all=True)` - **Antwort mit Anhang** (z.B. Angebot-PDF)
- `outlook_update_draft(body, replace=False)` - **Zuletzt erstellten Entwurf aktualisieren**
- `outlook_create_new_email` - Neue E-Mail erstellen
- `outlook_create_new_email_with_attachment(to, subject, body, path)` - Neue E-Mail mit Anhang
- `outlook_flag_selected_email` - Ausgewählte E-Mail flaggen (followup/complete/clear)
- `outlook_flag_email` - E-Mail per Suche flaggen
- `outlook_move_selected_email` - Ausgewählte E-Mail in Ordner verschieben
- `outlook_move_email` - E-Mail per Suche in Ordner verschieben
- `outlook_list_mail_folders` - Verfügbare Ordner auflisten

**Empfehlung:** Nutze `outlook_fast_search_emails` statt `outlook_search_emails` für schnellere Suche.

**Vollständige Suche über alle Postfächer:**
```python
# Suche in ALLEN Postfächern und ALLEN Ordnern (inkl. Unterordner)
outlook_fast_search_emails("Rechnungsnummer 12345", all_mailboxes=True)

# Suche nur im Standard-Postfach, aber alle Ordner
outlook_fast_search_emails("Microsoft Invoice")  # Durchsucht alle Ordner inkl. Unterordner
```

## Outlook - Anhänge lesen

- `outlook_get_email_attachments(query, index, selection_index)` - **Liste aller Anhänge** einer E-Mail
- `outlook_save_email_attachment(attachment_index, query, email_index, save_path, selection_index)` - **Anhang speichern**
- `outlook_read_pdf_attachment(attachment_index, query, email_index, selection_index)` - **PDF-Text extrahieren**

**Parameter `selection_index`:** Bei Mehrfachauswahl welche E-Mail (1-basiert). Standard: 1

**Workflow: PDF-Rechnung aus E-Mail lesen**
```python
# 1. Markierte E-Mail - Anhänge auflisten
outlook_get_email_attachments()   # → [0] Bestellung.pdf (125 KB)

# 2. PDF-Text extrahieren
outlook_read_pdf_attachment(0)    # → Textinhalt des PDFs
```

## Outlook - Archivierung (Entry-ID basiert)

Tools für das Archivieren von E-Mails über Entry-ID (aus `outlook_get_folder_emails`, `outlook_get_recent_emails`, etc.):

- `outlook_get_email_attachments_by_id(entry_id)` - **Anhänge einer E-Mail auflisten**
- `outlook_read_pdf_attachment_by_id(entry_id, attachment_index)` - **PDF-Text extrahieren** (ohne Speichern)
- `outlook_save_attachment_by_entry_id(entry_id, attachment_index, save_path)` - **Anhang speichern**
- `outlook_save_email_as_pdf(entry_id, save_path, filename)` - **E-Mail als PDF speichern** (Word-Export)

**Workflow: PDF-Rechnung prüfen (ohne Speichern)**
```python
# 1. E-Mails abrufen
emails = outlook_get_recent_emails(days=7)

# 2. Für Rechnung: PDF-Inhalt lesen
pdf_text = outlook_read_pdf_attachment_by_id(entry_id)
# → Prüfen auf "Visa", "PayPal", "Lastschrift" = bereits bezahlt
```

**Workflow: E-Mails aus Ordner archivieren**
```python
# 1. E-Mails aus Ordner laden
emails = outlook_get_folder_emails("DoneInvoices", limit=100)

# 2. Pro E-Mail: Anhänge prüfen
attachments = outlook_get_email_attachments_by_id(entry_id)

# 3a. PDF-Anhang vorhanden → Anhang speichern
outlook_save_attachment_by_entry_id(entry_id, 0, "Z:")

# 3b. Kein PDF → E-Mail als PDF speichern
outlook_save_email_as_pdf(entry_id, "Z:")
```

## Outlook - Generic E-Mail Functions (JSON mit entry_id)

Alle Funktionen liefern JSON mit `entry_id` für `outlook_batch_email_actions()`:

- `outlook_get_flagged_emails(limit, include_completed, dedupe_threads)` - **Geflaggte + Erledigte E-Mails aus ALLEN Ordnern**
  - Scannt Inbox + alle Unterordner
  - `dedupe_threads=True` (Standard) - Zeigt nur neueste E-Mail pro Thread
  - Liefert: `{"flagged": [...], "completed": [...]}`
  - Completed (flag_status=1) → sollten nach Done verschoben werden
- `outlook_get_recent_emails(days, date_from, date_to, sender, exclude_folders, exclude_flagged)` - **E-Mails mit Datumsfilter**
  - `days`: Zeitraum in Tagen (Standard: 7). Wird ignoriert wenn `date_from` gesetzt.
  - `date_from`: Start-Datum (YYYY-MM-DD oder DD.MM.YYYY). Überschreibt `days`.
  - `date_to`: End-Datum (YYYY-MM-DD oder DD.MM.YYYY). Standard: heute.
  - `sender`: Nur E-Mails von diesem Absender (Name oder E-Mail, case-insensitive)
  - `exclude_flagged=True`: Geflaggte E-Mails ausschließen (offene Todos)
  - Scannt Inbox aller Mailboxen
  - Liefert: JSON-Array mit E-Mails, sortiert nach Datum

**Beispiele für Datumsfilter:**
```python
# Letzte 14 Tage
outlook_get_recent_emails(days=14)

# Bestimmter Zeitraum (ISO oder deutsches Format)
outlook_get_recent_emails(date_from="2025-12-01", date_to="2025-12-31")
outlook_get_recent_emails(date_from="01.12.2025", date_to="31.12.2025")

# E-Mails von bestimmtem Absender in den letzten 14 Tagen
outlook_get_recent_emails(days=14, sender="Erika Musterfrau")

# Kombination: Absender + Zeitraum
outlook_get_recent_emails(date_from="22.12.2025", sender="erika")
```
- `outlook_get_folder_emails(folder, limit)` - **ALLE E-Mails aus einem Ordner**
  - Für Arbeitsqueues wie ToOffer, ToPay
  - Liefert: JSON-Array mit E-Mails

## Outlook - Batch-Actions ⚡

- `outlook_batch_email_actions(actions)` - **Mehrere Move/Flag/Delete in 1 Call**

**Batch-Aktionen Format:**
```json
[
  {"action": "move", "entry_id": "AAA...", "folder": "ToDelete"},
  {"action": "move", "entry_id": "BBB...", "folder": "Invoices", "mailbox": "user@example.com"},
  {"action": "flag", "entry_id": "CCC...", "flag_type": "followup"},
  {"action": "delete", "entry_id": "DDD..."}
]
```

**Same-Mailbox Default:** E-Mails bleiben standardmäßig in ihrer eigenen Mailbox. Ordner werden nur dort gesucht/erstellt.

**Cross-Mailbox Move:** Mit `"mailbox": "name@domain.com"` kann explizit in einen Ordner einer anderen Mailbox verschoben werden.

**Daily Check Workflow:**
```python
# 1. Daten parallel abrufen
outlook_get_flagged_emails()                              # Offene Todos + Erledigte
outlook_get_recent_emails(days=7, exclude_folders=["ToDelete"])   # Letzte 7 Tage
outlook_get_folder_emails("ToOffer")                      # Angebotsanfragen
outlook_get_folder_emails("ToPay")                        # Rechnungen

# 2. Aktionen sammeln und ausführen
outlook_batch_email_actions([...])
```

## Outlook - Kalender
- `outlook_get_today_events` - Heutige Termine anzeigen
- `outlook_get_upcoming_events(days=21)` - Termine der nächsten X Tage (z.B. 21 für 3 Wochen)
- `outlook_get_calendar_event_details` - Termindetails nach Betreff suchen
- `outlook_check_availability(date_str, start_time, end_time)` - Prüfen ob Zeitslot frei ist
- `outlook_create_appointment(subject, date, start, end, location, body)` - **Termin erstellen**
- `outlook_create_meeting(subject, date, start, end, attendees, teams_meeting)` - **Besprechung mit Teilnehmern**
- `outlook_create_teams_meeting(subject, date, start, end, attendees)` - **Teams-Meeting erstellen**

**Kalender-Beispiele:**
```python
# Einfacher Termin
outlook_create_appointment("Arzttermin", "15.01.2025", "10:00", "11:00", location="Praxis Dr. Müller")

# Meeting mit Teilnehmern
outlook_create_meeting("Projektbesprechung", "16.01.2025", "14:00", "15:00",
               attendees="max@example.com, anna@example.com")

# Teams-Meeting
outlook_create_teams_meeting("Sprint Review", "17.01.2025", "09:00", "10:00",
                     attendees="team@company.com", body="Agenda:\n- Demo\n- Feedback")
```

## Microsoft Graph - Server-Suche (alle E-Mails)

Die lokale Outlook-Suche (`outlook_fast_search_emails`) findet nur lokal gecachte E-Mails.
Für eine vollständige Suche aller E-Mails auf dem Exchange-Server nutze Microsoft Graph:

- `graph_authenticate()` - **Authentifizierung starten** (Device Code Flow)
- `graph_complete_auth()` - Authentifizierung abschließen
- `graph_status()` - Aktuellen Auth-Status prüfen
- `graph_search_emails(query, limit, has_attachments, date_from, date_to)` - **Server-seitige E-Mail-Suche**
- `graph_get_recent_emails(days, limit, inbox_only=True)` - Neueste E-Mails abrufen (Standard: nur Inbox)
- `graph_get_flagged_emails(limit, include_completed, mailbox)` - **Geflaggte E-Mails aus Office 365** (für "Auswahl" via Flag)
- `graph_get_folder_emails(folder_name, limit, mailbox)` - **E-Mails aus Ordner** (ToOffer, ToPay, DoneInvoices)
- `graph_get_email(message_id)` - Vollständigen E-Mail-Inhalt lesen
- `graph_get_attachments(message_id)` - **Anhänge einer E-Mail auflisten**
- `graph_download_attachment(message_id, attachment_id, save_path)` - **Anhang herunterladen**
- `graph_list_mailboxes()` - Verfügbare Postfächer auflisten

**WICHTIG - Search Syntax:**
```python
# ✅ RICHTIG: Einfache Keywords
graph_search_emails("EnBW Rechnung")
graph_search_emails("Adobe invoice")

# ✅ RICHTIG: Mit Filter-Parametern
graph_search_emails("EnBW", has_attachments=True, date_from="2025-11-01", date_to="2025-11-30")

# ❌ FALSCH: Komplexe Operatoren funktionieren NICHT!
graph_search_emails("subject:EnBW AND from:adobe has:attachment")  # → Wird automatisch bereinigt
```

**Wann Graph statt Outlook verwenden:**
| Szenario | Tool |
|----------|------|
| Aktuelle E-Mails (letzte 30 Tage) | `outlook_fast_search_emails` (schneller) |
| Ältere E-Mails / vollständige Suche | `graph_search_emails` (findet alles) |
| Offline-Nutzung | Outlook-Tools (COM API) |

**Workflow: Anhang herunterladen**
```python
# 1. E-Mail suchen
graph_search_emails("EnBW Rechnung", has_attachments=True)
# → ID: AAMkAGFl...

# 2. Anhänge auflisten (gibt VOLLSTÄNDIGE attachment_id zurück!)
graph_get_attachments("AAMkAGFl...")
# → [0] Rechnung.pdf (125 KB)
#       attachment_id: AAMkAGFl...FULL_ID...

# 3. Anhang herunterladen (VOLLE attachment_id verwenden!)
graph_download_attachment("AAMkAGFl...", "AAMkAGFl...FULL_ID...", ".temp/invoices")
# → SUCCESS: Downloaded and verified: .temp/invoices/Rechnung.pdf (125000 bytes)
# → ERROR: HTTP 404... (wenn IDs falsch/unvollständig)
```

**WICHTIG:** Nur "SUCCESS:" bedeutet tatsächlicher Erfolg. Bei "ERROR:" wurde NICHTS gespeichert!

**Workflow: E-Mail via Flag "auswählen" (Office 365)**
```python
# Alternative zu outlook_get_selected_email() für Office 365 ohne lokales Outlook:
# 1. E-Mail in Outlook Web/Mobile/Desktop flaggen
# 2. Geflaggte E-Mails abrufen (Flag synct zum Server!)
graph_get_flagged_emails()
# → {"flagged": [{"id": "AAMk...", "subject": "...", ...}], "completed": [], "total": 1}

# 3. E-Mail-Inhalt lesen
graph_get_email("AAMk...")

# 4. Verarbeiten (Antwort erstellen, archivieren, etc.)

# 5. Flag entfernen wenn fertig
graph_flag_email("AAMk...", "notFlagged")
```

## Microsoft Graph - Kalender

Kalender-Events lesen und erstellen via Graph API:

- `graph_get_upcoming_events(days, mailbox)` - **Termine der nächsten X Tage** (Standard: 2)
- `graph_get_today_events(mailbox)` - Heutige Termine
- `graph_create_calendar_event(subject, start_datetime, end_datetime, attendees, body, is_online_meeting)` - **Termin/Meeting erstellen**

**Termin erstellen:**
```python
# Teams Meeting mit Teilnehmern
graph_create_calendar_event(
    subject="Projekt-Besprechung",
    start_datetime="2025-01-15T14:00:00",
    end_datetime="2025-01-15T15:00:00",
    attendees="max@example.com, anna@example.com",
    body="Agenda:\n- Status-Update\n- Nächste Schritte",
    is_online_meeting=True  # Teams-Link wird automatisch generiert
)
# → Teams Meeting erstellt, Einladungen werden gesendet

# Einfacher Termin ohne Teilnehmer
graph_create_calendar_event(
    subject="Arzttermin",
    start_datetime="2025-01-16T10:00:00",
    end_datetime="2025-01-16T11:00:00",
    is_online_meeting=False,
    location="Praxis Dr. Müller"
)
```

**Parameter für `graph_create_calendar_event`:**
| Parameter | Beschreibung |
|-----------|--------------|
| `subject` | Betreff/Titel |
| `start_datetime` | Start im ISO-Format (YYYY-MM-DDTHH:MM:SS), lokale Zeit |
| `end_datetime` | Ende im ISO-Format |
| `attendees` | Kommagetrennte E-Mail-Adressen (optional) |
| `body` | Beschreibung/Agenda (optional) |
| `location` | Ort (optional, ignoriert bei Online-Meeting) |
| `is_online_meeting` | `true` für Teams-Link (Standard: true) |
| `mailbox` | Kalender eines anderen Users (optional) |

**Hinweis:** Zeiten sind in deutscher Lokalzeit (Europe/Berlin). Teams-Link wird automatisch generiert wenn `is_online_meeting=true`.

## Microsoft Graph - Teams

Teams-Chats und -Kanäle lesen und schreiben:

**Chats (1:1 und Gruppen):**
- `teams_get_chats(limit, filter_participant)` - Chats auflisten
- `teams_get_messages(chat_id, limit)` - Chat-Nachrichten lesen
- `teams_send_message(chat_id, message)` - Nachricht senden (als User)

**Teams & Kanäle:**
- `teams_list_teams()` - Alle Teams auflisten
- `teams_list_channels(team_id)` - Kanäle eines Teams
- `teams_get_channel_messages(team_id, channel_id, limit)` - Kanal-Nachrichten lesen
- `teams_post_to_channel(team_id, channel_id, message, subject)` - Nachricht posten (als User)

**Webhook-basiert (als "DeskAgent"):**
- `teams_post_webhook(webhook_url, message, title)` - Direkt via Webhook-URL
- `teams_post_to_configured_channel(channel_name, message, title)` - **Via konfigurierte Channels**

**Workflow: Nachricht als DeskAgent senden (empfohlen)**
```python
# Einfach mit konfiguriertem Channel-Namen
teams_post_to_configured_channel("deskagent", "Build erfolgreich!", title="CI/CD")
```

**Webhook erstellen (New Teams - Power Automate):**
1. Teams Channel → `...` → **Workflows**
2. Suche: "Post to a channel when a webhook request is received"
3. Name: "DeskAgent", Channel auswählen
4. HTTP POST URL kopieren → in `apis.json` unter `msgraph.webhooks` eintragen

**Webhook erstellen (Classic Teams):**
1. Teams Channel → `...` → Connectors → Incoming Webhook
2. Name: "DeskAgent", Icon hochladen
3. URL kopieren → in `apis.json` unter `msgraph.webhooks` eintragen

**Workflow: Nachricht als User senden**
```python
# 1. Teams auflisten
teams_list_teams()

# 2. Kanäle auflisten
teams_list_channels("abc123...")

# 3. Nachricht posten (erscheint als angemeldeter User)
teams_post_to_channel("abc123...", "def456...", "Hallo Team!", subject="Update")
```

**Konfiguration in apis.json:**
```json
"msgraph": {
  "client_id": "YOUR_AZURE_APP_CLIENT_ID",
  "tenant_id": "common",
  "webhooks": {
    "deskagent": "https://...webhook.office.com/webhookb2/...",
    "general": "https://...webhook.office.com/webhookb2/..."
  }
}
```

**Azure AD App erstellen:**
1. Azure Portal → Azure Active Directory → App registrations
2. New registration → Name: "DeskAgent"
3. Supported account types: "Accounts in any organizational directory"
4. Redirect URI: Mobile and desktop applications → `https://login.microsoftonline.com/common/oauth2/nativeclient`
5. API permissions → Add:
   - Mail: `Mail.Read`, `Mail.ReadWrite`
   - User: `User.Read`
   - Teams: `Chat.Read`, `Chat.ReadWrite`, `ChatMessage.Send`, `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `ChannelMessage.Read.All`, `ChannelMessage.Send`
6. Client ID kopieren → in apis.json eintragen

## Microsoft Graph - Teams Watcher (Auto-Response)

Automatische Agent-Antworten auf Teams-Kanal-Nachrichten via Graph API Polling.

**Setup:**
```python
# 1. Watcher einrichten (sucht Kanal, speichert IDs, aktiviert)
teams_setup_watcher('deskagent')

# 2. DeskAgent neu starten - Polling beginnt
```

**Konfiguration in `deskagent/config/triggers.json`:**
```json
{
  "triggers": [
    {
      "id": "teams_deskagent",
      "type": "teams_channel",
      "name": "Teams DeskAgent Channel",
      "enabled": true,
      "team_id": "abc123...",
      "channel_id": "def456...",
      "poll_interval": 10,
      "response_webhook": "deskagent",
      "agent": "chat"
    }
  ]
}
```

| Option | Beschreibung |
|--------|--------------|
| `enabled` | Watcher aktiv (true/false) |
| `poll_interval` | Polling-Intervall in Sekunden (Standard: 10) |
| `response_webhook` | Webhook-Name aus `apis.json` für Antworten |
| `agent` | Agent der auf Nachrichten antwortet |

**API Endpoints:**
- `GET /teams-watcher` - Status und Statistiken
- `POST /teams-watcher/start` - Watcher starten
- `POST /teams-watcher/stop` - Watcher stoppen
- `POST /teams-watcher/clear` - State zurücksetzen

**Flow:**
1. Graph API pollt Kanal alle X Sekunden
2. Neue Nachrichten (nicht von Bots) werden erkannt
3. Konfigurierter Agent wird mit Nachricht als Prompt ausgeführt
4. Agent antwortet via `teams_post_to_configured_channel()`

## Gmail - E-Mails

Gmail-Integration via Google API mit OAuth2-Authentifizierung.

**Authentifizierung:**
- `gmail_authenticate()` - **OAuth2 Anmeldung starten** (Browser-Flow)
- `gmail_status()` - Aktuellen Auth-Status prüfen
- `gmail_logout()` - Abmelden und Credentials löschen
- `gmail_refresh_token()` - Token manuell aktualisieren

**E-Mail-Operationen:**
- `gmail_search_emails(query, limit, include_spam_trash)` - **E-Mails suchen** (Gmail-Syntax)
- `gmail_get_email(message_id)` - Vollständigen E-Mail-Inhalt lesen
- `gmail_get_recent_emails(days, limit, label)` - Neueste E-Mails abrufen
- `gmail_get_emails_by_label(label, limit)` - E-Mails mit bestimmtem Label
- `gmail_get_unread_emails(limit)` - Ungelesene E-Mails
- `gmail_get_starred_emails(limit)` - Markierte E-Mails (wie Outlook Flags)
- `gmail_get_thread(thread_id)` - Gesamte Konversation lesen
- `gmail_mark_read(message_id, is_read)` - Als gelesen/ungelesen markieren
- `gmail_get_profile()` - Profilinformationen (E-Mail, Nachrichten-Anzahl)

**Entwürfe & Senden:**
- `gmail_create_draft(to, subject, body, cc, html)` - E-Mail-Entwurf erstellen
- `gmail_create_reply_draft(message_id, body, reply_all, from_email)` - **Antwort mit zitiertem Original** (inkl. "On [date], [sender] wrote:")
- `gmail_send_draft(draft_id)` - Entwurf senden

**Gmail Query Syntax:**
```python
# Absender/Empfänger
gmail_search_emails("from:sender@example.com")
gmail_search_emails("to:recipient@example.com")

# Betreff/Inhalt
gmail_search_emails("subject:Rechnung")
gmail_search_emails("invoice payment")  # Volltextsuche

# Filter
gmail_search_emails("has:attachment")
gmail_search_emails("is:unread")
gmail_search_emails("is:starred")

# Datum
gmail_search_emails("after:2025/01/01")
gmail_search_emails("before:2025/12/31")

# Label (Ordner)
gmail_search_emails("label:INBOX")
gmail_search_emails("label:Work")

# Kombiniert
gmail_search_emails("from:example.com subject:invoice after:2025/01/01 has:attachment")
```

## Gmail - Labels & Aktionen

Gmail verwendet Labels statt Ordner (ein E-Mail kann mehrere Labels haben).

**Label-Verwaltung:**
- `gmail_list_labels()` - Alle Labels auflisten
- `gmail_create_label(name, background_color, text_color)` - Neues Label erstellen
- `gmail_delete_label(label_id)` - Label löschen

**E-Mail-Aktionen:**
- `gmail_add_label(message_id, label)` - Label hinzufügen (wie Ordner-Move)
- `gmail_remove_label(message_id, label)` - Label entfernen
- `gmail_star_email(message_id, starred)` - Markieren/Entmarkieren (wie Flag)
- `gmail_archive_email(message_id)` - Archivieren (aus Inbox entfernen)
- `gmail_trash_email(message_id)` - In Papierkorb verschieben
- `gmail_untrash_email(message_id)` - Aus Papierkorb wiederherstellen
- `gmail_delete_email(message_id)` - **Permanent löschen** (nicht wiederherstellbar!)

**Batch-Aktionen:**
- `gmail_batch_actions(actions)` - **Mehrere Aktionen in einem Call**

**Batch-Format:**
```json
[
  {"action": "add_label", "message_id": "...", "label": "Work"},
  {"action": "star", "message_id": "..."},
  {"action": "archive", "message_id": "..."},
  {"action": "mark_read", "message_id": "..."}
]
```

**Verfügbare Batch-Aktionen:** `add_label`, `remove_label`, `star`, `unstar`, `archive`, `trash`, `untrash`, `mark_read`, `mark_unread`

## Gmail - Anhänge

- `gmail_get_attachments(message_id)` - **Anhänge einer E-Mail auflisten**
- `gmail_download_attachment(message_id, attachment_id, save_path)` - Anhang herunterladen
- `gmail_download_all_attachments(message_id, save_path)` - Alle Anhänge herunterladen
- `gmail_read_pdf_attachment(message_id, attachment_id)` - **PDF-Text extrahieren** (ohne Speichern)

**Workflow: PDF-Rechnung lesen**
```python
# 1. E-Mail suchen
gmail_search_emails("from:lieferant@example.com has:attachment")

# 2. Anhänge auflisten
gmail_get_attachments("message_id_123")
# → [{"index": 0, "filename": "Rechnung.pdf", "attachment_id": "att_456", ...}]

# 3. PDF-Text direkt lesen (ohne Download)
gmail_read_pdf_attachment("message_id_123", "att_456")
# → "Rechnungsnummer: RE-2025-001..."
```

## Gmail - Google Calendar

Kalender-Operationen mit Google Calendar API.

**Termine anzeigen:**
- `gcal_get_today_events()` - Heutige Termine
- `gcal_get_upcoming_events(days)` - Termine der nächsten X Tage
- `gcal_get_event_details(event_id)` - Vollständige Termindetails
- `gcal_list_calendars()` - Alle Kalender auflisten
- `gcal_check_availability(date, start_time, end_time)` - Prüfen ob Zeitslot frei ist

**Termine erstellen:**
- `gcal_create_event(subject, date, start, end, location, description)` - **Termin erstellen**
- `gcal_create_meeting(subject, date, start, end, attendees, add_meet_link)` - **Meeting mit Teilnehmern**
- `gcal_delete_event(event_id)` - Termin löschen

**Beispiele:**
```python
# Einfacher Termin
gcal_create_event(
    subject="Arzttermin",
    date_str="15.01.2025",
    start_time="10:00",
    end_time="11:00",
    location="Praxis Dr. Müller"
)

# Meeting mit Google Meet Link
gcal_create_meeting(
    subject="Projekt-Besprechung",
    date_str="16.01.2025",
    start_time="14:00",
    end_time="15:00",
    attendees="max@example.com, anna@example.com",
    description="Agenda:\n- Status-Update\n- Nächste Schritte",
    add_meet_link=True  # Standard: True
)
# → Google Meet Link wird automatisch generiert
```

## Gmail - Konfiguration

**apis.json:**
```json
"gmail": {
  "enabled": true,
  "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
  "client_secret": "YOUR_CLIENT_SECRET",
  "redirect_port": 8080
}
```

**Google Cloud Setup:**
1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) öffnen
2. Projekt erstellen (oder vorhandenes auswählen)
3. APIs aktivieren: **Gmail API** und **Google Calendar API**
4. OAuth 2.0 Credentials erstellen (Typ: **Desktop-App**)
5. `client_id` und `client_secret` in apis.json eintragen
6. `gmail_authenticate()` aufrufen → Browser öffnet Google Login

**Tool-Mapping: Gmail vs Outlook vs Graph**

| Operation | Gmail | Outlook | MS Graph |
|-----------|-------|---------|----------|
| E-Mails suchen | `gmail_search_emails` | `outlook_fast_search_emails` | `graph_search_emails` |
| E-Mail lesen | `gmail_get_email` | `outlook_get_email_content` | `graph_get_email` |
| Neueste E-Mails | `gmail_get_recent_emails` | `outlook_get_recent_emails` | `graph_get_recent_emails` |
| Entwurf erstellen | `gmail_create_draft` | `outlook_create_new_email` | `graph_create_draft` |
| Antwort-Entwurf | `gmail_create_reply_draft` | `outlook_create_reply_draft` | `graph_create_reply_draft` |
| Markieren/Flag | `gmail_star_email` | `outlook_flag_email` | `graph_flag_email` |
| Labels/Ordner | `gmail_add_label` | `outlook_move_email` | `graph_move_email` |
| Anhänge | `gmail_get_attachments` | `outlook_get_email_attachments` | `graph_get_attachments` |
| Heutige Termine | `gcal_get_today_events` | `outlook_get_today_events` | `graph_get_today_events` |
| Termin erstellen | `gcal_create_event` | `outlook_create_appointment` | `graph_create_calendar_event` |

## IMAP/SMTP - E-Mails (Standard-Protokolle)

Standard IMAP/SMTP MCP für E-Mail-Provider ohne spezielle API (z.B. eigener Mailserver, Provider-E-Mails).

**Besonderheit: Custom IMAP Flags (Keywords)**
- Setze eigene Flags wie "NeedsReview", "Processed", "Urgent" auf E-Mails
- Suche nach Custom Flags für Workflow-Automatisierung
- Unabhängig von Provider-spezifischen Features

### IMAP - E-Mail Lesen

- `imap_list_folders()` - **Alle IMAP-Ordner auflisten**
- `imap_search_emails(folder, search_criteria, limit)` - **E-Mails suchen**
  - Unterstützt IMAP-Suchkriterien: ALL, UNSEEN, FLAGGED, FROM, SUBJECT, BODY, SINCE, BEFORE, KEYWORD
- `imap_get_email(uid, folder)` - **Vollständigen E-Mail-Inhalt lesen**
- `imap_get_recent_emails(folder, days, limit, only_unseen)` - **E-Mails der letzten N Tage**
- `imap_get_unread_emails(folder, limit)` - **Ungelesene E-Mails**
- `imap_get_flagged_emails(folder, limit)` - **Geflaggte E-Mails**

**IMAP Suchkriterien Beispiele:**
```python
# Alle E-Mails
imap_search_emails("INBOX", "ALL")

# Ungelesen
imap_search_emails("INBOX", "UNSEEN")

# Von bestimmtem Absender
imap_search_emails("INBOX", "FROM sender@example.com")

# Betreff enthält Keyword
imap_search_emails("INBOX", "SUBJECT invoice")

# Seit Datum
imap_search_emails("INBOX", "SINCE 1-Jan-2025")

# Kombiniert
imap_search_emails("INBOX", "(FROM example.com UNSEEN)")

# Mit Custom Flag
imap_search_emails("INBOX", "KEYWORD NeedsReview")
```

### IMAP - Custom Flags (Keywords)

**Custom Flags** ermöglichen Workflow-Automatisierung unabhängig vom E-Mail-Provider:

- `imap_get_flags(uid, folder)` - **Alle Flags einer E-Mail** (Standard + Custom)
- `imap_set_custom_flag(uid, keyword, folder)` - **Custom Flag setzen**
  - Beispiel: `imap_set_custom_flag("123", "NeedsReview", "INBOX")`
- `imap_remove_custom_flag(uid, keyword, folder)` - **Custom Flag entfernen**
- `imap_search_by_custom_flag(keyword, folder, limit)` - **Nach Custom Flag suchen**
  - Beispiel: `imap_search_by_custom_flag("Processed", "INBOX")`
- `imap_list_custom_flags(folder)` - **Alle Custom Flags im Ordner auflisten**

**Workflow-Beispiel:**
```python
# 1. E-Mails suchen die Review benötigen
emails = imap_search_emails("INBOX", "FROM support@example.com UNSEEN")

# 2. Custom Flag setzen für Workflow
imap_set_custom_flag("123", "NeedsReview", "INBOX")

# 3. Später: Alle Review-E-Mails finden
review_emails = imap_search_by_custom_flag("NeedsReview", "INBOX")

# 4. Nach Bearbeitung: Flag entfernen, neues setzen
imap_remove_custom_flag("123", "NeedsReview", "INBOX")
imap_set_custom_flag("123", "Processed", "INBOX")
```

**Standard IMAP Flags:**
- `imap_set_flag(uid, flag, folder)` - **Standard Flag setzen**
  - `\\Seen` - Als gelesen markieren
  - `\\Flagged` - Flaggen/Markieren
  - `\\Answered` - Als beantwortet markieren
  - `\\Draft` - Als Entwurf markieren
  - `\\Deleted` - Zum Löschen markieren
- `imap_remove_flag(uid, flag, folder)` - **Standard Flag entfernen**

### SMTP - E-Mails Senden

- `smtp_send_email(to, subject, body, cc, bcc, html, reply_to)` - **E-Mail senden**
  - Plain Text oder HTML
  - CC/BCC Unterstützung
  - Reply-To Header
- `smtp_send_with_attachment(to, subject, body, attachment_path, ...)` - **E-Mail mit Anhang**
- `smtp_send_reply(to, subject, body, in_reply_to, references, cc, html)` - **Antwort mit Threading**
  - In-Reply-To und References Headers für korrekte Konversations-Zuordnung

**Beispiele:**
```python
# Einfache E-Mail
smtp_send_email(
    to="customer@example.com",
    subject="Re: Your inquiry",
    body="Thank you for your message..."
)

# Mit Anhang
smtp_send_with_attachment(
    to="customer@example.com",
    subject="Your invoice",
    body="Please find attached...",
    attachment_path="/path/to/invoice.pdf"
)

# Antwort mit Threading
smtp_send_reply(
    to="customer@example.com",
    subject="Re: Support Request #123",
    body="We have resolved your issue...",
    in_reply_to="<message-id@example.com>",
    references="<thread-id@example.com> <message-id@example.com>"
)
```

### IMAP - E-Mail Management

- `imap_move_email(uid, source_folder, target_folder)` - **E-Mail verschieben**
- `imap_copy_email(uid, source_folder, target_folder)` - **E-Mail kopieren**
- `imap_delete_email(uid, folder, expunge)` - **E-Mail löschen**
  - `expunge=True`: Sofort permanent löschen
  - `expunge=False`: Nur als gelöscht markieren

**Ordner-Management:**
- `imap_create_folder(folder_name)` - **Ordner erstellen**
- `imap_delete_folder(folder_name)` - **Ordner löschen** (muss leer sein)
- `imap_rename_folder(old_name, new_name)` - **Ordner umbenennen**

### IMAP/SMTP - Konfiguration

**apis.json:**
```json
"imap": {
  "enabled": true,
  "imap_host": "imap.example.com",
  "imap_port": 993,
  "imap_user": "user@example.com",
  "imap_password": "your-password",
  "imap_ssl": true,
  "smtp_host": "smtp.example.com",
  "smtp_port": 587,
  "smtp_user": "user@example.com",
  "smtp_password": "your-password",
  "smtp_tls": true
}
```

**Hinweise:**
- IMAP Port: 993 (SSL), 143 (unverschlüsselt, nicht empfohlen)
- SMTP Port: 587 (STARTTLS), 465 (SSL)
- `imap_ssl`: SSL-Verschlüsselung für IMAP (empfohlen)
- `smtp_tls`: STARTTLS für SMTP (empfohlen)

**Kompatibilität:**
- Funktioniert mit allen IMAP/SMTP-kompatiblen Servern
- Getestet mit: Gmail, Office 365, Exchange, Dovecot, Postfix
- **Custom Flags**: Nicht alle Server unterstützen Keywords (prüfe PERMANENTFLAGS)

## Billomat - Kunden
- `billomat_search_customers` - Kunden suchen
- `billomat_get_customer` - Kundendetails abrufen
- `billomat_create_customer` - Neuen Kunden anlegen
- `billomat_update_customer` - Kundendaten aktualisieren

## Billomat - Angebote
- `billomat_create_offer` - Angebot erstellen (Entwurf)
- `billomat_get_offer` - Angebotsdetails abrufen
- `billomat_get_recent_offers` - Letzte Angebote
- `billomat_add_offer_item` - Produkt zum Angebot hinzufügen
- `billomat_get_offer_items` - Angebotspositionen anzeigen
- `billomat_finalize_offer(offer_id)` - **Angebot finalisieren** (Status → OPEN)
- `billomat_download_offer_pdf(offer_id)` - **PDF herunterladen** (für E-Mail-Anhang)

**Workflow: Angebot erstellen und versenden**
```
1. billomat_create_offer(customer_id)        → Entwurf erstellen
2. billomat_add_offer_item(offer_id, "RVP1") → Produkte hinzufügen
3. billomat_finalize_offer(offer_id)         → Finalisieren
4. billomat_download_offer_pdf(offer_id)     → PDF herunterladen
5. outlook_create_reply_draft_with_attachment(body, pdf_path) → Als Antwort senden
```

## Billomat - Rechnungen
- `billomat_create_invoice(customer_id, intro, template, address, label)` - **Rechnung erstellen mit allen Optionen**
  - `intro`: Einleitungstext (z.B. "Ihre Bestellnummer: PO-12345...")
  - `template`: "rechnung-de-software" oder "rechnung-en-software"
  - `address`: Rechnungsadresse (überschreibt Kundenadresse)
- `billomat_get_recent_invoices` - Letzte Rechnungen
- `billomat_search_invoices` - Rechnungen suchen (nach Kunde, Nummer, Status)
- `billomat_get_invoice` - Rechnungsdetails abrufen
- `billomat_get_invoices_by_period(from_date, to_date, status)` - **Rechnungen nach Zeitraum** (Format: YYYY-MM-DD)
- `billomat_download_invoice_pdf(invoice_id, save_path, filename)` - **PDF herunterladen**
- `billomat_add_invoice_item` - Position zur Rechnung hinzufügen
- `billomat_add_timelog_to_invoice` - Zeiteintrag als Position hinzufügen (Standard: 150€/h)
- `billomat_add_article_to_invoice` - Artikel zur Rechnung hinzufügen
- `billomat_get_invoice_items` - Rechnungspositionen anzeigen
- `billomat_update_invoice_item` - Rechnungsposition aktualisieren
- `billomat_delete_invoice_item` - Rechnungsposition löschen

## Billomat - Zahlungen
- `billomat_get_open_invoices` - **Alle offenen/überfälligen Rechnungen** (mit Client-Cache)
- `billomat_mark_invoice_paid(invoice_id, payment_type)` - **Rechnung als bezahlt markieren** (payment_type: BANK_TRANSFER, CASH, PAYPAL, etc.)
- `billomat_open_invoice(invoice_id)` - **Rechnung im Browser öffnen**

## Billomat - Artikel
- `billomat_get_articles` - Verfügbare Produkte listen
- `billomat_search_article` - Artikel suchen

## Billomat - Batch-Tools (Performance) ⚡

- `billomat_create_complete_offer(customer_id, items, finalize)` - **Angebot mit allen Positionen in 1 Call**
- `billomat_add_invoice_items_batch(invoice_id, items)` - **Mehrere Rechnungspositionen in 1 Call**

**Angebot-Items Format:**
```json
[
  {"article": "RVP1", "quantity": 1},
  {"article": "DL4", "quantity": 2, "description": "Setup & Training"}
]
```

**Rechnungs-Items Format:**
```json
[
  {"title": "Beratung 10.12.", "hours": 2, "rate": 150},
  {"article": "RVP1", "quantity": 1}
]
```

**Performance-Gewinn:** ~80% weniger API-Calls, Artikel-Cache (1h TTL)

## Lexware Office (lexoffice) - Kontakte
- `lexware_search_contacts(query, role)` - Kontakte suchen (role: "customer" oder "vendor")
- `lexware_get_contact(contact_id)` - Kontaktdetails abrufen
- `lexware_create_contact(...)` - Neuen Kontakt anlegen
- `lexware_update_contact(contact_id, ...)` - Kontakt aktualisieren

## Lexware Office - Artikel
- `lexware_get_articles()` - Alle Artikel/Produkte auflisten
- `lexware_get_article(article_id)` - Artikeldetails abrufen
- `lexware_search_articles(query)` - Artikel nach Titel/Nummer suchen

## Lexware Office - Angebote
- `lexware_create_quotation(contact_id, title, introduction, validity_days)` - Angebot erstellen
- `lexware_get_quotation(quotation_id)` - Angebotsdetails abrufen
- `lexware_get_recent_quotations(limit)` - Letzte Angebote
- `lexware_add_quotation_item(quotation_id, title, quantity, unit_price, ...)` - Position hinzufügen
- `lexware_download_quotation_pdf(quotation_id, save_path, filename)` - **PDF herunterladen**

## Lexware Office - Rechnungen
- `lexware_create_invoice(contact_id, title, introduction, finalize)` - Rechnung erstellen
- `lexware_get_invoice(invoice_id)` - Rechnungsdetails abrufen
- `lexware_get_recent_invoices(limit)` - Letzte Rechnungen
- `lexware_add_invoice_item(invoice_id, title, quantity, unit_price, ...)` - Position hinzufügen
- `lexware_finalize_invoice(invoice_id)` - Rechnung finalisieren
- `lexware_download_invoice_pdf(invoice_id, save_path, filename)` - **PDF herunterladen**
- `lexware_get_open_invoices()` - **Offene Rechnungen auflisten**

## Lexware Office - Zahlungen & Gutschriften
- `lexware_get_payments(voucher_id)` - Zahlungen zu einem Beleg abrufen
- `lexware_create_credit_note(contact_id, title, invoice_id, finalize)` - Gutschrift erstellen
- `lexware_get_credit_note(credit_note_id)` - Gutschriftdetails abrufen

**Workflow: Angebot erstellen**
```python
# 1. Kontakt suchen oder erstellen
lexware_search_contacts("Firma XY")  # oder lexware_create_contact(...)

# 2. Angebot erstellen
lexware_create_quotation("uuid-123", title="Projektangebot", validity_days=30)

# 3. Positionen hinzufügen
lexware_add_quotation_item("quote-uuid", "Beratung", quantity=8, unit_price=150, unit="Stunde")
lexware_add_quotation_item("quote-uuid", "Software-Lizenz", quantity=1, unit_price=1098)

# 4. PDF herunterladen
lexware_download_quotation_pdf("quote-uuid")
```

**API-Details:**
- Base URL: `https://api.lexoffice.io/v1`
- Auth: Bearer Token im Authorization Header
- Rate Limit: 2 requests/second
- XL Plan erforderlich für API-Zugang

**Konfiguration in apis.json:**
```json
"lexware": {
  "api_key": "YOUR_LEXWARE_API_KEY"
}
```

**API-Key generieren:** https://app.lexoffice.de/addons/public-api

## UserEcho - Support-Tickets
- `userecho_get_forums` - Alle Foren/Kategorien auflisten
- `userecho_get_recent_new_tickets()` - **Neue Tickets für Daily Check** (Status Neu + max 14 Tage)
- `userecho_get_open_tickets(forum_id, limit, max_age_days)` - Offene Tickets (mit optionalem Altersfilter)
- `userecho_get_tickets_by_status(status)` - **Tickets nach Status** (z.B. "planned", "new", "review")
- `userecho_get_all_tickets(forum_id, status, limit)` - Tickets mit Status-Filter
- `userecho_get_ticket(ticket_id)` - Vollständige Ticket-Details mit Beschreibung
- `userecho_get_ticket_comments(ticket_id)` - Alle Kommentare/Antworten zu einem Ticket
- `userecho_search_tickets(query, limit)` - Tickets nach Suchbegriff durchsuchen
- `userecho_create_ticket_reply(ticket_id, text, is_official)` - **Antwort erstellen und senden**
- `userecho_create_ticket_reply_draft(ticket_id, text)` - Antwort-Entwurf anzeigen (ohne Senden)
- `userecho_update_ticket_status(ticket_id, status, forum_id)` - Status ändern

**Status-Werte (Helpdesk):**
- `new` - Neu (ID 1) - **KRITISCH: nie bearbeitet!**
- `review` - Under review (ID 17)
- `planned` - Planned (ID 18)
- `started` - Started (ID 19)
- `completed` - Completed (ID 20, geschlossen)

**Workflow: Support-Ticket beantworten**
```
1. userecho_get_open_tickets()              → Offene Tickets anzeigen
2. userecho_get_ticket(ticket_id)           → Details lesen
3. userecho_get_ticket_comments(ticket_id)  → Bisherige Antworten
4. userecho_create_ticket_reply_draft(ticket_id, text) → Entwurf prüfen
5. userecho_create_ticket_reply(ticket_id, text)   → Antwort senden
6. userecho_update_ticket_status(ticket_id, "answered") → Status setzen
```

**Konfiguration in apis.json:**
```json
"userecho": {
  "subdomain": "your-subdomain",
  "api_key": "YOUR_API_KEY"
}
```

## Clipboard - Zwischenablage
- `clipboard_get` - Text aus Zwischenablage lesen
- `clipboard_set` - Text in Zwischenablage schreiben
- `clipboard_append` - Text an Zwischenablage anhängen

## DataStore - Persistente Datenspeicherung

SQLite-basierter Datenspeicher. Datenbank: `workspace/.state/datastore.db`

**Documents (strukturierte JSON-Objekte):**
- `db_doc_save(collection, doc_id, data)` - Dokument speichern/aktualisieren
- `db_doc_get(collection, doc_id)` - Dokument abrufen
- `db_doc_list(collection)` - Alle Dokumente einer Collection
- `db_doc_find(collection, field, value)` - Dokumente nach Feld suchen (Substring-Match)
- `db_doc_delete(collection, doc_id)` - Dokument löschen
- `db_doc_collections()` - Alle Document-Collections mit Anzahl

**Collections (String-Listen):**
- `db_add(collection, value)` - Item hinzufügen (mit Auto-Timestamp)
- `db_remove(collection, value)` - Item entfernen
- `db_list(collection)` - Alle Items auflisten (JSON)
- `db_contains(collection, value)` - Prüfen ob Item existiert ("true"/"false")
- `db_search(collection, pattern)` - Items suchen (Substring-Match)
- `db_clear(collection)` - Collection leeren

**Key-Value:**
- `db_set(key, value)` - Wert speichern
- `db_get(key)` - Wert abrufen (oder "null")
- `db_delete(key)` - Key löschen

**Counter:**
- `db_increment(name, amount=1)` - Counter erhöhen
- `db_get_counter(name)` - Counter-Wert abrufen
- `db_reset_counter(name)` - Counter zurücksetzen

**Info & Kosten:**
- `db_collections()` - Alle Collection-Namen mit Anzahl
- `db_stats()` - Datenbank-Statistiken (Größe, Anzahlen)
- `db_api_costs()` - API-Kosten-Statistik (nach Model, Backend, Datum)

**Beispiele:**
```python
# Kontakt speichern
db_doc_save("contacts", "max_mueller", {
  "name": "Max Müller", "email": "max@acme.de", "company": "ACME GmbH"
})
db_doc_find("contacts", "company", "ACME")  # → Alle ACME-Kontakte

# Spam-Liste
db_add("blocked_senders", "spam@example.com")
db_contains("blocked_senders", "spam@example.com")  # → "true"

# Key-Value
db_set("last_daily_check", "2025-01-08")
db_get("last_daily_check")  # → "2025-01-08"

# Zähler
db_increment("emails_processed")
db_get_counter("emails_processed")  # → "47"

# Kosten abfragen
db_api_costs()  # → {"total_usd": 10.01, "by_model": {...}, ...}
```

## Browser - Webseiten öffnen
- `browser_open_url` - URL im Standard-Browser öffnen
- `browser_open_url_new_tab` - URL in neuem Tab öffnen
- `browser_open_url_new_window` - URL in neuem Fenster öffnen

## Browser - Automatisierung (Chrome Remote Debugging)

Tools für Browser-Automatisierung via Chrome DevTools Protocol (CDP):

**Verbindung:**
- `browser_start(browser_type, url)` - **Browser mit Remote-Debugging starten** (vivaldi/chrome/edge)
- `browser_status()` - Verbindungsstatus prüfen
- `browser_connect()` - Mit laufendem Browser verbinden (Port 9222)

**Tab-Management:**
- `browser_get_tabs()` - Alle offenen Tabs auflisten
- `browser_switch_tab(tab_index)` - Zu Tab wechseln

**Navigation & Info:**
- `browser_navigate(url)` - Zu URL navigieren
- `browser_get_page_info()` - Seiteninfo (URL, Titel, Text)

**Formulare:**
- `browser_get_forms()` - Alle Formulare und Felder finden
- `browser_fill_field(selector, value)` - Einzelnes Feld ausfüllen
- `browser_fill_form(fields)` - Mehrere Felder ausfüllen (JSON)
- `browser_select(selector, value)` - Dropdown-Option wählen

**Interaktion:**
- `browser_click(selector)` - Element klicken (CSS-Selector)
- `browser_click_text(text)` - Element klicken (sichtbarer Text)
- `browser_type(selector, text, delay)` - Text tippen (zeichenweise)
- `browser_press_key(key)` - Taste drücken (Enter, Tab, Escape, etc.)
- `browser_wait(selector, timeout)` - Auf Element warten

**Content:**
- `browser_get_text(selector)` - Text eines Elements lesen
- `browser_execute_js(script)` - JavaScript ausführen
- `browser_screenshot(path)` - Screenshot erstellen

**Workflow: UI-Test durchführen**
```python
# 1. Browser mit Remote Debugging starten
browser_start("chrome", "http://localhost:8765/")

# 2. Alternativ: Mit bestehendem Browser verbinden
browser_connect()

# 3. Formular ausfüllen
browser_fill_form('{"#username": "admin", "#password": "secret"}')

# 4. Button klicken
browser_click("button[type='submit']")

# 5. Auf Ergebnis warten
browser_wait(".success-message", timeout=5000)

# 6. Screenshot zur Verifizierung
browser_screenshot(".temp/login_result.png")
```

**Hinweis:** Browser muss mit `--remote-debugging-port=9222` gestartet sein. Siehe `/browser-test` für vollständigen Workflow.

## DeskAgent - System-Kontrolle
- `desk_restart()` - **DeskAgent neu starten** (stoppt aktuelle Instanz, startet neu)
- `desk_get_status()` - Status und Version abrufen
- `desk_list_agents()` - Alle verfügbaren Agents auflisten
- `desk_run_agent(agent_name, inputs)` - **Agent im Hintergrund starten**
- `desk_list_agent_tools()` - **Auto-discovered Agent-Tools auflisten**
- `desk_add_agent_config(name, category, ...)` - **Agent zu agents.json hinzufügen**
- `desk_remove_agent_config(name)` - **Agent aus agents.json entfernen**
- `desk_get_agent_log()` - **Letztes Agent-Log lesen** (agent_latest.txt)
- `desk_get_system_log(lines=100)` - **System-Log lesen** (letzte N Zeilen)

**Agent starten mit Inputs:**
```python
# Agent ohne Inputs
desk_run_agent("daily_check")

# Agent mit Inputs (JSON-String)
desk_run_agent("archive_files", '{"files": ["/path/to/file.pdf"]}')
```

**Agent-as-Tool Architektur:**

Agents mit `tool` Definition im Frontmatter werden automatisch als strukturierte MCP-Tools registriert:

```python
# Statt generisch:
desk_run_agent("invoice_processor", inputs='{"invoices": [...]}')

# Strukturiert (wenn tool definiert):
process_invoices(invoices=[...])  # Auto-discovered Tool
```

Siehe [docs/agent-as-tool-architecture.md](docs/agent-as-tool-architecture.md) für Details.

**Restart-Workflow:**
```python
# 1. Änderungen an Agent-Dateien speichern
fs_write_file("agents/my_agent.md", new_content)

# 2. DeskAgent neu starten
desk_restart()  # Startet automatisch neu
```

## Filesystem - Generische Dateioperationen
- `fs_read_file(path, encoding)` - Textdatei lesen (max. 10MB)
- `fs_read_pdf(path)` - **PDF-Text extrahieren** (verwendet pypdf)
- `fs_read_pdfs_batch(paths)` - **Mehrere PDFs in einem Call lesen** (Performance)
- `fs_write_file(path, content, encoding)` - Datei schreiben/erstellen
- `fs_list_directory(path, pattern)` - Verzeichnisinhalt auflisten
- `fs_file_exists(path)` - Prüfen ob Datei/Ordner existiert
- `fs_get_file_info(path)` - Datei-Metadaten (Größe, Datum, Typ)
- `fs_copy_file(source, destination)` - Datei kopieren
- `fs_delete_file(path)` - Datei löschen (keine Ordner)

**Hinweis:** Keine Pfad-Beschränkungen - der Benutzer wählt Dateien explizit aus. Für Agent Pre-Inputs verwendet.

**PDF lesen:** Verwende `fs_read_pdf()` statt `fs_read_file()` für PDF-Dateien.

**Batch-PDF-Lesen:**
```python
# Mehrere PDFs effizient lesen
fs_read_pdfs_batch([
    ".temp/invoice1.pdf",
    ".temp/invoice2.pdf",
    ".temp/invoice3.pdf"
])
# → {"invoice1.pdf": "Text...", "invoice2.pdf": "Text...", ...}
```

## Excel - Tabellen lesen und schreiben

### Datei-Informationen
- `excel_get_info(file_path)` - **Informationen über Excel-Datei** (Arbeitsblätter, Größen)
- `excel_list_sheets(file_path)` - **Alle Arbeitsblätter auflisten**

### Lesen
- `excel_read_cell(file_path, cell_ref, sheet_name, preserve_formulas)` - **Einzelne Zelle lesen** (z.B. 'A1')
- `excel_read_range(file_path, range_ref, sheet_name, include_header, preserve_formulas)` - **Zellenbereich lesen** (z.B. 'A1:C10')
- `excel_read_sheet(file_path, sheet_name, max_rows, preserve_formulas)` - **Ganzes Arbeitsblatt lesen** (erste Zeile = Header)

**Parameter `preserve_formulas`:**
- `false` (Standard): Liest berechnete Werte (z.B. `300` statt `=SUM(A1:A2)`)
- `true`: Liest Formeln als String (z.B. `=SUM(A1:A2)`)

### Schreiben
- `excel_write_cell(file_path, cell_ref, value, sheet_name)` - **Einzelne Zelle schreiben** (erkennt Formeln mit "=")
- `excel_write_range(file_path, range_ref, data, sheet_name)` - **Zellenbereich schreiben** (erkennt Formeln mit "=")
- `excel_write_sheet(file_path, data, sheet_name, clear_existing)` - **⭐ Ganzes Arbeitsblatt schreiben** (erkennt Formeln mit "=")

**FORMELN:** Strings die mit "=" beginnen werden automatisch als Excel-Formeln geschrieben.
- Beispiel: `{"Total": "=SUM(A1:A10)"}` → Formel in Excel-Zelle
- Beispiel: `excel_write_cell("file.xlsx", "C3", "=A1+B1")` → Formel in C3

### Arbeitsblätter verwalten
- `excel_create_sheet(file_path, sheet_name)` - **Neues Arbeitsblatt erstellen**
- `excel_delete_sheet(file_path, sheet_name)` - **Arbeitsblatt löschen**

**Unterstützte Formate:** .xlsx (OpenXML Format)

**Pfade:** Absolute Pfade oder relativ zum Workspace (z.B. `exports/data.xlsx`)

**Workflow: Excel-Datei lesen und verarbeiten**
```python
# 1. Datei-Informationen
excel_get_info("exports/kunden.xlsx")
# → {"sheet_count": 2, "sheets": [{"name": "Kunden", "rows": 150, "columns": 8}, ...]}

# 2. Arbeitsblatt lesen (mit Header)
excel_read_sheet("exports/kunden.xlsx", "Kunden", max_rows=100)
# → {"sheet": "Kunden", "rows": 99, "data": [{"Name": "Müller GmbH", "E-Mail": "info@mueller.de", ...}, ...]}

# 3. Bestimmten Bereich lesen
excel_read_range("exports/kunden.xlsx", "A1:C10", "Kunden")
# → [{"Name": "Müller GmbH", "Ort": "Berlin", "Status": "Aktiv"}, ...]

# 4. Einzelne Zelle lesen
excel_read_cell("exports/kunden.xlsx", "B5", "Kunden")
# → "info@mueller.de"
```

**Workflow: Excel-Datei schreiben**
```python
# 1. Neue Datei mit Daten erstellen
data = [
    {"Name": "Müller GmbH", "Ort": "Berlin", "Status": "Aktiv"},
    {"Name": "Schmidt AG", "Ort": "München", "Status": "Inaktiv"}
]
excel_write_range("exports/neue_kunden.xlsx", "A1:C3", json.dumps(data), "Kunden")

# 2. Einzelne Zelle aktualisieren
excel_write_cell("exports/kunden.xlsx", "D5", "Bezahlt", "Rechnungen")

# 3. Neues Arbeitsblatt hinzufügen
excel_create_sheet("exports/kunden.xlsx", "Archiv")
```

**Workflow: Full-Roundtrip (Lesen → Verarbeiten → Schreiben)**
```python
# 1. LESEN: Ganzes Arbeitsblatt lesen
result = excel_read_sheet("exports/kunden.xlsx", "Aktiv", max_rows=500)
data = json.loads(result)
# → {"sheet": "Aktiv", "rows": 123, "data": [{"Name": "...", "Email": "...", "Status": "..."}, ...]}

# 2. VERARBEITEN: AI analysiert/modifiziert Daten
customers = data["data"]
# ... AI macht Änderungen an customers ...

# 3. SCHREIBEN: Komplettes Sheet zurückschreiben (OHNE Range!)
excel_write_sheet("exports/kunden_neu.xlsx", json.dumps(customers), "Aktiv")
# → Schreibt automatisch: Header + alle 123 Zeilen
# → "OK: 123 Zeilen × 5 Spalten in 'Aktiv' geschrieben"
```

**Vorteil `excel_write_sheet()` vs `excel_write_range()`:**
- ✅ Keine Range-Berechnung nötig ("A1:Z501" etc.)
- ✅ Automatische Größenerkennung
- ✅ Löscht alte Daten automatisch (`clear_existing=True`)
- ✅ Ideal für Full-Roundtrip-Workflows

**Workflow: Formeln erhalten (Full-Roundtrip mit Formeln)**
```python
# 1. LESEN: Mit preserve_formulas=True
result = excel_read_sheet("rechnung.xlsx", "Calc", max_rows=100, preserve_formulas=True)
data = json.loads(result)["data"]
# → [{"Pos": "1", "Menge": "5", "Preis": "10", "Total": "=B2*C2"}, ...]

# 2. VERARBEITEN: AI ändert nur Daten, nicht Formeln
# Formeln bleiben als "=B2*C2" String erhalten

# 3. SCHREIBEN: Formeln werden automatisch erkannt (String mit "=")
excel_write_sheet("rechnung_neu.xlsx", json.dumps(data), "Calc")
# → Formeln werden als Excel-Formeln geschrieben, nicht als Text!
```

**Workflow: Formeln hinzufügen**
```python
# Rechnung mit Summenzeile erstellen
data = [
    {"Artikel": "Produkt A", "Menge": "10", "Preis": "5.50", "Total": "=B2*C2"},
    {"Artikel": "Produkt B", "Menge": "3", "Preis": "12.00", "Total": "=B3*C3"},
    {"Artikel": "SUMME", "Menge": "", "Preis": "", "Total": "=SUM(D2:D3)"}
]
excel_write_sheet("rechnung.xlsx", json.dumps(data), "Rechnung")
# → Excel berechnet automatisch: Total-Spalte + Summenzeile
```

**Hinweis:**
- Dateien werden automatisch erstellt, falls sie nicht existieren
- Erste Zeile wird bei `read_sheet` und `read_range` als Spaltenüberschrift verwendet (außer `include_header=False`)
- Bei `write_range` und `write_sheet` mit Dictionaries werden automatisch Header hinzugefügt
- **FORMELN:** Berechnete Werte vs. Formeln via `preserve_formulas` Parameter steuern
- **FORMELN schreiben:** Automatische Erkennung via "=" am Anfang (keine Escape nötig)

## Project - Claude Code in anderen Projekten ausführen
- `project_ask(prompt, project_path, timeout)` - **Claude Code CLI im Zielprojekt ausführen**
- `project_ask_with_context(prompt, project_path, context)` - Mit zusätzlichem Kontext (z.B. E-Mail)
- `project_list_knowledge(project_path)` - Knowledge-Dateien des Projekts auflisten
- `project_check(project_path)` - Prüfen ob Projekt für Claude Code eingerichtet ist

**Workflow: Support-Anfrage mit externem Projekt beantworten**
```
1. outlook_get_selected_email()   → Kundenanfrage lesen
2. project_check("E:/docs")       → Projekt prüfen
3. project_ask_with_context(      → Antwort generieren
     prompt="Beantworte diese Anfrage",
     project_path="E:/docs",
     context="<E-Mail-Inhalt>"
   )
4. outlook_create_reply_draft(body)       → Entwurf erstellen
```

**Hinweis:** Das Zielprojekt sollte eine eigene CLAUDE.md mit Produkt-/Support-Expertise haben.

**Produkt-Codes:**
- `RVP1` - Professional Edition (€1.098)
- `RVR1` - Research & Education Bundle (€2.100)
- `DL4` - Online Training and Support (€150/h)

## PDF - Dokumente bearbeiten
- `pdf_get_info(path)` - **PDF-Metadaten** (Seiten, Größe, Autor, etc.)
- `pdf_extract_pages(source, pages, output)` - **Seiten extrahieren** zu neuem PDF
- `pdf_merge(files, output)` - **PDFs zusammenfügen**
- `pdf_split(source, output_dir)` - **PDF in Einzelseiten aufteilen**

**Seiten-Syntax für `pdf_extract_pages`:**
| Syntax | Beschreibung |
|--------|--------------|
| `"1"` | Einzelne Seite |
| `"1-5"` | Seitenbereich |
| `"1,3,5"` | Mehrere einzelne Seiten |
| `"1-3,7,10-12"` | Gemischt |
| `"-1"` | Letzte Seite |
| `"-3"` | Drittletzte Seite |

**Beispiele:**
```python
# PDF-Info anzeigen
pdf_get_info("C:/Dokumente/Vertrag.pdf")

# Erste 3 Seiten extrahieren
pdf_extract_pages("C:/input.pdf", "1-3", "C:/output.pdf")

# Seiten 1, 5 und 10-15 extrahieren
pdf_extract_pages("C:/input.pdf", "1,5,10-15")

# Letzte Seite extrahieren
pdf_extract_pages("C:/input.pdf", "-1", "C:/letzte_seite.pdf")

# Mehrere PDFs zusammenfügen
pdf_merge(["doc1.pdf", "doc2.pdf", "doc3.pdf"], "combined.pdf")

# PDF in Einzelseiten aufteilen
pdf_split("C:/buch.pdf", "C:/seiten/")
```

## SEPA - Überweisungen (pain.001)
- `sepa_validate_iban(iban)` - **IBAN validieren** (Prüfsumme + Länge)
- `sepa_create_transfer(..., account, filename)` - **Einzelüberweisung** erstellen
- `sepa_create_batch(payments, account, filename)` - **Sammelüberweisung** mit mehreren Zahlungen
- `sepa_get_accounts()` - **Alle Konten anzeigen** (IBANs maskiert)
- `sepa_lookup_recipient_iban(name)` - **Empfänger-IBAN nachschlagen** (volle IBAN für Überweisungen)
- `sepa_get_details(filename)` - **Vollständige Übersicht** (Von, Von-IBAN, Nach, Nach-IBAN, Referenz, Betrag)
- `sepa_list_files()` - **Alle erstellten SEPA-Dateien auflisten**
- `sepa_append(filename, payments)` - **Zahlungen zu bestehender Datei hinzufügen**
- `sepa_clear_files()` - **Alle SEPA-Dateien löschen** (vor neuer Session)

**Dateinamen-Konvention:**
- Format: `sepa-{konto}-{YYYYMMDD}.xml`
- Beispiel: `sepa-business-20251231.xml` oder `sepa-private-20251231.xml`

**Konfiguration in config/banking.json:**
```json
{
  "business": {
    "name": "My Company GmbH",
    "iban": "DE...",
    "bic": "...",
    "currency": "EUR"
  },
  "private": {
    "name": "Max Mustermann",
    "iban": "DE...",
    "bic": "...",
    "currency": "EUR"
  },
  "default": "business"
}
```

**Workflow: Empfänger-IBAN nachschlagen**
```python
# Name aus Dokument → IBAN nachschlagen
sepa_lookup_recipient_iban("Erika Musterfrau")
# → {"found": true, "name": "Erika Musterfrau", "iban": "DE89370400440532013001", ...}

# Auch Teilmatch (Vorname/Nachname) funktioniert:
sepa_lookup_recipient_iban("Erika")
# → Findet "Erika Musterfrau"
```

**Workflow: Lieferantenrechnung bezahlen**
```python
# 1. Verfügbare Konten anzeigen
sepa_get_accounts()

# 2. Überweisung mit Default-Konto (business)
sepa_create_transfer(
    creditor_name="Lieferant GmbH",
    creditor_iban="DE89370400440532013000",
    amount=1500.00,
    reference="Rechnung RE-2025-001"
)

# 3. Überweisung mit privatem Konto
sepa_create_transfer(..., account="private")

# 4. Sammelüberweisung für Firma
sepa_create_batch('[...]', account="business")
```

**Format:** pain.001.001.03 (SEPA Credit Transfer, ISO 20022)

## SEPA - Kontoauszüge lesen (CAMT.052)
- `sepa_read_camt052_zip(zip_path)` - **Kontoauszüge aus ZIP lesen** (Intraday-Reports)
- `sepa_read_camt052_xml(xml_path)` - Einzelne CAMT.052 XML-Datei lesen
- `sepa_get_camt_credits(zip_path, min_amount)` - **Nur Zahlungseingänge extrahieren** (für Rechnungsabgleich)

**CAMT.052 Format:** ISO 20022 Bank to Customer Account Report (Intraday)

**Workflow: Zahlungseingänge prüfen**
```python
# 1. CAMT.052 ZIP von der Bank herunterladen

# 2. Alle Zahlungseingänge extrahieren
sepa_get_camt_credits("C:/Downloads/kontoauszug.zip")
# → {"credits": [{"date": "2025-01-03", "amount": 1098.00, "debtor_name": "Kunde GmbH", ...}], ...}

# 3. Gegen offene Rechnungen abgleichen (Billomat)
billomat_get_open_invoices()
```

**Extrahierte Daten pro Transaktion:**
- `booking_date` / `value_date` - Buchungs-/Valutadatum
- `amount`, `currency` - Betrag und Währung
- `type` - "credit" (Eingang) oder "debit" (Ausgang)
- `debtor_name`, `debtor_iban` - Zahlender bei Credits
- `creditor_name`, `creditor_iban` - Empfänger bei Debits
- `reference` - Verwendungszweck
- `end_to_end_id` - End-to-End-Referenz

## ecoDMS - Dokumentenarchiv

Tools zum Archivieren, Suchen und Verwalten von Dokumenten in ecoDMS:

**Archiv-Informationen:**
- `ecodms_test_connection()` - **Verbindung testen**
- `ecodms_get_folders()` - Ordner/Ablagen auflisten
- `ecodms_get_document_types()` - Dokumenttypen auflisten
- `ecodms_get_statuses()` - Status-Werte auflisten
- `ecodms_get_roles()` - Rollen/Berechtigungen auflisten
- `ecodms_get_classify_attributes()` - Klassifizierungs-Attribute auflisten

**Dokument-Operationen:**
- `ecodms_search_documents(query, folder_id, doc_type, status, date_from, date_to)` - **Dokumente suchen**
- `ecodms_get_document_info(doc_id)` - Dokumentmetadaten abrufen
- `ecodms_download_document(doc_id, save_path)` - **Dokument herunterladen** (1 API-Connect)
- `ecodms_upload_document(file_path, version_controlled)` - **Dokument hochladen** (1 API-Connect)
- `ecodms_classify_document(doc_id, folder_id, doc_type, status, bemerkung)` - Dokument klassifizieren
- `ecodms_archive_file(file_path, folder_id, doc_type, status, bemerkung)` - **Upload + Klassifizierung in einem Schritt**
- `ecodms_get_thumbnail(doc_id, page, height)` - Vorschaubild-URL (keine API-Connects)

**Workflow: Dokument archivieren**
```python
# 1. Verbindung testen
ecodms_test_connection()

# 2. Verfügbare Ordner und Typen anzeigen
ecodms_get_folders()
ecodms_get_document_types()

# 3. Datei archivieren und klassifizieren
ecodms_archive_file(
    file_path=".temp/rechnung.pdf",
    folder_id="5",           # Ziel-Ordner
    doc_type="Rechnung",     # Dokumenttyp
    status="Neu",            # Status
    bemerkung="Rechnung 2024-001"
)
```

**Konfiguration in apis.json:**
```json
"ecodms": {
  "url": "http://localhost:8180",
  "username": "ecodms",
  "password": "ecodms",
  "archive_id": "1"
}
```

**API-Limits:** Jeder Upload/Download verbraucht 1 API-Connect. Standard-Lizenz: 10/Monat. ecoDMS ONE: Unbegrenzt.

## Paperless-ngx - Dokumentenmanagement

Open-Source Dokumenten-Management-System mit OCR und Volltextsuche.

**Verbindung & Authentifizierung:**
- `paperless_test_connection()` - **Verbindung testen**
- `paperless_get_token(username, password)` - **API-Token abrufen** (für apis.json)

**Dokument-Operationen:**
- `paperless_search_documents(query, correspondent_id, correspondent_isnull, document_type_id, tag_ids, ...)` - **Dokumente suchen**
  - `correspondent_isnull=True` - Nur Dokumente OHNE Korrespondent (unklassifiziert)
  - `correspondent_isnull=False` - Nur Dokumente MIT Korrespondent (klassifiziert)
- `paperless_get_document(doc_id)` - Dokumentmetadaten abrufen
- `paperless_get_document_content(doc_id)` - **OCR-Text eines Dokuments lesen**
- `paperless_download_document(doc_id, save_path, original)` - **Dokument herunterladen**
- `paperless_export_document_pdf(doc_id, save_path)` - **PDF exportieren** mit Namensformat `YYYY-MM-DD-[Korrespondent]-[doc_id].pdf`
- `paperless_upload_document(file_path, title, correspondent_id, storage_path_id, tag_ids, ...)` - **Dokument hochladen**
- `paperless_update_document(doc_id, title, correspondent_id, storage_path_id, ...)` - Dokument aktualisieren
- `paperless_delete_document(doc_id)` - Dokument löschen
- `paperless_find_similar_documents(doc_id, limit)` - **Ähnliche Dokumente finden**

**Bulk-Operationen:**
- `paperless_bulk_edit_documents(document_ids, operation, value)` - **Mehrere Dokumente bearbeiten** (gleiche Operation)
  - Operationen: `set_correspondent`, `set_document_type`, `add_tag`, `remove_tag`, `delete`, `reprocess`
- `paperless_batch_classify_documents(classifications)` - **Dokumente klassifizieren** (Korrespondenten/Tags/Storage Path/Datum)
  - JSON-Array: `[{"doc_id": 1, "correspondent_name": "Firma", "tag_ids": "7,3", "storage_path_name": "Privat", "created": "2025-01-15"}, ...]`
  - Erstellt fehlende Korrespondenten und Storage Paths automatisch
  - `storage_path_name`: Optional, setzt Speicherpfad (z.B. "business", "Privat")
  - `created`: Optional, setzt Dokumentdatum (Format: YYYY-MM-DD)
  - Ideal für Auto-Tagging Workflows

**Metadaten-Verwaltung:**
- `paperless_get_tags()` / `paperless_create_tag(name, color)` / `paperless_update_tag()` / `paperless_delete_tag()` - Tags
- `paperless_get_correspondents()` / `paperless_create_correspondent(name)` / `paperless_delete_correspondent()` - Korrespondenten
- `paperless_get_document_types()` / `paperless_create_document_type(name)` / `paperless_delete_document_type()` - Dokumenttypen
- `paperless_get_storage_paths()` / `paperless_create_storage_path(name, path)` - Speicherpfade
- `paperless_get_custom_fields()` - Benutzerdefinierte Felder auflisten
- `paperless_set_document_custom_field(doc_id, field_name, value)` - **Custom Field setzen** (Text, Boolean, Integer, Float)
- `paperless_get_document_custom_field(doc_id, field_name)` - Custom Field Wert lesen
- `paperless_get_saved_views()` - Gespeicherte Ansichten

**Task-Monitoring:**
- `paperless_get_task_status(task_id)` - **Consumption-Status prüfen** (nach Upload)
- `paperless_acknowledge_tasks(task_ids)` - Erledigte Tasks bestätigen

**Suche:**
- `paperless_search_autocomplete(term, limit)` - Suchvorschläge

**Workflow: Dokument hochladen und kategorisieren**
```python
# 1. Tags und Korrespondenten abrufen
paperless_get_tags()
paperless_get_correspondents()

# 2. Dokument hochladen
paperless_upload_document(
    file_path="rechnung.pdf",
    title="Rechnung Januar 2025",
    correspondent_id=5,
    tag_ids="1,3"
)
# → task_id: "abc123..."

# 3. Status prüfen
paperless_get_task_status("abc123...")
```

**Workflow: Dokumente suchen und lesen**
```python
# Volltextsuche
paperless_search_documents(query="Rechnung 2025", document_type_id=3)

# Nur unklassifizierte Dokumente (ohne Korrespondent) im Zeitraum
paperless_search_documents(correspondent_isnull=True, created_after="2025-01-01", created_before="2025-12-31")

# Inhalt eines Dokuments lesen (OCR-Text)
paperless_get_document_content(doc_id=42)
```

**Workflow: Dokumente als PDF exportieren**
```python
# Export mit standardisiertem Namen: YYYY-MM-DD-[Korrespondent]-[doc_id].pdf
paperless_export_document_pdf(doc_id=42)
# → 2025-01-03-EnBW_Energie-42.pdf

paperless_export_document_pdf(doc_id=43)
# → 2025-01-03-EnBW_Energie-43.pdf

# Export in bestimmten Ordner
paperless_export_document_pdf(doc_id=42, save_path="invoices/2025")
```

**Konfiguration in apis.json:**
```json
"paperless": {
  "enabled": true,
  "url": "http://localhost:8000",
  "token": "abc123...",
  "api_version": 5
}
```

**Token erhalten:**
1. `paperless_get_token("username", "password")` aufrufen
2. Token in `apis.json` unter `paperless.token` eintragen
3. Alternativ: `username` und `password` direkt in `apis.json` (weniger sicher)

**Matching-Algorithmen** (für Auto-Assignment):
| Wert | Algorithmus |
|------|-------------|
| 0 | None (kein Auto-Match) |
| 1 | Any (ein Wort) |
| 2 | All (alle Wörter) |
| 3 | Literal (exakt) |
| 4 | Regex |
| 5 | Fuzzy |

## Telegram - Messaging

Telegram Bot API Integration für Nachrichten, Dateien und interaktive Buttons.

**Setup:**
1. Bot erstellen bei `@BotFather` in Telegram
2. Bot Token in `apis.json` unter `telegram.bot_token` eintragen
3. Chat-ID herausfinden: Nachricht an Bot senden, dann `telegram_get_updates()` aufrufen

**Verbindung:**
- `telegram_test_connection()` - **Verbindung testen** (zeigt Bot-Name und Username)

**Nachrichten senden:**
- `telegram_send_message(chat_id, text, parse_mode, disable_notification, reply_to_message_id)` - **Text-Nachricht senden**
  - `parse_mode`: "Markdown" (Standard), "MarkdownV2" oder "HTML"
  - Markdown: `*fett* _kursiv_ `code` [Link](url)`
  - HTML: `<b>fett</b> <i>kursiv</i> <code>code</code> <a href="url">Link</a>`
- `telegram_send_document(chat_id, file_path, caption, parse_mode, disable_notification)` - **Dokument senden** (PDF, DOCX, ZIP, max. 50 MB)
- `telegram_send_photo(chat_id, file_path, caption, parse_mode, disable_notification)` - **Foto senden** (JPG, PNG, max. 10 MB)
- `telegram_send_message_with_keyboard(chat_id, text, buttons, parse_mode)` - **Nachricht mit Inline-Buttons**
  - Buttons als JSON-Array: `[{"text": "✅ Ja", "callback_data": "yes"}, {"text": "❌ Nein", "callback_data": "no"}]`

**Nachrichten verwalten:**
- `telegram_edit_message(chat_id, message_id, text, parse_mode)` - **Nachricht bearbeiten**
- `telegram_delete_message(chat_id, message_id)` - **Nachricht löschen**

**Updates & Chat-Info:**
- `telegram_get_updates(offset, limit)` - **Neue Nachrichten abrufen** (Polling)
  - Returns: JSON mit `update_id`, `message_id`, `from`, `chat`, `text`
- `telegram_get_chat_info(chat_id)` - **Chat-Informationen** (Titel, Typ, Mitgliederzahl)

**Interaktive Buttons:**
- `telegram_answer_callback_query(callback_query_id, text, show_alert)` - **Button-Klick beantworten**

**Workflow: Rechnung per Telegram senden**
```python
# 1. Rechnung exportieren
billomat_download_invoice_pdf("123", ".temp", "rechnung.pdf")

# 2. Per Telegram senden
telegram_send_document(
    "123456789",  # Chat-ID
    ".temp/rechnung.pdf",
    caption="📄 Ihre Rechnung RE-2025-001"
)
```

**Workflow: Interaktive Bestätigung**
```python
# 1. Frage mit Buttons
telegram_send_message_with_keyboard(
    "123456789",
    "Angebot erstellen?\n\n*Kunde:* Firma XY\n*Produkt:* RVP1\n*Preis:* 1.098 €",
    '[{"text": "✅ Ja", "callback_data": "create"}, {"text": "❌ Nein", "callback_data": "cancel"}]'
)

# 2. Updates abrufen (callback_data aus Update extrahieren)
telegram_get_updates()

# 3. Auf Callback reagieren
if callback_data == "create":
    billomat_create_offer(...)
    telegram_send_message("123456789", "✅ Angebot erstellt!")
```

**Workflow: Daily Check Benachrichtigung**
```python
# Agent sendet tägliche Zusammenfassung
summary = f"""📧 *Daily Check*

📥 Neue E-Mails: {new_count}
🚩 Follow-up: {followup_count}
🗑️ Newsletter: {spam_count}

✅ Alle verarbeitet!
"""

telegram_send_message("123456789", summary)
```

**Chat-Typen:**
| Typ | Chat-ID Format | Beispiel |
|-----|----------------|----------|
| Private Chat | Positive Zahl | `123456789` |
| Gruppe | Negative Zahl | `-987654321` |
| Supergruppe | Negativ mit -100 | `-1001234567890` |
| Kanal | Username oder -100 | `@my_channel` oder `-1001234567890` |

**Konfiguration in apis.json:**
```json
"telegram": {
  "enabled": true,
  "bot_token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
}
```

**Bot Token erhalten:**
1. Telegram öffnen → `@BotFather` suchen
2. `/newbot` senden → Name und Username wählen
3. Bot Token kopieren → in `apis.json` eintragen

**Chat-ID herausfinden:**
1. Nachricht an Bot senden (z.B. `/start`)
2. `telegram_get_updates()` aufrufen
3. `chat.id` aus Response ist deine Chat-ID

**Limits:**
- Text: 4.096 Zeichen
- Caption: 1.024 Zeichen
- Foto: 10 MB
- Dokument: 50 MB
- Requests: 30/Sekunde

**Vollständige Dokumentation:** [docs/telegram-mcp-setup.md](../docs/telegram-mcp-setup.md)

---

## Plugin-MCPs

Plugin-MCPs werden automatisch erkannt und geladen. Es werden zwei Verzeichnisstrukturen unterstuetzt:

### Verzeichnisstruktur

**Flat Structure (empfohlen):** Ein MCP pro Plugin, direkt in `mcp/`.
```
plugins/sap/
├── plugin.json
└── mcp/
    └── __init__.py    # -> server_name = "sap:sap"
```

**Nested Structure:** Mehrere MCPs pro Plugin in Unterordnern.
```
plugins/myplugin/
├── plugin.json
└── mcp/
    ├── api_server/
    │   └── __init__.py   # -> server_name = "myplugin:api_server"
    └── data_server/
        └── __init__.py   # -> server_name = "myplugin:data_server"
```

### Naming Convention
- Flat: `{plugin_name}:{plugin_name}` (z.B. `sap:sap`, `myplugin:myplugin`)
- Nested: `{plugin_name}:{mcp_folder_name}` (z.B. `myplugin:api_server`)
- Tool-Namen: Wie im Plugin definiert (ohne Prefix)

### Discovery Flow
```
discover_plugins() -> mcp_count (flat + nested)
    -> has_mcp = True
        -> get_plugin_mcp_dirs()
            -> discover_mcp_servers() Method 3
                -> Flat:   mcp/__init__.py -> "plugin:plugin"
                -> Nested: mcp/name/__init__.py -> "plugin:name"
```

**In allowed_mcp verwenden:**
```yaml
---
{
  "allowed_mcp": "sap|outlook|billomat"  # Plugin-Name direkt
}
---
```

**Verfuegbare Plugin-MCPs:**
- `sap` - SAP S/4HANA Cloud API (Business Partner, Sales Orders, etc.)

**Mehr Details:** Siehe [doc-pluginsystem.md](doc-pluginsystem.md)
