# MCP Tools Reference

You have access to the following tools:

## Outlook - Emails
- `outlook_get_selected_email` - Read selected email (first if multiple selected)
- `outlook_get_selected_emails()` - **ALL selected emails** as JSON (for multi-selection)
- `outlook_delete_selected_email` - Delete selected email (→ Deleted Items)
- `outlook_delete_email(query, index)` - Delete email by search (index=0 for newest)
- `outlook_delete_emails_from_sender(sender, mailbox, dry_run)` - **Bulk delete from sender** (AdvancedSearch, fast!)
- `outlook_move_emails_from_sender(sender, target_folder, mailbox, dry_run)` - **Bulk move from sender** (AdvancedSearch, fast!)
- `outlook_get_recent_emails(days, date_from, date_to, sender, ...)` - Emails with date filter from all mailboxes
- `outlook_get_unread_emails` - Unread emails
- `outlook_search_emails` - Search emails (slow, no index, only Inbox)
- `outlook_fast_search_emails(query, all_mailboxes)` - **Fast email search** (uses index, all folders incl. subfolders)
- `outlook_fast_get_email_content(query, all_mailboxes)` - Email content from fast search (all folders)
- `outlook_get_email_content` - Email content from search results
- `outlook_create_reply_draft(body, reply_all=True)` - Create reply draft (default: reply all)
- `outlook_create_reply_draft_with_attachment(body, path, reply_all=True)` - **Reply with attachment** (e.g. quote PDF)
- `outlook_update_draft(body, replace=False)` - **Update last created draft**
- `outlook_create_new_email` - Create new email
- `outlook_create_new_email_with_attachment(to, subject, body, path)` - New email with attachment
- `outlook_flag_selected_email` - Flag selected email (followup/complete/clear)
- `outlook_flag_email` - Flag email by search
- `outlook_move_selected_email` - Move selected email to folder
- `outlook_move_email` - Move email by search to folder
- `outlook_list_mail_folders` - List available folders

**Recommendation:** Use `outlook_fast_search_emails` instead of `outlook_search_emails` for faster search.

**Full search across all mailboxes:**
```python
# Search in ALL mailboxes and ALL folders (incl. subfolders)
outlook_fast_search_emails("Rechnungsnummer 12345", all_mailboxes=True)

# Search only in default mailbox, but all folders
outlook_fast_search_emails("Microsoft Invoice")  # Searches all folders incl. subfolders
```

## Outlook - Read Attachments

- `outlook_get_email_attachments(query, index, selection_index)` - **List all attachments** of an email
- `outlook_save_email_attachment(attachment_index, query, email_index, save_path, selection_index)` - **Save attachment**
- `outlook_read_pdf_attachment(attachment_index, query, email_index, selection_index)` - **Extract PDF text**

**Parameter `selection_index`:** For multi-selection which email (1-based). Default: 1

**Workflow: Read PDF invoice from email**
```python
# 1. Selected email - list attachments
outlook_get_email_attachments()   # → [0] Bestellung.pdf (125 KB)

# 2. Extract PDF text
outlook_read_pdf_attachment(0)    # → Text content of the PDF
```

## Outlook - Archiving (Entry-ID based)

Tools for archiving emails via entry ID (from `outlook_get_folder_emails`, `outlook_get_recent_emails`, etc.):

- `outlook_get_email_attachments_by_id(entry_id)` - **List attachments of an email**
- `outlook_read_pdf_attachment_by_id(entry_id, attachment_index)` - **Extract PDF text** (without saving)
- `outlook_save_attachment_by_entry_id(entry_id, attachment_index, save_path)` - **Save attachment**
- `outlook_save_email_as_pdf(entry_id, save_path, filename)` - **Save email as PDF** (Word export)

**Workflow: Check PDF invoice (without saving)**
```python
# 1. Fetch emails
emails = outlook_get_recent_emails(days=7)

# 2. For invoice: read PDF content
pdf_text = outlook_read_pdf_attachment_by_id(entry_id)
# → Check for "Visa", "PayPal", "Lastschrift" = already paid
```

**Workflow: Archive emails from folder**
```python
# 1. Load emails from folder
emails = outlook_get_folder_emails("DoneInvoices", limit=100)

# 2. For each email: check attachments
attachments = outlook_get_email_attachments_by_id(entry_id)

# 3a. PDF attachment present → save attachment
outlook_save_attachment_by_entry_id(entry_id, 0, "Z:")

# 3b. No PDF → save email as PDF
outlook_save_email_as_pdf(entry_id, "Z:")
```

## Outlook - Generic Email Functions (JSON with entry_id)

All functions return JSON with `entry_id` for `outlook_batch_email_actions()`:

- `outlook_get_flagged_emails(limit, include_completed, dedupe_threads)` - **Flagged + completed emails from ALL folders**
  - Scans Inbox + all subfolders
  - `dedupe_threads=True` (default) - shows only newest email per thread
  - Returns: `{"flagged": [...], "completed": [...]}`
  - Completed (flag_status=1) → should be moved to Done
- `outlook_get_recent_emails(days, date_from, date_to, sender, exclude_folders, exclude_flagged)` - **Emails with date filter**
  - `days`: Range in days (default: 7). Ignored when `date_from` is set.
  - `date_from`: Start date (YYYY-MM-DD or DD.MM.YYYY). Overrides `days`.
  - `date_to`: End date (YYYY-MM-DD or DD.MM.YYYY). Default: today.
  - `sender`: Only emails from this sender (name or email, case-insensitive)
  - `exclude_flagged=True`: Exclude flagged emails (open todos)
  - Scans Inbox of all mailboxes
  - Returns: JSON array of emails, sorted by date

**Examples for date filter:**
```python
# Last 14 days
outlook_get_recent_emails(days=14)

# Specific range (ISO or German format)
outlook_get_recent_emails(date_from="2025-12-01", date_to="2025-12-31")
outlook_get_recent_emails(date_from="01.12.2025", date_to="31.12.2025")

# Emails from specific sender in the last 14 days
outlook_get_recent_emails(days=14, sender="Erika Musterfrau")

# Combination: sender + range
outlook_get_recent_emails(date_from="22.12.2025", sender="erika")
```
- `outlook_get_folder_emails(folder, limit)` - **ALL emails from a folder**
  - For work queues like ToOffer, ToPay
  - Returns: JSON array of emails

## Outlook - Batch Actions

- `outlook_batch_email_actions(actions)` - **Multiple move/flag/delete in 1 call**

**Batch actions format:**
```json
[
  {"action": "move", "entry_id": "AAA...", "folder": "ToDelete"},
  {"action": "move", "entry_id": "BBB...", "folder": "Invoices", "mailbox": "user@example.com"},
  {"action": "flag", "entry_id": "CCC...", "flag_type": "followup"},
  {"action": "delete", "entry_id": "DDD..."}
]
```

**Same-mailbox default:** Emails stay in their own mailbox by default. Folders are only looked up/created there.

**Cross-mailbox move:** With `"mailbox": "name@domain.com"` you can explicitly move into a folder of another mailbox.

**Daily Check workflow:**
```python
# 1. Fetch data in parallel
outlook_get_flagged_emails()                              # Open todos + completed
outlook_get_recent_emails(days=7, exclude_folders=["ToDelete"])   # Last 7 days
outlook_get_folder_emails("ToOffer")                      # Quote requests
outlook_get_folder_emails("ToPay")                        # Invoices

# 2. Collect and execute actions
outlook_batch_email_actions([...])
```

## Outlook - Calendar
- `outlook_get_today_events` - Show today's appointments
- `outlook_get_upcoming_events(days=7)` - Appointments for the next X days (default 7; pass 21 for 3 weeks)
- `outlook_get_calendar_event_details` - Search appointment details by subject
- `outlook_check_availability(date_str, start_time, end_time)` - Check if time slot is free
- `outlook_create_appointment(subject, date, start, end, location, body)` - **Create appointment**
- `outlook_create_meeting(subject, date, start, end, attendees, teams_meeting)` - **Meeting with attendees**
- `outlook_create_teams_meeting(subject, date, start, end, attendees)` - **Create Teams meeting**

**Calendar examples:**
```python
# Simple appointment
outlook_create_appointment("Arzttermin", "15.01.2025", "10:00", "11:00", location="Praxis Dr. Müller")

# Meeting with attendees
outlook_create_meeting("Projektbesprechung", "16.01.2025", "14:00", "15:00",
               attendees="max@example.com, anna@example.com")

# Teams meeting
outlook_create_teams_meeting("Sprint Review", "17.01.2025", "09:00", "10:00",
                     attendees="team@company.com", body="Agenda:\n- Demo\n- Feedback")
```

## Microsoft Graph - Server Search (all emails)

The local Outlook search (`outlook_fast_search_emails`) only finds locally cached emails.
For a complete search of all emails on the Exchange server, use Microsoft Graph:

- `graph_authenticate()` - **Start authentication** (device code flow)
- `graph_complete_auth()` - Complete authentication
- `graph_status()` - Check current auth status
- `graph_search_emails(query, limit, has_attachments, date_from, date_to)` - **Server-side email search**
- `graph_get_recent_emails(days, limit, inbox_only=True)` - Fetch newest emails (default: only Inbox)
- `graph_get_flagged_emails(limit, include_completed, mailbox)` - **Flagged emails from Office 365** (for "selection" via flag)
- `graph_get_folder_emails(folder_name, limit, mailbox)` - **Emails from folder** (ToOffer, ToPay, DoneInvoices)
- `graph_get_email(message_id)` - Read full email content
- `graph_get_attachments(message_id)` - **List attachments of an email**
- `graph_download_attachment(message_id, attachment_id, save_path)` - **Download attachment**
- `graph_list_mailboxes()` - List available mailboxes

**IMPORTANT - Search syntax:**
```python
# CORRECT: simple keywords
graph_search_emails("EnBW Rechnung")
graph_search_emails("Adobe invoice")

# CORRECT: with filter parameters
graph_search_emails("EnBW", has_attachments=True, date_from="2025-11-01", date_to="2025-11-30")

# WRONG: complex operators do NOT work!
graph_search_emails("subject:EnBW AND from:adobe has:attachment")  # → Automatically sanitized
```

**When to use Graph instead of Outlook:**
| Scenario | Tool |
|----------|------|
| Recent emails (last 30 days) | `outlook_fast_search_emails` (faster) |
| Older emails / full search | `graph_search_emails` (finds everything) |
| Offline use | Outlook tools (COM API) |

**Workflow: Download attachment**
```python
# 1. Search email
graph_search_emails("EnBW Rechnung", has_attachments=True)
# → ID: AAMkAGFl...

# 2. List attachments (returns FULL attachment_id!)
graph_get_attachments("AAMkAGFl...")
# → [0] Rechnung.pdf (125 KB)
#       attachment_id: AAMkAGFl...FULL_ID...

# 3. Download attachment (use FULL attachment_id!)
graph_download_attachment("AAMkAGFl...", "AAMkAGFl...FULL_ID...", ".temp/invoices")
# → SUCCESS: Downloaded and verified: .temp/invoices/Rechnung.pdf (125000 bytes)
# → ERROR: HTTP 404... (when IDs wrong/incomplete)
```

**IMPORTANT:** Only "SUCCESS:" means actual success. On "ERROR:" NOTHING was saved!

**Workflow: "Select" email via flag (Office 365)**
```python
# Alternative to outlook_get_selected_email() for Office 365 without local Outlook:
# 1. Flag email in Outlook Web/Mobile/Desktop
# 2. Fetch flagged emails (flag syncs to server!)
graph_get_flagged_emails()
# → {"flagged": [{"id": "AAMk...", "subject": "...", ...}], "completed": [], "total": 1}

# 3. Read email content
graph_get_email("AAMk...")

# 4. Process (create reply, archive, etc.)

# 5. Remove flag when done
graph_flag_email("AAMk...", "notFlagged")
```

## Microsoft Graph - Calendar

Read and create calendar events via Graph API:

- `graph_get_upcoming_events(days, mailbox)` - **Appointments for the next X days** (default: 2)
- `graph_get_today_events(mailbox)` - Today's appointments
- `graph_create_calendar_event(subject, start_datetime, end_datetime, attendees, body, is_online_meeting)` - **Create appointment/meeting**

**Create appointment:**
```python
# Teams meeting with attendees
graph_create_calendar_event(
    subject="Projekt-Besprechung",
    start_datetime="2025-01-15T14:00:00",
    end_datetime="2025-01-15T15:00:00",
    attendees="max@example.com, anna@example.com",
    body="Agenda:\n- Status-Update\n- Nächste Schritte",
    is_online_meeting=True  # Teams link is generated automatically
)
# → Teams meeting created, invitations are sent

# Simple appointment without attendees
graph_create_calendar_event(
    subject="Arzttermin",
    start_datetime="2025-01-16T10:00:00",
    end_datetime="2025-01-16T11:00:00",
    is_online_meeting=False,
    location="Praxis Dr. Müller"
)
```

**Parameters for `graph_create_calendar_event`:**
| Parameter | Description |
|-----------|-------------|
| `subject` | Subject/title |
| `start_datetime` | Start in ISO format (YYYY-MM-DDTHH:MM:SS), local time |
| `end_datetime` | End in ISO format |
| `attendees` | Comma-separated email addresses (optional) |
| `body` | Description/agenda (optional) |
| `location` | Location (optional, ignored for online meeting) |
| `is_online_meeting` | `true` for Teams link (default: true) |
| `mailbox` | Calendar of another user (optional) |

**Note:** Times are in German local time (Europe/Berlin). Teams link is generated automatically when `is_online_meeting=true`.

## Microsoft Graph - Teams

Read and write Teams chats and channels:

**Chats (1:1 and groups):**
- `teams_get_chats(limit, filter_participant)` - List chats
- `teams_get_messages(chat_id, limit)` - Read chat messages
- `teams_send_message(chat_id, message)` - Send message (as user)

**Teams & channels:**
- `teams_list_teams()` - List all teams
- `teams_list_channels(team_id)` - Channels of a team
- `teams_get_channel_messages(team_id, channel_id, limit)` - Read channel messages
- `teams_post_to_channel(team_id, channel_id, message, subject)` - Post message (as user)

**Webhook-based (as "DeskAgent"):**
- `teams_post_webhook(webhook_url, message, title)` - Directly via webhook URL
- `teams_post_to_configured_channel(channel_name, message, title)` - **Via configured channels**

**Workflow: Send message as DeskAgent (recommended)**
```python
# Simple with configured channel name
teams_post_to_configured_channel("deskagent", "Build erfolgreich!", title="CI/CD")
```

**Create webhook (New Teams - Power Automate):**
1. Teams Channel → `...` → **Workflows**
2. Search: "Post to a channel when a webhook request is received"
3. Name: "DeskAgent", select channel
4. Copy HTTP POST URL → enter into `apis.json` under `msgraph.webhooks`

**Create webhook (Classic Teams):**
1. Teams Channel → `...` → Connectors → Incoming Webhook
2. Name: "DeskAgent", upload icon
3. Copy URL → enter into `apis.json` under `msgraph.webhooks`

**Workflow: Send message as user**
```python
# 1. List teams
teams_list_teams()

# 2. List channels
teams_list_channels("abc123...")

# 3. Post message (appears as the signed-in user)
teams_post_to_channel("abc123...", "def456...", "Hallo Team!", subject="Update")
```

**Configuration in apis.json:**
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

**Create Azure AD app:**
1. Azure Portal → Azure Active Directory → App registrations
2. New registration → Name: "DeskAgent"
3. Supported account types: "Accounts in any organizational directory"
4. Redirect URI: Mobile and desktop applications → `https://login.microsoftonline.com/common/oauth2/nativeclient`
5. API permissions → Add:
   - Mail: `Mail.Read`, `Mail.ReadWrite`
   - User: `User.Read`
   - Teams: `Chat.Read`, `Chat.ReadWrite`, `ChatMessage.Send`, `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `ChannelMessage.Read.All`, `ChannelMessage.Send`
6. Copy client ID → enter in apis.json

## Microsoft Graph - Teams Watcher (Auto-Response)

Automatic agent responses to Teams channel messages via Graph API polling.

**Setup:**
```python
# 1. Set up watcher (finds channel, stores IDs, activates)
teams_setup_watcher('deskagent')

# 2. Restart DeskAgent - polling begins
```

**Configuration in `deskagent/config/triggers.json`:**
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

| Option | Description |
|--------|-------------|
| `enabled` | Watcher active (true/false) |
| `poll_interval` | Polling interval in seconds (default: 10) |
| `response_webhook` | Webhook name from `apis.json` for replies |
| `agent` | Agent that replies to messages |

**API endpoints:**
- `GET /teams-watcher` - Status and statistics
- `POST /teams-watcher/start` - Start watcher
- `POST /teams-watcher/stop` - Stop watcher
- `POST /teams-watcher/clear` - Reset state

**Flow:**
1. Graph API polls channel every X seconds
2. New messages (not from bots) are detected
3. Configured agent is run with the message as prompt
4. Agent replies via `teams_post_to_configured_channel()`

## Gmail - Emails

Gmail integration via Google API with OAuth2 authentication.

**Authentication:**
- `gmail_authenticate()` - **Start OAuth2 sign-in** (browser flow)
- `gmail_status()` - Check current auth status
- `gmail_logout()` - Sign out and delete credentials
- `gmail_refresh_token()` - Refresh token manually

**Email operations:**
- `gmail_search_emails(query, limit, include_spam_trash)` - **Search emails** (Gmail syntax)
- `gmail_get_email(message_id)` - Read full email content
- `gmail_get_recent_emails(days, limit, label)` - Fetch newest emails
- `gmail_get_emails_by_label(label, limit)` - Emails with a specific label
- `gmail_get_unread_emails(limit)` - Unread emails
- `gmail_get_starred_emails(limit)` - Starred emails (like Outlook flags)
- `gmail_get_thread(thread_id)` - Read full conversation
- `gmail_mark_read(message_id, is_read)` - Mark as read/unread
- `gmail_get_profile()` - Profile info (email, message count)

**Drafts & send:**
- `gmail_create_draft(to, subject, body, cc, html)` - Create email draft
- `gmail_create_reply_draft(message_id, body, reply_all, from_email)` - **Reply with quoted original** (incl. "On [date], [sender] wrote:")
- `gmail_send_draft(draft_id)` - Send draft

**Gmail query syntax:**
```python
# Sender/recipient
gmail_search_emails("from:sender@example.com")
gmail_search_emails("to:recipient@example.com")

# Subject/content
gmail_search_emails("subject:Rechnung")
gmail_search_emails("invoice payment")  # Full-text search

# Filter
gmail_search_emails("has:attachment")
gmail_search_emails("is:unread")
gmail_search_emails("is:starred")

# Date
gmail_search_emails("after:2025/01/01")
gmail_search_emails("before:2025/12/31")

# Label (folder)
gmail_search_emails("label:INBOX")
gmail_search_emails("label:Work")

# Combined
gmail_search_emails("from:example.com subject:invoice after:2025/01/01 has:attachment")
```

## Gmail - Labels & Actions

Gmail uses labels instead of folders (one email can have multiple labels).

**Label management:**
- `gmail_list_labels()` - List all labels
- `gmail_create_label(name, background_color, text_color)` - Create new label
- `gmail_delete_label(label_id)` - Delete label

**Email actions:**
- `gmail_add_label(message_id, label)` - Add label (like folder move)
- `gmail_remove_label(message_id, label)` - Remove label
- `gmail_star_email(message_id, starred)` - Star/unstar (like flag)
- `gmail_archive_email(message_id)` - Archive (remove from Inbox)
- `gmail_trash_email(message_id)` - Move to trash
- `gmail_untrash_email(message_id)` - Restore from trash
- `gmail_delete_email(message_id)` - **Permanently delete** (not recoverable!)

**Batch actions:**
- `gmail_batch_actions(actions)` - **Multiple actions in one call**

**Batch format:**
```json
[
  {"action": "add_label", "message_id": "...", "label": "Work"},
  {"action": "star", "message_id": "..."},
  {"action": "archive", "message_id": "..."},
  {"action": "mark_read", "message_id": "..."}
]
```

**Available batch actions:** `add_label`, `remove_label`, `star`, `unstar`, `archive`, `trash`, `untrash`, `mark_read`, `mark_unread`

## Gmail - Attachments

- `gmail_get_attachments(message_id)` - **List attachments of an email**
- `gmail_download_attachment(message_id, attachment_id, save_path)` - Download attachment
- `gmail_download_all_attachments(message_id, save_path)` - Download all attachments
- `gmail_read_pdf_attachment(message_id, attachment_id)` - **Extract PDF text** (without saving)

**Workflow: Read PDF invoice**
```python
# 1. Search email
gmail_search_emails("from:lieferant@example.com has:attachment")

# 2. List attachments
gmail_get_attachments("message_id_123")
# → [{"index": 0, "filename": "Rechnung.pdf", "attachment_id": "att_456", ...}]

# 3. Read PDF text directly (without download)
gmail_read_pdf_attachment("message_id_123", "att_456")
# → "Rechnungsnummer: RE-2025-001..."
```

## Gmail - Google Calendar

Calendar operations with the Google Calendar API.

**Show appointments:**
- `gcal_get_today_events()` - Today's appointments
- `gcal_get_upcoming_events(days)` - Appointments for the next X days
- `gcal_get_event_details(event_id)` - Full appointment details
- `gcal_list_calendars()` - List all calendars
- `gcal_check_availability(date, start_time, end_time)` - Check if time slot is free

**Create appointments:**
- `gcal_create_event(subject, date, start, end, location, description)` - **Create appointment**
- `gcal_create_meeting(subject, date, start, end, attendees, add_meet_link)` - **Meeting with attendees**
- `gcal_delete_event(event_id)` - Delete appointment

**Examples:**
```python
# Simple appointment
gcal_create_event(
    subject="Arzttermin",
    date_str="15.01.2025",
    start_time="10:00",
    end_time="11:00",
    location="Praxis Dr. Müller"
)

# Meeting with Google Meet link
gcal_create_meeting(
    subject="Projekt-Besprechung",
    date_str="16.01.2025",
    start_time="14:00",
    end_time="15:00",
    attendees="max@example.com, anna@example.com",
    description="Agenda:\n- Status-Update\n- Nächste Schritte",
    add_meet_link=True  # Default: True
)
# → Google Meet link is generated automatically
```

## Gmail - Configuration

**apis.json:**
```json
"gmail": {
  "enabled": true,
  "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
  "client_secret": "YOUR_CLIENT_SECRET",
  "redirect_port": 8080
}
```

**Google Cloud setup:**
1. Open [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create project (or select existing)
3. Enable APIs: **Gmail API** and **Google Calendar API**
4. Create OAuth 2.0 credentials (type: **Desktop app**)
5. Enter `client_id` and `client_secret` in apis.json
6. Call `gmail_authenticate()` → browser opens Google login

**Tool mapping: Gmail vs Outlook vs Graph**

| Operation | Gmail | Outlook | MS Graph |
|-----------|-------|---------|----------|
| Search emails | `gmail_search_emails` | `outlook_fast_search_emails` | `graph_search_emails` |
| Read email | `gmail_get_email` | `outlook_get_email_content` | `graph_get_email` |
| Recent emails | `gmail_get_recent_emails` | `outlook_get_recent_emails` | `graph_get_recent_emails` |
| Create draft | `gmail_create_draft` | `outlook_create_new_email` | `graph_create_draft` |
| Reply draft | `gmail_create_reply_draft` | `outlook_create_reply_draft` | `graph_create_reply_draft` |
| Star/flag | `gmail_star_email` | `outlook_flag_email` | `graph_flag_email` |
| Labels/folders | `gmail_add_label` | `outlook_move_email` | `graph_move_email` |
| Attachments | `gmail_get_attachments` | `outlook_get_email_attachments` | `graph_get_attachments` |
| Today's events | `gcal_get_today_events` | `outlook_get_today_events` | `graph_get_today_events` |
| Create event | `gcal_create_event` | `outlook_create_appointment` | `graph_create_calendar_event` |

## IMAP/SMTP - Emails (standard protocols)

Standard IMAP/SMTP MCP for email providers without special API (e.g. own mail server, provider emails).

**Special feature: custom IMAP flags (keywords)**
- Set own flags like "NeedsReview", "Processed", "Urgent" on emails
- Search by custom flags for workflow automation
- Independent of provider-specific features

### IMAP - Read Emails

- `imap_list_folders()` - **List all IMAP folders**
- `imap_search_emails(folder, search_criteria, limit)` - **Search emails**
  - Supports IMAP search criteria: ALL, UNSEEN, FLAGGED, FROM, SUBJECT, BODY, SINCE, BEFORE, KEYWORD
- `imap_get_email(uid, folder)` - **Read full email content**
- `imap_get_recent_emails(folder, days, limit, only_unseen)` - **Emails of the last N days**
- `imap_get_unread_emails(folder, limit)` - **Unread emails**
- `imap_get_flagged_emails(folder, limit)` - **Flagged emails**
- `imap_mark_read(uid, folder, is_read)` - **Mark as read/unread**
  - `is_read=True`: Mark as read (default)
  - `is_read=False`: Mark as unread

**IMAP search criteria examples:**
```python
# All emails
imap_search_emails("INBOX", "ALL")

# Unread
imap_search_emails("INBOX", "UNSEEN")

# From specific sender
imap_search_emails("INBOX", "FROM sender@example.com")

# Subject contains keyword
imap_search_emails("INBOX", "SUBJECT invoice")

# Since date
imap_search_emails("INBOX", "SINCE 1-Jan-2025")

# Combined
imap_search_emails("INBOX", "(FROM example.com UNSEEN)")

# With custom flag
imap_search_emails("INBOX", "KEYWORD NeedsReview")
```

### IMAP - Custom Flags (Keywords)

**Custom flags** enable workflow automation independent of the email provider:

- `imap_get_flags(uid, folder)` - **All flags of an email** (standard + custom)
- `imap_set_custom_flag(uid, keyword, folder)` - **Set custom flag**
  - Example: `imap_set_custom_flag("123", "NeedsReview", "INBOX")`
- `imap_remove_custom_flag(uid, keyword, folder)` - **Remove custom flag**
- `imap_search_by_custom_flag(keyword, folder, limit)` - **Search by custom flag**
  - Example: `imap_search_by_custom_flag("Processed", "INBOX")`
- `imap_list_custom_flags(folder)` - **List all custom flags in folder**

**Workflow example:**
```python
# 1. Search emails that need review
emails = imap_search_emails("INBOX", "FROM support@example.com UNSEEN")

# 2. Set custom flag for workflow
imap_set_custom_flag("123", "NeedsReview", "INBOX")

# 3. Later: find all review emails
review_emails = imap_search_by_custom_flag("NeedsReview", "INBOX")

# 4. After processing: remove flag, set new one
imap_remove_custom_flag("123", "NeedsReview", "INBOX")
imap_set_custom_flag("123", "Processed", "INBOX")
```

**Standard IMAP flags:**
- `imap_set_flag(uid, flag, folder)` - **Set standard flag**
  - `\\Seen` - Mark as read
  - `\\Flagged` - Flag
  - `\\Answered` - Mark as answered
  - `\\Draft` - Mark as draft
  - `\\Deleted` - Mark for deletion
- `imap_remove_flag(uid, flag, folder)` - **Remove standard flag**

### IMAP - Attachments

- `imap_get_attachments(uid, folder)` - **List all attachments of an email**
  - Returns JSON with index, filename, content_type, size_bytes, size_kb
- `imap_download_attachment(uid, attachment_index, folder, save_path)` - **Download attachment**
  - `attachment_index`: Index from imap_get_attachments (default: 0 = first attachment)
  - `save_path`: Target directory (default: .temp/)
- `imap_read_pdf_attachment(uid, attachment_index, folder)` - **Extract PDF text directly**
  - Reads PDF content without saving to disk
  - Ideal for invoices, documents, etc.

**Example:**
```python
# 1. List attachments
attachments = imap_get_attachments("123", "INBOX")
# → {"attachments": [{"index": 0, "filename": "invoice.pdf", "size_kb": 45.2}]}

# 2. Read PDF directly
text = imap_read_pdf_attachment("123", 0, "INBOX")

# 3. Or download file
imap_download_attachment("123", 0, "INBOX", "/path/to/save")
```

### SMTP - Send Emails

- `smtp_send_email(to, subject, body, cc, bcc, html, reply_to)` - **Send email**
  - Plain text or HTML
  - CC/BCC support
  - Reply-To header
- `smtp_send_with_attachment(to, subject, body, attachment_path, ...)` - **Email with attachment**
- `smtp_send_reply(to, subject, body, in_reply_to, references, cc, html)` - **Reply with threading**
  - In-Reply-To and References headers for correct conversation association
- `imap_send_reply(uid, folder, body, html, reply_all)` - **Reply by UID (combo tool)**
  - Automatically reads original headers (From, Subject, Message-ID)
  - Sends reply with correct threading headers via SMTP
  - `reply_all=True`: Reply to all (incl. CC)

**Examples:**
```python
# Simple email
smtp_send_email(
    to="customer@example.com",
    subject="Re: Your inquiry",
    body="Thank you for your message..."
)

# With attachment
smtp_send_with_attachment(
    to="customer@example.com",
    subject="Your invoice",
    body="Please find attached...",
    attachment_path="/path/to/invoice.pdf"
)

# Reply with threading
smtp_send_reply(
    to="customer@example.com",
    subject="Re: Support Request #123",
    body="We have resolved your issue...",
    in_reply_to="<message-id@example.com>",
    references="<thread-id@example.com> <message-id@example.com>"
)
```

### IMAP - Email Management

- `imap_move_email(uid, source_folder, target_folder)` - **Move email**
- `imap_copy_email(uid, source_folder, target_folder)` - **Copy email**
- `imap_delete_email(uid, folder, expunge)` - **Delete email**
  - `expunge=True`: Permanently delete immediately
  - `expunge=False`: Only mark as deleted
- `imap_batch_actions(actions)` - **Multiple actions in one call**
  - Supports: mark_read, mark_unread, flag, unflag, move, delete, set_keyword, remove_keyword
  - Optimized for performance with bulk operations (e.g. daily check)

**Batch example:**
```python
imap_batch_actions('[
  {"action": "mark_read", "uid": "10", "folder": "INBOX"},
  {"action": "set_keyword", "uid": "10", "keyword": "IsDone"},
  {"action": "move", "uid": "15", "folder": "INBOX", "target": "Archive"}
]')
```

**Folder management:**
- `imap_create_folder(folder_name)` - **Create folder**
- `imap_delete_folder(folder_name)` - **Delete folder** (must be empty)
- `imap_rename_folder(old_name, new_name)` - **Rename folder**

### IMAP/SMTP - Configuration

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

**Notes:**
- IMAP port: 993 (SSL), 143 (unencrypted, not recommended)
- SMTP port: 587 (STARTTLS), 465 (SSL)
- `imap_ssl`: SSL encryption for IMAP (recommended)
- `smtp_tls`: STARTTLS for SMTP (recommended)

**Compatibility:**
- Works with all IMAP/SMTP-compatible servers
- Tested with: Gmail, Office 365, Exchange, Dovecot, Postfix
- **Custom flags**: Not all servers support keywords (check PERMANENTFLAGS)

## Billomat - Customers
- `billomat_search_customers` - Search customers
- `billomat_get_customer` - Retrieve customer details
- `billomat_create_customer` - Create new customer
- `billomat_update_customer` - Update customer data

## Billomat - Quotes
- `billomat_create_offer` - Create quote (draft)
- `billomat_get_offer` - Retrieve quote details
- `billomat_get_recent_offers` - Most recent quotes
- `billomat_add_offer_item` - Add product to quote
- `billomat_get_offer_items` - Show quote items
- `billomat_finalize_offer(offer_id)` - **Finalize quote** (status → OPEN)
- `billomat_download_offer_pdf(offer_id)` - **Download PDF** (for email attachment)

**Workflow: Create and send quote**
```
1. billomat_create_offer(customer_id)        → Create draft
2. billomat_add_offer_item(offer_id, "RVP1") → Add products
3. billomat_finalize_offer(offer_id)         → Finalize
4. billomat_download_offer_pdf(offer_id)     → Download PDF
5. outlook_create_reply_draft_with_attachment(body, pdf_path) → Send as reply
```

## Billomat - Invoices
- `billomat_create_invoice(customer_id, intro, template, address, label)` - **Create invoice with all options**
  - `intro`: Intro text (e.g. "Ihre Bestellnummer: PO-12345...")
  - `template`: "rechnung-de-software" or "rechnung-en-software"
  - `address`: Billing address (overrides customer address)
- `billomat_get_recent_invoices` - Most recent invoices
- `billomat_search_invoices` - Search invoices (by customer, number, status)
- `billomat_search_invoices_by_article(article_number, from_date, to_date, status)` - **Find invoices by article** (e.g. all with "RVP1"). Searches directly via invoice-items API instead of querying all invoices individually.
- `billomat_get_invoice` - Retrieve invoice details
- `billomat_get_invoices_by_period(from_date, to_date, status)` - **Invoices by period** (format: YYYY-MM-DD)
- `billomat_download_invoice_pdf(invoice_id, save_path, filename)` - **Download PDF**
- `billomat_add_invoice_item` - Add item to invoice
- `billomat_add_timelog_to_invoice` - Add timelog entry as item (default: €150/h)
- `billomat_add_article_to_invoice` - Add article to invoice
- `billomat_get_invoice_items` - Show invoice items
- `billomat_update_invoice_item` - Update invoice item
- `billomat_delete_invoice_item` - Delete invoice item

## Billomat - Payments
- `billomat_get_open_invoices` - **All open/overdue invoices** (with client cache)
- `billomat_mark_invoice_paid(invoice_id, payment_type)` - **Mark invoice as paid** (payment_type: BANK_TRANSFER, CASH, PAYPAL, etc.)
- `billomat_open_invoice(invoice_id)` - **Open invoice in browser**

## Billomat - Articles
- `billomat_get_articles` - List available products
- `billomat_search_article` - Search article

## Billomat - Batch Tools (Performance)

- `billomat_create_complete_offer(customer_id, items, finalize)` - **Quote with all items in 1 call**
- `billomat_add_invoice_items_batch(invoice_id, items)` - **Multiple invoice items in 1 call**

**Quote items format:**
```json
[
  {"article": "RVP1", "quantity": 1},
  {"article": "DL4", "quantity": 2, "description": "Setup & Training"}
]
```

**Invoice items format:**
```json
[
  {"title": "Beratung 10.12.", "hours": 2, "rate": 150},
  {"article": "RVP1", "quantity": 1}
]
```

**Performance gain:** ~80% fewer API calls, article cache (1h TTL)

## Lexware Office (lexoffice) - Contacts
- `lexware_search_contacts(query, role)` - Search contacts (role: "customer" or "vendor")
- `lexware_get_contact(contact_id)` - Retrieve contact details
- `lexware_create_contact(...)` - Create new contact
- `lexware_update_contact(contact_id, ...)` - Update contact

## Lexware Office - Articles
- `lexware_get_articles()` - List all articles/products
- `lexware_get_article(article_id)` - Retrieve article details
- `lexware_search_articles(query)` - Search articles by title/number

## Lexware Office - Quotes
- `lexware_create_quotation(contact_id, title, introduction, validity_days)` - Create quote
- `lexware_get_quotation(quotation_id)` - Retrieve quote details
- `lexware_get_recent_quotations(limit)` - Most recent quotes
- `lexware_add_quotation_item(quotation_id, title, quantity, unit_price, ...)` - Add item
- `lexware_download_quotation_pdf(quotation_id, save_path, filename)` - **Download PDF**

## Lexware Office - Invoices
- `lexware_create_invoice(contact_id, title, introduction, finalize)` - Create invoice
- `lexware_get_invoice(invoice_id)` - Retrieve invoice details
- `lexware_get_recent_invoices(limit)` - Most recent invoices
- `lexware_add_invoice_item(invoice_id, title, quantity, unit_price, ...)` - Add item
- `lexware_finalize_invoice(invoice_id)` - Finalize invoice
- `lexware_download_invoice_pdf(invoice_id, save_path, filename)` - **Download PDF**
- `lexware_get_open_invoices()` - **List open invoices**

## Lexware Office - Payments & Credit Notes
- `lexware_get_payments(voucher_id)` - Retrieve payments for a voucher
- `lexware_create_credit_note(contact_id, title, invoice_id, finalize)` - Create credit note
- `lexware_get_credit_note(credit_note_id)` - Retrieve credit note details

**Workflow: Create quote**
```python
# 1. Search or create contact
lexware_search_contacts("Firma XY")  # or lexware_create_contact(...)

# 2. Create quote
lexware_create_quotation("uuid-123", title="Projektangebot", validity_days=30)

# 3. Add items
lexware_add_quotation_item("quote-uuid", "Beratung", quantity=8, unit_price=150, unit="Stunde")
lexware_add_quotation_item("quote-uuid", "Software-Lizenz", quantity=1, unit_price=1098)

# 4. Download PDF
lexware_download_quotation_pdf("quote-uuid")
```

**API details:**
- Base URL: `https://api.lexoffice.io/v1`
- Auth: Bearer token in Authorization header
- Rate limit: 2 requests/second
- XL plan required for API access

**Configuration in apis.json:**
```json
"lexware": {
  "api_key": "YOUR_LEXWARE_API_KEY"
}
```

**Generate API key:** https://app.lexoffice.de/addons/public-api

## UserEcho - Support Tickets
- `userecho_get_forums` - List all forums/categories
- `userecho_get_recent_new_tickets()` - **New tickets for daily check** (status New + max 14 days)
- `userecho_get_open_tickets(forum_id, limit, max_age_days)` - Open tickets (with optional age filter)
- `userecho_get_tickets_by_status(status)` - **Tickets by status** (e.g. "planned", "new", "review")
- `userecho_get_all_tickets(forum_id, status, limit)` - Tickets with status filter
- `userecho_get_ticket(ticket_id)` - Full ticket details with description
- `userecho_get_ticket_comments(ticket_id)` - All comments/replies of a ticket
- `userecho_search_tickets(query, limit)` - Search tickets by query
- `userecho_create_ticket_reply(ticket_id, text, is_official)` - **Create and send reply**
- `userecho_create_ticket_reply_draft(ticket_id, text)` - Show reply draft (without sending)
- `userecho_update_ticket_status(ticket_id, status, forum_id)` - Change status

**Status values (helpdesk):**
- `new` - New (ID 1) - **CRITICAL: never processed!**
- `review` - Under review (ID 17)
- `planned` - Planned (ID 18)
- `started` - Started (ID 19)
- `completed` - Completed (ID 20, closed)

**Workflow: Reply to support ticket**
```
1. userecho_get_open_tickets()              → Show open tickets
2. userecho_get_ticket(ticket_id)           → Read details
3. userecho_get_ticket_comments(ticket_id)  → Previous replies
4. userecho_create_ticket_reply_draft(ticket_id, text) → Check draft
5. userecho_create_ticket_reply(ticket_id, text)   → Send reply
6. userecho_update_ticket_status(ticket_id, "answered") → Set status
```

**Configuration in apis.json:**
```json
"userecho": {
  "subdomain": "meine-firma",
  "api_key": "YOUR_API_KEY"
}
```

## Clipboard
- `clipboard_get` - Read text from clipboard
- `clipboard_set` - Write text to clipboard
- `clipboard_append` - Append text to clipboard

## DataStore - Persistent Data Storage

SQLite-based data store. Database: `workspace/.state/datastore.db`

**Documents (structured JSON objects):**
- `db_doc_save(collection, doc_id, data)` - Save/update document
- `db_doc_get(collection, doc_id)` - Retrieve document
- `db_doc_list(collection)` - All documents of a collection
- `db_doc_find(collection, field, value)` - Search documents by field (substring match)
- `db_doc_delete(collection, doc_id)` - Delete document
- `db_doc_collections()` - All document collections with count

**Collections (string lists):**
- `db_add(collection, value)` - Add item (with auto-timestamp)
- `db_remove(collection, value)` - Remove item
- `db_list(collection)` - List all items (JSON)
- `db_contains(collection, value)` - Check if item exists ("true"/"false")
- `db_search(collection, pattern)` - Search items (substring match)
- `db_clear(collection)` - Empty collection

**Key-value:**
- `db_set(key, value)` - Store value
- `db_get(key)` - Retrieve value (or "null")
- `db_delete(key)` - Delete key

**Counter:**
- `db_increment(name, amount=1)` - Increment counter
- `db_get_counter(name)` - Get counter value
- `db_reset_counter(name)` - Reset counter

**Info & cost:**
- `db_collections()` - All collection names with count
- `db_stats()` - Database statistics (size, counts)
- `db_api_costs()` - API cost statistics (by model, backend, date)

**Examples:**
```python
# Store contact
db_doc_save("contacts", "max_mueller", {
  "name": "Max Müller", "email": "max@acme.de", "company": "ACME GmbH"
})
db_doc_find("contacts", "company", "ACME")  # → All ACME contacts

# Spam list
db_add("blocked_senders", "spam@example.com")
db_contains("blocked_senders", "spam@example.com")  # → "true"

# Key-value
db_set("last_daily_check", "2025-01-08")
db_get("last_daily_check")  # → "2025-01-08"

# Counter
db_increment("emails_processed")
db_get_counter("emails_processed")  # → "47"

# Query cost
db_api_costs()  # → {"total_usd": 10.01, "by_model": {...}, ...}
```

## Browser - Open Web Pages
- `browser_open_url` - Open URL in default browser
- `browser_open_url_new_tab` - Open URL in new tab
- `browser_open_url_new_window` - Open URL in new window

## Browser - Automation (Chrome Remote Debugging)

Tools for browser automation via Chrome DevTools Protocol (CDP):

**Connection:**
- `browser_start(browser_type, url)` - **Start browser with remote debugging** (vivaldi/chrome/edge)
- `browser_status()` - Check connection status
- `browser_connect()` - Connect to running browser (port 9222)

**Tab management:**
- `browser_get_tabs()` - List all open tabs
- `browser_switch_tab(tab_index)` - Switch to tab

**Navigation & info:**
- `browser_navigate(url)` - Navigate to URL
- `browser_get_page_info()` - Page info (URL, title, text)

**Forms:**
- `browser_get_forms()` - Find all forms and fields
- `browser_fill_field(selector, value)` - Fill single field
- `browser_fill_form(fields)` - Fill multiple fields (JSON)
- `browser_select(selector, value)` - Select dropdown option

**Interaction:**
- `browser_click(selector)` - Click element (CSS selector)
- `browser_click_text(text)` - Click element (visible text)
- `browser_type(selector, text, delay)` - Type text (character by character)
- `browser_press_key(key)` - Press key (Enter, Tab, Escape, etc.)
- `browser_wait(selector, timeout)` - Wait for element

**Content:**
- `browser_get_text(selector)` - Read element text
- `browser_execute_js(script)` - Execute JavaScript
- `browser_screenshot(path)` - Create screenshot

**Workflow: Perform UI test**
```python
# 1. Start browser with remote debugging
browser_start("chrome", "http://localhost:8765/")

# 2. Or: connect to existing browser
browser_connect()

# 3. Fill form
browser_fill_form('{"#username": "admin", "#password": "secret"}')

# 4. Click button
browser_click("button[type='submit']")

# 5. Wait for result
browser_wait(".success-message", timeout=5000)

# 6. Screenshot for verification
browser_screenshot(".temp/login_result.png")
```

**Note:** Browser must be started with `--remote-debugging-port=9222`. See `/browser-test` for full workflow.

## DeskAgent - System Control
- `desk_restart()` - **Restart DeskAgent** (stops current instance, restarts)
- `desk_get_status()` - Retrieve status and version
- `desk_list_agents()` - List all available agents
- `desk_run_agent(agent_name, inputs)` - **Start agent in background**
- `desk_list_agent_tools()` - **List auto-discovered agent tools**
- `desk_add_agent_config(name, category, ...)` - **Add agent to agents.json**
- `desk_remove_agent_config(name)` - **Remove agent from agents.json**
- `desk_get_agent_log()` - **Read last agent log** (agent_latest.txt)
- `desk_get_mcp_log(lines=100)` - **Read MCP/system log** (last N lines)

**Start agent with inputs:**
```python
# Agent without inputs
desk_run_agent("daily_check")

# Agent with inputs (JSON string)
desk_run_agent("archive_files", '{"files": ["/path/to/file.pdf"]}')
```

**Agent-as-Tool architecture:**

Agents with a `tool` definition in the frontmatter are automatically registered as structured MCP tools:

```python
# Instead of generic:
desk_run_agent("invoice_processor", inputs='{"invoices": [...]}')

# Structured (when tool is defined):
process_invoices(invoices=[...])  # Auto-discovered tool
```

See [docs/agent-as-tool-architecture.md](docs/agent-as-tool-architecture.md) for details.

**Restart workflow:**
```python
# 1. Save changes to agent files
fs_write_file("agents/my_agent.md", new_content)

# 2. Restart DeskAgent
desk_restart()  # Restarts automatically
```

## Filesystem - Generic File Operations
- `fs_read_file(path, encoding)` - Read text file (max. 10MB)
- `fs_read_pdf(path)` - **Extract PDF text** (uses pypdf)
- `fs_read_pdfs_batch(paths)` - **Read multiple PDFs in one call** (performance)
- `fs_write_file(path, content, encoding)` - Write/create file
- `fs_list_directory(path, pattern)` - List directory contents
- `fs_file_exists(path)` - Check if file/folder exists
- `fs_get_file_info(path)` - File metadata (size, date, type)
- `fs_copy_file(source, destination)` - Copy file
- `fs_delete_file(path)` - Delete file (no folders)

**Note:** No path restrictions - the user selects files explicitly. Used for agent pre-inputs.

**Read PDF:** Use `fs_read_pdf()` instead of `fs_read_file()` for PDF files.

**Batch PDF read:**
```python
# Read multiple PDFs efficiently
fs_read_pdfs_batch([
    ".temp/invoice1.pdf",
    ".temp/invoice2.pdf",
    ".temp/invoice3.pdf"
])
# → {"invoice1.pdf": "Text...", "invoice2.pdf": "Text...", ...}
```

## Excel - Read and Write Spreadsheets

### File Information
- `excel_get_info(file_path)` - **Information about Excel file** (sheets, sizes)
- `excel_list_sheets(file_path)` - **List all worksheets**

### Read
- `excel_read_cell(file_path, cell_ref, sheet_name, preserve_formulas)` - **Read single cell** (e.g. 'A1')
- `excel_read_range(file_path, range_ref, sheet_name, include_header, preserve_formulas)` - **Read cell range** (e.g. 'A1:C10')
- `excel_read_sheet(file_path, sheet_name, max_rows, preserve_formulas)` - **Read full worksheet** (first row = header)

**Parameter `preserve_formulas`:**
- `false` (default): Reads computed values (e.g. `300` instead of `=SUM(A1:A2)`)
- `true`: Reads formulas as string (e.g. `=SUM(A1:A2)`)

### Write
- `excel_write_cell(file_path, cell_ref, value, sheet_name)` - **Write single cell** (detects formulas with "=")
- `excel_write_range(file_path, range_ref, data, sheet_name)` - **Write cell range** (detects formulas with "=")
- `excel_write_sheet(file_path, data, sheet_name, clear_existing)` - **Write entire worksheet** (detects formulas with "=")

**FORMULAS:** Strings beginning with "=" are written automatically as Excel formulas.
- Example: `{"Total": "=SUM(A1:A10)"}` → Formula in Excel cell
- Example: `excel_write_cell("file.xlsx", "C3", "=A1+B1")` → Formula in C3

### Manage Worksheets
- `excel_create_sheet(file_path, sheet_name)` - **Create new worksheet**
- `excel_delete_sheet(file_path, sheet_name)` - **Delete worksheet**

**Supported formats:** .xlsx (OpenXML format)

**Paths:** Absolute paths or relative to workspace (e.g. `exports/data.xlsx`)

**Workflow: Read and process Excel file**
```python
# 1. File info
excel_get_info("exports/kunden.xlsx")
# → {"sheet_count": 2, "sheets": [{"name": "Kunden", "rows": 150, "columns": 8}, ...]}

# 2. Read worksheet (with header)
excel_read_sheet("exports/kunden.xlsx", "Kunden", max_rows=100)
# → {"sheet": "Kunden", "rows": 99, "data": [{"Name": "Müller GmbH", "E-Mail": "info@mueller.de", ...}, ...]}

# 3. Read specific range
excel_read_range("exports/kunden.xlsx", "A1:C10", "Kunden")
# → [{"Name": "Müller GmbH", "Ort": "Berlin", "Status": "Aktiv"}, ...]

# 4. Read single cell
excel_read_cell("exports/kunden.xlsx", "B5", "Kunden")
# → "info@mueller.de"
```

**Workflow: Write Excel file**
```python
# 1. Create new file with data
data = [
    {"Name": "Müller GmbH", "Ort": "Berlin", "Status": "Aktiv"},
    {"Name": "Schmidt AG", "Ort": "München", "Status": "Inaktiv"}
]
excel_write_range("exports/neue_kunden.xlsx", "A1:C3", json.dumps(data), "Kunden")

# 2. Update single cell
excel_write_cell("exports/kunden.xlsx", "D5", "Bezahlt", "Rechnungen")

# 3. Add new worksheet
excel_create_sheet("exports/kunden.xlsx", "Archiv")
```

**Workflow: Full roundtrip (read → process → write)**
```python
# 1. READ: read full worksheet
result = excel_read_sheet("exports/kunden.xlsx", "Aktiv", max_rows=500)
data = json.loads(result)
# → {"sheet": "Aktiv", "rows": 123, "data": [{"Name": "...", "Email": "...", "Status": "..."}, ...]}

# 2. PROCESS: AI analyzes/modifies data
customers = data["data"]
# ... AI makes changes to customers ...

# 3. WRITE: write complete sheet back (WITHOUT range!)
excel_write_sheet("exports/kunden_neu.xlsx", json.dumps(customers), "Aktiv")
# → Writes automatically: header + all 123 rows
# → "OK: 123 rows × 5 columns written in 'Aktiv'"
```

**Advantage of `excel_write_sheet()` vs `excel_write_range()`:**
- No range calculation needed ("A1:Z501" etc.)
- Automatic size detection
- Automatically deletes old data (`clear_existing=True`)
- Ideal for full-roundtrip workflows

**Workflow: Preserve formulas (full-roundtrip with formulas)**
```python
# 1. READ: with preserve_formulas=True
result = excel_read_sheet("rechnung.xlsx", "Calc", max_rows=100, preserve_formulas=True)
data = json.loads(result)["data"]
# → [{"Pos": "1", "Menge": "5", "Preis": "10", "Total": "=B2*C2"}, ...]

# 2. PROCESS: AI changes only data, not formulas
# Formulas stay as "=B2*C2" string

# 3. WRITE: formulas are detected automatically (string with "=")
excel_write_sheet("rechnung_neu.xlsx", json.dumps(data), "Calc")
# → Formulas are written as Excel formulas, not as text!
```

**Workflow: Add formulas**
```python
# Create invoice with total row
data = [
    {"Artikel": "Produkt A", "Menge": "10", "Preis": "5.50", "Total": "=B2*C2"},
    {"Artikel": "Produkt B", "Menge": "3", "Preis": "12.00", "Total": "=B3*C3"},
    {"Artikel": "SUMME", "Menge": "", "Preis": "", "Total": "=SUM(D2:D3)"}
]
excel_write_sheet("rechnung.xlsx", json.dumps(data), "Rechnung")
# → Excel computes automatically: Total column + total row
```

**Notes:**
- Files are created automatically if they do not exist
- The first row is used as column header in `read_sheet` and `read_range` (unless `include_header=False`)
- For `write_range` and `write_sheet` with dictionaries, headers are added automatically
- **FORMULAS:** Control computed values vs formulas via `preserve_formulas` parameter
- **WRITE formulas:** Automatic detection via "=" at the start (no escape needed)

## Project - Run Claude Code in Other Projects
- `project_ask(prompt, project_path, timeout)` - **Run Claude Code CLI in the target project**
- `project_ask_with_context(prompt, project_path, context)` - With additional context (e.g. email)
- `project_list_knowledge(project_path)` - List knowledge files of the project
- `project_check(project_path)` - Check if project is set up for Claude Code

**Workflow: Reply to support request with external project**
```
1. outlook_get_selected_email()   → Read customer request
2. project_check("E:/docs")       → Check project
3. project_ask_with_context(      → Generate reply
     prompt="Beantworte diese Anfrage",
     project_path="E:/docs",
     context="<email content>"
   )
4. outlook_create_reply_draft(body)       → Create draft
```

**Note:** The target project should have its own CLAUDE.md with product/support expertise.

**Product codes:**
- `RVP1` - Professional Edition (€1,098)
- `RVR1` - Research & Education Bundle (€2,100)
- `DL4` - Online Training and Support (€150/h)

## PDF - Edit Documents
- `pdf_get_info(path)` - **PDF metadata** (pages, size, author, etc.)
- `pdf_extract_pages(source, pages, output)` - **Extract pages** to new PDF
- `pdf_merge(files, output)` - **Merge PDFs**
- `pdf_split(source, output_dir)` - **Split PDF into individual pages**

**Page syntax for `pdf_extract_pages`:**
| Syntax | Description |
|--------|-------------|
| `"1"` | Single page |
| `"1-5"` | Page range |
| `"1,3,5"` | Multiple individual pages |
| `"1-3,7,10-12"` | Mixed |
| `"-1"` | Last page |
| `"-3"` | Third to last page |

**Examples:**
```python
# Show PDF info
pdf_get_info("C:/Dokumente/Vertrag.pdf")

# Extract first 3 pages
pdf_extract_pages("C:/input.pdf", "1-3", "C:/output.pdf")

# Extract pages 1, 5 and 10-15
pdf_extract_pages("C:/input.pdf", "1,5,10-15")

# Extract last page
pdf_extract_pages("C:/input.pdf", "-1", "C:/letzte_seite.pdf")

# Merge multiple PDFs
pdf_merge(["doc1.pdf", "doc2.pdf", "doc3.pdf"], "combined.pdf")

# Split PDF into individual pages
pdf_split("C:/buch.pdf", "C:/seiten/")
```

## SEPA - Transfers (pain.001)
- `sepa_validate_iban(iban)` - **Validate IBAN** (checksum + length)
- `sepa_create_transfer(..., account, filename)` - Create **single transfer**
- `sepa_create_batch(payments, account, filename)` - **Batch transfer** with multiple payments
- `sepa_get_accounts()` - **Show all accounts** (IBANs masked)
- `sepa_lookup_recipient_iban(name)` - **Look up recipient IBAN** (full IBAN for transfers)
- `sepa_get_details(filename)` - **Full overview** (From, From-IBAN, To, To-IBAN, reference, amount)
- `sepa_list_files()` - **List all created SEPA files**
- `sepa_append(filename, payments)` - **Append payments to existing file**
- `sepa_clear_files()` - **Delete all SEPA files** (before a new session)

**File name convention:**
- Format: `sepa-{account}-{YYYYMMDD}.xml`
- Example: `sepa-meinefirma-20251231.xml` or `sepa-private-20251231.xml`

**Configuration in config/banking.json:**
```json
{
  "meinefirma": {
    "name": "Meine Firma GmbH",
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
  "default": "meinefirma"
}
```

**Workflow: Look up recipient IBAN**
```python
# Name from document → look up IBAN
sepa_lookup_recipient_iban("Erika Musterfrau")
# → {"found": true, "name": "Erika Musterfrau", "iban": "DE89370400440532013001", ...}

# Partial match (first name/last name) also works:
sepa_lookup_recipient_iban("Erika")
# → Finds "Erika Musterfrau"
```

**Workflow: Pay supplier invoice**
```python
# 1. Show available accounts
sepa_get_accounts()

# 2. Transfer with default account (meinefirma)
sepa_create_transfer(
    creditor_name="Lieferant GmbH",
    creditor_iban="DE89370400440532013000",
    amount=1500.00,
    reference="Rechnung RE-2025-001"
)

# 3. Transfer with private account
sepa_create_transfer(..., account="private")

# 4. Batch transfer for company
sepa_create_batch('[...]', account="meinefirma")
```

**Format:** pain.001.001.03 (SEPA Credit Transfer, ISO 20022)

## SEPA - Read Bank Statements (CAMT.052)
- `sepa_read_camt052_zip(zip_path)` - **Read bank statements from ZIP** (intraday reports)
- `sepa_read_camt052_xml(xml_path)` - Read single CAMT.052 XML file
- `sepa_get_camt_credits(zip_path, min_amount)` - **Extract only incoming payments** (for invoice matching)

**CAMT.052 format:** ISO 20022 Bank to Customer Account Report (intraday)

**Workflow: Check incoming payments**
```python
# 1. Download CAMT.052 ZIP from the bank

# 2. Extract all incoming payments
sepa_get_camt_credits("C:/Downloads/kontoauszug.zip")
# → {"credits": [{"date": "2025-01-03", "amount": 1098.00, "debtor_name": "Kunde GmbH", ...}], ...}

# 3. Match against open invoices (Billomat)
billomat_get_open_invoices()
```

**Extracted data per transaction:**
- `booking_date` / `value_date` - Booking/value date
- `amount`, `currency` - Amount and currency
- `type` - "credit" (incoming) or "debit" (outgoing)
- `debtor_name`, `debtor_iban` - Payer for credits
- `creditor_name`, `creditor_iban` - Recipient for debits
- `reference` - Purpose
- `end_to_end_id` - End-to-end reference

## ecoDMS - Document Archive

Tools to archive, search, and manage documents in ecoDMS:

**Archive information:**
- `ecodms_test_connection()` - **Test connection**
- `ecodms_get_folders()` - List folders/locations
- `ecodms_get_document_types()` - List document types
- `ecodms_get_statuses()` - List status values
- `ecodms_get_roles()` - List roles/permissions
- `ecodms_get_classify_attributes()` - List classification attributes

**Document operations:**
- `ecodms_search_documents(query, folder_id, doc_type, status, date_from, date_to)` - **Search documents**
- `ecodms_get_document_info(doc_id)` - Retrieve document metadata
- `ecodms_download_document(doc_id, save_path)` - **Download document** (1 API connect)
- `ecodms_upload_document(file_path, version_controlled)` - **Upload document** (1 API connect)
- `ecodms_classify_document(doc_id, folder_id, doc_type, status, bemerkung)` - Classify document
- `ecodms_archive_file(file_path, folder_id, doc_type, status, bemerkung)` - **Upload + classify in one step**
- `ecodms_get_thumbnail(doc_id, page, height)` - Thumbnail URL (no API connects)

**Workflow: Archive document**
```python
# 1. Test connection
ecodms_test_connection()

# 2. Show available folders and types
ecodms_get_folders()
ecodms_get_document_types()

# 3. Archive and classify file
ecodms_archive_file(
    file_path=".temp/rechnung.pdf",
    folder_id="5",           # Target folder
    doc_type="Rechnung",     # Document type
    status="Neu",            # Status
    bemerkung="Rechnung 2024-001"
)
```

**Configuration in apis.json:**
```json
"ecodms": {
  "url": "http://localhost:8180",
  "username": "ecodms",
  "password": "ecodms",
  "archive_id": "1"
}
```

**API limits:** Every upload/download consumes 1 API connect. Standard license: 10/month. ecoDMS ONE: unlimited.

## Paperless-ngx - Document Management

Open-source document management system with OCR and full-text search.

**Connection & authentication:**
- `paperless_test_connection()` - **Test connection**
- `paperless_get_token(username, password)` - **Get API token** (for apis.json)

**Document operations:**
- `paperless_search_documents(query, correspondent_id, correspondent_isnull, document_type_id, tag_ids, ...)` - **Search documents**
  - `correspondent_isnull=True` - Only documents WITHOUT correspondent (unclassified)
  - `correspondent_isnull=False` - Only documents WITH correspondent (classified)
- `paperless_get_document(doc_id)` - Retrieve document metadata
- `paperless_get_document_content(doc_id)` - **Read OCR text of a document**
- `paperless_download_document(doc_id, save_path, original)` - **Download document**
- `paperless_export_document_pdf(doc_id, save_path)` - **Export PDF** with name format `YYYY-MM-DD-[Correspondent]-[doc_id].pdf`
- `paperless_upload_document(file_path, title, correspondent_id, storage_path_id, tag_ids, ...)` - **Upload document**
- `paperless_update_document(doc_id, title, correspondent_id, storage_path_id, ...)` - Update document
- `paperless_delete_document(doc_id)` - Delete document
- `paperless_find_similar_documents(doc_id, limit)` - **Find similar documents**

**Bulk operations:**
- `paperless_bulk_edit_documents(document_ids, operation, value)` - **Edit multiple documents** (same operation)
  - Operations: `set_correspondent`, `set_document_type`, `add_tag`, `remove_tag`, `delete`, `reprocess`
- `paperless_batch_classify_documents(classifications)` - **Classify documents** (correspondents/tags/storage path/date)
  - JSON array: `[{"doc_id": 1, "correspondent_name": "Firma", "tag_ids": "7,3", "storage_path_name": "Privat", "created": "2025-01-15"}, ...]`
  - Creates missing correspondents and storage paths automatically
  - `storage_path_name`: Optional, sets storage path (e.g. "Firma", "Privat")
  - `created`: Optional, sets document date (format: YYYY-MM-DD)
  - Ideal for auto-tagging workflows

**Metadata management:**
- `paperless_get_tags()` / `paperless_create_tag(name, color)` / `paperless_update_tag()` / `paperless_delete_tag()` - Tags
- `paperless_get_correspondents()` / `paperless_create_correspondent(name)` / `paperless_delete_correspondent()` - Correspondents
- `paperless_get_document_types()` / `paperless_create_document_type(name)` / `paperless_delete_document_type()` - Document types
- `paperless_get_storage_paths()` / `paperless_create_storage_path(name, path)` - Storage paths
- `paperless_get_custom_fields()` - List custom fields
- `paperless_set_document_custom_field(doc_id, field_name, value)` - **Set custom field** (text, boolean, integer, float)
- `paperless_get_document_custom_field(doc_id, field_name)` - Read custom field value
- `paperless_get_saved_views()` - Saved views

**Task monitoring:**
- `paperless_get_task_status(task_id)` - **Check consumption status** (after upload)
- `paperless_acknowledge_tasks(task_ids)` - Acknowledge completed tasks

**Search:**
- `paperless_search_autocomplete(term, limit)` - Search suggestions

**Workflow: Upload and categorize document**
```python
# 1. Fetch tags and correspondents
paperless_get_tags()
paperless_get_correspondents()

# 2. Upload document
paperless_upload_document(
    file_path="rechnung.pdf",
    title="Rechnung Januar 2025",
    correspondent_id=5,
    tag_ids="1,3"
)
# → task_id: "abc123..."

# 3. Check status
paperless_get_task_status("abc123...")
```

**Workflow: Search and read documents**
```python
# Full-text search
paperless_search_documents(query="Rechnung 2025", document_type_id=3)

# Only unclassified documents (without correspondent) in time range
paperless_search_documents(correspondent_isnull=True, created_after="2025-01-01", created_before="2025-12-31")

# Read document content (OCR text)
paperless_get_document_content(doc_id=42)
```

**Workflow: Export documents as PDF**
```python
# Export with standardized name: YYYY-MM-DD-[Correspondent]-[doc_id].pdf
paperless_export_document_pdf(doc_id=42)
# → 2025-01-03-EnBW_Energie-42.pdf

paperless_export_document_pdf(doc_id=43)
# → 2025-01-03-EnBW_Energie-43.pdf

# Export to specific folder
paperless_export_document_pdf(doc_id=42, save_path="invoices/2025")
```

**Configuration in apis.json:**
```json
"paperless": {
  "enabled": true,
  "url": "http://localhost:8000",
  "token": "abc123...",
  "api_version": 5
}
```

**Get token:**
1. Call `paperless_get_token("username", "password")`
2. Enter token in `apis.json` under `paperless.token`
3. Alternatively: `username` and `password` directly in `apis.json` (less secure)

**Matching algorithms** (for auto-assignment):
| Value | Algorithm |
|-------|-----------|
| 0 | None (no auto match) |
| 1 | Any (one word) |
| 2 | All (all words) |
| 3 | Literal (exact) |
| 4 | Regex |
| 5 | Fuzzy |

## Telegram - Messaging

Telegram Bot API integration for messages, files, and interactive buttons.

**Setup:**
1. Create bot via `@BotFather` in Telegram
2. Enter bot token in `apis.json` under `telegram.bot_token`
3. Find chat ID: send a message to the bot, then call `telegram_get_updates()`

**Connection:**
- `telegram_test_connection()` - **Test connection** (shows bot name and username)

**Send messages:**
- `telegram_send_message(chat_id, text, parse_mode, disable_notification, reply_to_message_id)` - **Send text message**
  - `parse_mode`: "Markdown" (default), "MarkdownV2" or "HTML"
  - Markdown: `*bold* _italic_ `code` [Link](url)`
  - HTML: `<b>bold</b> <i>italic</i> <code>code</code> <a href="url">Link</a>`
- `telegram_send_document(chat_id, file_path, caption, parse_mode, disable_notification)` - **Send document** (PDF, DOCX, ZIP, max. 50 MB)
- `telegram_send_photo(chat_id, file_path, caption, parse_mode, disable_notification)` - **Send photo** (JPG, PNG, max. 10 MB)
- `telegram_send_message_with_keyboard(chat_id, text, buttons, parse_mode)` - **Message with inline buttons**
  - Buttons as JSON array: `[{"text": "Yes", "callback_data": "yes"}, {"text": "No", "callback_data": "no"}]`

**Manage messages:**
- `telegram_edit_message(chat_id, message_id, text, parse_mode)` - **Edit message**
- `telegram_delete_message(chat_id, message_id)` - **Delete message**

**Updates & chat info:**
- `telegram_get_updates(offset, limit)` - **Fetch new messages** (polling)
  - Returns: JSON with `update_id`, `message_id`, `from`, `chat`, `text`
- `telegram_get_chat_info(chat_id)` - **Chat information** (title, type, member count)

**Interactive buttons:**
- `telegram_answer_callback_query(callback_query_id, text, show_alert)` - **Reply to button click**

**Workflow: Send invoice via Telegram**
```python
# 1. Export invoice
billomat_download_invoice_pdf("123", ".temp", "rechnung.pdf")

# 2. Send via Telegram
telegram_send_document(
    "123456789",  # Chat ID
    ".temp/rechnung.pdf",
    caption="Ihre Rechnung RE-2025-001"
)
```

**Workflow: Interactive confirmation**
```python
# 1. Question with buttons
telegram_send_message_with_keyboard(
    "123456789",
    "Angebot erstellen?\n\n*Kunde:* Firma XY\n*Produkt:* RVP1\n*Preis:* 1.098 €",
    '[{"text": "Yes", "callback_data": "create"}, {"text": "No", "callback_data": "cancel"}]'
)

# 2. Fetch updates (extract callback_data from update)
telegram_get_updates()

# 3. React to callback
if callback_data == "create":
    billomat_create_offer(...)
    telegram_send_message("123456789", "Angebot erstellt!")
```

**Workflow: Daily check notification**
```python
# Agent sends daily summary
summary = f"""*Daily Check*

New emails: {new_count}
Follow-up: {followup_count}
Newsletters: {spam_count}

All processed!
"""

telegram_send_message("123456789", summary)
```

**Chat types:**
| Type | Chat ID format | Example |
|------|----------------|---------|
| Private chat | Positive number | `123456789` |
| Group | Negative number | `-987654321` |
| Supergroup | Negative with -100 | `-1001234567890` |
| Channel | Username or -100 | `@my_channel` or `-1001234567890` |

**Configuration in apis.json:**
```json
"telegram": {
  "enabled": true,
  "bot_token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
}
```

**Get bot token:**
1. Open Telegram → search for `@BotFather`
2. Send `/newbot` → choose name and username
3. Copy bot token → enter into `apis.json`

**Find chat ID:**
1. Send message to bot (e.g. `/start`)
2. Call `telegram_get_updates()`
3. `chat.id` from response is your chat ID

**Limits:**
- Text: 4,096 characters
- Caption: 1,024 characters
- Photo: 10 MB
- Document: 50 MB
- Requests: 30/second

**Full documentation:** [docs/telegram-mcp-setup.md](../docs/telegram-mcp-setup.md)

---

## Plugin MCPs

Plugin MCPs are detected and loaded automatically. Two directory structures are supported:

### Directory Structure

**Flat structure (recommended):** One MCP per plugin, directly in `mcp/`.
```
plugins/sap/
├── plugin.json
└── mcp/
    └── __init__.py    # -> server_name = "sap:sap"
```

**Nested structure:** Multiple MCPs per plugin in subfolders.
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
- Flat: `{plugin_name}:{plugin_name}` (e.g. `sap:sap`, `myplugin:myplugin`)
- Nested: `{plugin_name}:{mcp_folder_name}` (e.g. `myplugin:api_server`)
- Tool names: As defined in the plugin (without prefix)

### Discovery Flow
```
discover_plugins() -> mcp_count (flat + nested)
    -> has_mcp = True
        -> get_plugin_mcp_dirs()
            -> discover_mcp_servers() Method 3
                -> Flat:   mcp/__init__.py -> "plugin:plugin"
                -> Nested: mcp/name/__init__.py -> "plugin:name"
```

**Use in allowed_mcp:**
```yaml
---
{
  "allowed_mcp": "sap|outlook|billomat"  # Plugin name directly
}
---
```

**Available plugin MCPs:**
- `sap` - SAP S/4HANA Cloud API (business partner, sales orders, etc.)

**More details:** see [doc-pluginsystem.md](doc-pluginsystem.md)
