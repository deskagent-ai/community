# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Email Auto-Watcher
==================
Background email monitoring for Gmail, Office 365 (MS Graph), and IMAP.
Matches emails against regex patterns and triggers AI agents to auto-respond.

Supports:
- Gmail (via gmail_mcp)
- Office 365 (via msgraph_mcp)
- IMAP (via imap_mcp) - any IMAP server with custom flags support
- Regex matching on from, subject, to, body
- Agent triggering with auto_send option
"""

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Path is set up by assistant/__init__.py
from paths import get_data_dir, PROJECT_DIR

# Import system_log for background logging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): pass


# =============================================================================
# Configuration
# =============================================================================

def _load_triggers_config() -> dict:
    """Load triggers.json config (Object structure)."""
    config_file = PROJECT_DIR / "config" / "triggers.json"
    if config_file.exists():
        try:
            return json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            system_log(f"[EmailWatcher] Error loading triggers.json: {e}")
    return {}


def _get_current_hostname() -> str:
    """Get current computer hostname (lowercase for comparison)."""
    import socket
    return socket.gethostname().lower()


def _get_email_watcher_configs() -> List[dict]:
    """Get all email_watcher triggers from config.

    Supports Object structure where trigger_id is the key:
    {
        "gmail_support": {"type": "email_watcher", ...},
        "msgraph_invoices": {"type": "email_watcher", ...}
    }

    Hostname filtering: If a trigger has "hostname" field, it only runs
    on matching computer. This prevents duplicate processing when
    DeskAgent runs on multiple machines with shared config.
    """
    config = _load_triggers_config()
    watchers = []
    current_host = _get_current_hostname()

    for trigger_id, trigger_config in config.items():
        # Skip comment keys
        if trigger_id.startswith("_"):
            continue

        # Only email_watcher type
        if trigger_config.get("type") != "email_watcher":
            continue

        # Hostname filter: skip if configured for different host
        required_host = trigger_config.get("hostname", "").lower()
        if required_host and required_host != current_host:
            system_log(f"[EmailWatcher] Skipping {trigger_id}: hostname mismatch ({required_host} != {current_host})")
            continue

        # Add ID from key to the config
        trigger_config["id"] = trigger_id
        watchers.append(trigger_config)

    return watchers


# =============================================================================
# State Management (per watcher instance)
# =============================================================================

@dataclass
class WatcherState:
    """State for a single email watcher instance.

    Note: For Gmail, we use labels (IsDone) as the single source of truth.
    in_progress_ids only prevents race conditions during processing.
    """
    watcher_id: str
    provider: str
    in_progress_ids: List[str]  # Only emails currently being processed (race condition prevention)
    processed_count: int
    last_check: Optional[str]
    actions_log: List[dict]
    errors: List[dict]
    stats_by_date: Dict[str, dict]

    @classmethod
    def default(cls, watcher_id: str, provider: str) -> "WatcherState":
        return cls(
            watcher_id=watcher_id,
            provider=provider,
            in_progress_ids=[],
            processed_count=0,
            last_check=None,
            actions_log=[],
            errors=[],
            stats_by_date={}
        )

    def to_dict(self) -> dict:
        return {
            "watcher_id": self.watcher_id,
            "provider": self.provider,
            "in_progress_ids": self.in_progress_ids,
            "processed_count": self.processed_count,
            "last_check": self.last_check,
            "actions_log": self.actions_log,
            "errors": self.errors,
            "stats_by_date": self.stats_by_date
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WatcherState":
        # Migration: Support old seen_email_ids for backwards compatibility
        in_progress = data.get("in_progress_ids", [])
        # Don't migrate seen_email_ids - labels are now the source of truth

        return cls(
            watcher_id=data.get("watcher_id", "unknown"),
            provider=data.get("provider", "unknown"),
            in_progress_ids=in_progress,
            processed_count=data.get("processed_count", 0),
            last_check=data.get("last_check"),
            actions_log=data.get("actions_log", []),
            errors=data.get("errors", []),
            stats_by_date=data.get("stats_by_date", {})
        )


def _get_state_file(watcher_id: str) -> Path:
    """Get state file path for a watcher."""
    return get_data_dir() / f"email_watcher_{watcher_id}_state.json"


def _load_state(watcher_id: str, provider: str) -> WatcherState:
    """Load watcher state from file."""
    state_file = _get_state_file(watcher_id)
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return WatcherState.from_dict(data)
        except (json.JSONDecodeError, IOError):
            pass
    return WatcherState.default(watcher_id, provider)


def _save_state(state: WatcherState):
    """Save watcher state to file."""
    state_file = _get_state_file(state.watcher_id)
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except IOError as e:
        system_log(f"[EmailWatcher] Error saving state: {e}")


# =============================================================================
# Email Fetching (via tool_bridge)
# =============================================================================

def _execute_tool(tool_name: str, params: dict, mcp_filter: str = None) -> Optional[str]:
    """Execute MCP tool via tool_bridge with isolated TaskContext.

    Note: skip_logging=True to prevent anon_messages.log bloat from polling.

    Uses TaskContext isolation to prevent MCP filter collision with
    concurrent agents. Each watcher call gets its own context that
    doesn't interfere with running agents.

    Args:
        tool_name: Name of the MCP tool to execute
        params: Tool parameters
        mcp_filter: Optional MCP filter to ensure correct provider is loaded
                    (e.g., "gmail" for gmail tools, "msgraph" for MS Graph tools)
    """
    try:
        from ai_agent.tool_bridge import execute_tool, set_mcp_filter
        from ai_agent.task_context import TaskContext, set_task_context, clear_task_context

        # Create isolated TaskContext for this watcher call
        # This prevents filter collision with concurrent agents
        ctx = TaskContext(
            task_id=f"watcher-{int(time.time() * 1000)}",
            mcp_filter=mcp_filter
        )
        set_task_context(ctx)

        try:
            return execute_tool(tool_name, params, skip_logging=True)
        finally:
            # Always clear context to avoid leaking state
            clear_task_context()

    except ImportError:
        try:
            import sys
            sys.path.insert(0, str(PROJECT_DIR / "scripts"))
            from ai_agent.tool_bridge import execute_tool, set_mcp_filter
            from ai_agent.task_context import TaskContext, set_task_context, clear_task_context

            # Create isolated TaskContext for this watcher call
            ctx = TaskContext(
                task_id=f"watcher-{int(time.time() * 1000)}",
                mcp_filter=mcp_filter
            )
            set_task_context(ctx)

            try:
                return execute_tool(tool_name, params, skip_logging=True)
            finally:
                clear_task_context()

        except Exception as e:
            system_log(f"[EmailWatcher] Tool bridge import error: {e}")
            return None
    except Exception as e:
        import traceback
        system_log(f"[EmailWatcher] Tool execution error: {e}")
        system_log(f"[EmailWatcher] Traceback:\n{traceback.format_exc()}")
        return None


def _get_emails(config: dict) -> List[dict]:
    """Get recent emails based on provider config.

    For Gmail: Uses -label:IsDone -label:InProgress to filter out processed/in-progress emails.
    Note: "Ask" label is permanent (marks support requests) and NOT filtered out.
    Labels are the single source of truth for tracking.
    """
    provider = config.get("provider", "gmail")
    days = config.get("lookback_days", 1)
    limit = config.get("max_emails_per_check", 50)

    # Get labels from config
    labels = config.get("labels", {})
    done_label = labels.get("done", "IsDone")
    inprogress_label = labels.get("inprogress", "InProgress")

    result = None

    if provider == "gmail":
        # Exclude done AND inprogress labels (Ask is permanent, not filtered)
        exclude = f"{done_label},{inprogress_label}"
        result = _execute_tool("gmail_get_recent_emails", {
            "days": days,
            "limit": limit,
            "exclude_labels": exclude  # Server-side filtering!
        }, mcp_filter="gmail")
    elif provider == "msgraph":
        # Exclude done AND inprogress categories
        exclude = f"{done_label},{inprogress_label}"
        params = {
            "days": days,
            "limit": limit,
            "exclude_categories": exclude  # Server-side filtering!
        }
        mailbox = config.get("mailbox")
        if mailbox:
            params["mailbox"] = mailbox
        result = _execute_tool("graph_get_recent_emails", params, mcp_filter="msgraph")
    elif provider == "imap":
        # IMAP uses custom keywords (flags) for workflow tracking
        # Build search criteria to exclude done and inprogress
        folder = config.get("folder", "INBOX")
        # Calculate SINCE date for days filter
        from datetime import timedelta
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        # IMAP search: SINCE date NOT KEYWORD IsDone NOT KEYWORD InProgress
        search_criteria = f"SINCE {since_date} NOT KEYWORD {done_label} NOT KEYWORD {inprogress_label}"
        result = _execute_tool("imap_search_emails", {
            "folder": folder,
            "search_criteria": search_criteria,
            "limit": limit
        }, mcp_filter="imap")
    else:
        system_log(f"[EmailWatcher] Unknown provider: {provider}")
        return []

    if not result:
        return []

    # Check for ERROR prefix (MCP tools return "ERROR: ..." on failure)
    if isinstance(result, str) and result.startswith("ERROR:"):
        system_log(f"[EmailWatcher] MCP tool error: {result}")
        return []

    try:
        data = json.loads(result)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "error" in data:
            system_log(f"[EmailWatcher] API error: {data['error']}")
            return []
        return []
    except json.JSONDecodeError as e:
        # Log truncated result for debugging (first 200 chars)
        result_preview = result[:200] if result else "(empty)"
        system_log(f"[EmailWatcher] Failed to parse emails JSON: {e}")
        system_log(f"[EmailWatcher] Response preview: {result_preview}")
        return []


def _get_email_content(provider: str, message_id: str, mailbox: Optional[str] = None, folder: str = "INBOX") -> Optional[str]:
    """Get full email content."""
    if provider == "gmail":
        result = _execute_tool("gmail_get_email", {"message_id": message_id}, mcp_filter="gmail")
    elif provider == "msgraph":
        params = {"message_id": message_id}
        if mailbox:
            params["mailbox"] = mailbox
        result = _execute_tool("graph_get_email", params, mcp_filter="msgraph")
    elif provider == "imap":
        # IMAP uses uid instead of message_id
        result = _execute_tool("imap_get_email", {"uid": message_id, "folder": folder}, mcp_filter="imap")
    else:
        return None
    return result


# =============================================================================
# Rule Matching
# =============================================================================

def _extract_email_address(sender: str) -> str:
    """Extract email address from 'Name <email@example.com>' format."""
    match = re.search(r'<([^>]+)>', sender)
    if match:
        return match.group(1).lower()
    return sender.lower().strip()


def _match_rule(email: dict, rule: dict) -> bool:
    """Check if email matches rule patterns."""
    match_config = rule.get("match", {})

    # from_pattern - check sender
    from_pattern = match_config.get("from_pattern")
    if from_pattern:
        sender = email.get("from", "") or email.get("sender", "") or ""
        if not re.search(from_pattern, sender, re.IGNORECASE):
            return False

    # subject_pattern - check subject
    subject_pattern = match_config.get("subject_pattern")
    if subject_pattern:
        subject = email.get("subject", "") or ""
        if not re.search(subject_pattern, subject, re.IGNORECASE):
            return False

    # to_pattern - check recipients (NEW)
    to_pattern = match_config.get("to_pattern")
    if to_pattern:
        # Check both 'to' and 'recipients' fields
        recipients = email.get("to", "") or ""
        if isinstance(recipients, list):
            recipients = ", ".join(recipients)
        if not re.search(to_pattern, recipients, re.IGNORECASE):
            return False

    # body_pattern - check body preview (optional, expensive)
    body_pattern = match_config.get("body_pattern")
    if body_pattern:
        body = email.get("snippet", "") or email.get("body_preview", "") or ""
        if not re.search(body_pattern, body, re.IGNORECASE):
            return False

    return True


# =============================================================================
# Action Execution
# =============================================================================

def _create_reply_draft(provider: str, message_id: str, body: str,
                        reply_all: bool = True, mailbox: Optional[str] = None) -> Optional[str]:
    """Create reply draft."""
    if provider == "gmail":
        result = _execute_tool("gmail_create_reply_draft", {
            "message_id": message_id,
            "body": body,
            "reply_all": reply_all
        }, mcp_filter="gmail")
    elif provider == "msgraph":
        params = {
            "message_id": message_id,
            "body": body,
            "reply_all": reply_all
        }
        if mailbox:
            params["mailbox"] = mailbox
        result = _execute_tool("graph_create_reply_draft", params, mcp_filter="msgraph")
    else:
        return None
    return result


def _send_draft(provider: str, draft_id: str) -> bool:
    """Send a draft."""
    if provider == "gmail":
        result = _execute_tool("gmail_send_draft", {"draft_id": draft_id}, mcp_filter="gmail")
        return result and "sent" in result.lower()
    elif provider == "msgraph":
        # MS Graph drafts are sent differently - need to check the API
        # For now, return False as MS Graph create_reply_draft might work differently
        system_log("[EmailWatcher] MS Graph auto-send not yet implemented")
        return False
    return False


def _mark_as_read(provider: str, message_id: str, mailbox: Optional[str] = None, folder: str = "INBOX") -> bool:
    """Mark email as read."""
    if provider == "gmail":
        result = _execute_tool("gmail_mark_read", {
            "message_id": message_id,
            "is_read": True
        }, mcp_filter="gmail")
        return result is not None
    elif provider == "msgraph":
        params = {"message_id": message_id, "is_read": True}
        if mailbox:
            params["mailbox"] = mailbox
        result = _execute_tool("graph_mark_read", params, mcp_filter="msgraph")
        return result is not None
    elif provider == "imap":
        # IMAP uses \\Seen flag to mark as read
        result = _execute_tool("imap_set_flag", {
            "uid": message_id,
            "flag": "\\Seen",
            "folder": folder
        }, mcp_filter="imap")
        return result is not None and "Success" in str(result)
    return False


def _add_label(provider: str, message_id: str, label: str, mailbox: Optional[str] = None, folder: str = "INBOX") -> bool:
    """Add a label/category/custom flag to an email."""
    if provider == "gmail":
        result = _execute_tool("gmail_add_label", {
            "message_id": message_id,
            "label": label
        }, mcp_filter="gmail")
        return result is not None and "ERROR" not in str(result)
    elif provider == "msgraph":
        params = {"message_id": message_id, "category": label}
        if mailbox:
            params["mailbox"] = mailbox
        result = _execute_tool("graph_add_category", params, mcp_filter="msgraph")
        return result is not None and "ERROR" not in str(result)
    elif provider == "imap":
        # IMAP uses custom keywords (flags) for labels
        result = _execute_tool("imap_set_custom_flag", {
            "uid": message_id,
            "keyword": label,
            "folder": folder
        }, mcp_filter="imap")
        return result is not None and "Success" in str(result)
    return False


def _remove_label(provider: str, message_id: str, label: str, mailbox: Optional[str] = None, folder: str = "INBOX") -> bool:
    """Remove a label/category/custom flag from an email."""
    if provider == "gmail":
        result = _execute_tool("gmail_remove_label", {
            "message_id": message_id,
            "label": label
        }, mcp_filter="gmail")
        return result is not None and "ERROR" not in str(result)
    elif provider == "msgraph":
        params = {"message_id": message_id, "category": label}
        if mailbox:
            params["mailbox"] = mailbox
        result = _execute_tool("graph_remove_category", params, mcp_filter="msgraph")
        return result is not None and "ERROR" not in str(result)
    elif provider == "imap":
        # IMAP uses custom keywords (flags) for labels
        result = _execute_tool("imap_remove_custom_flag", {
            "uid": message_id,
            "keyword": label,
            "folder": folder
        }, mcp_filter="imap")
        return result is not None and "Success" in str(result)
    return False


def _get_emails_by_label(provider: str, label: str, limit: int = 100, mailbox: Optional[str] = None, folder: str = "INBOX") -> List[dict]:
    """Get emails with a specific label/category/custom flag."""
    result = None

    if provider == "gmail":
        result = _execute_tool("gmail_get_emails_by_label", {
            "label": label,
            "limit": limit
        }, mcp_filter="gmail")
    elif provider == "msgraph":
        params = {"category": label, "limit": limit}
        if mailbox:
            params["mailbox"] = mailbox
        result = _execute_tool("graph_get_emails_by_category", params, mcp_filter="msgraph")
    elif provider == "imap":
        # IMAP uses KEYWORD search for custom flags
        result = _execute_tool("imap_search_by_custom_flag", {
            "keyword": label,
            "folder": folder,
            "limit": limit
        }, mcp_filter="imap")

    if not result:
        return []

    try:
        data = json.loads(result)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _execute_action(email: dict, action: dict, config: dict, state: WatcherState) -> str:
    """Execute a single action on an email."""
    action_type = action.get("type")
    provider = config.get("provider", "gmail")
    mailbox = config.get("mailbox")
    folder = config.get("folder", "INBOX")  # For IMAP

    subject = email.get("subject", "")[:50]
    sender = email.get("from", "") or email.get("sender", "")
    # IMAP uses "uid", Gmail/msgraph use "id" or "message_id"
    message_id = email.get("uid") or email.get("id") or email.get("message_id")

    if action_type == "trigger_workflow":
        # Use workflow system instead of direct agent call
        workflow_id = action.get("workflow", "email_reply")

        # Get labels from config
        labels = config.get("labels", {})

        # Extract sender email
        sender_email = _extract_email_address(sender)

        # Get full email content
        body = ""
        if action.get("include_body", True):
            full_content = _get_email_content(provider, message_id, mailbox, folder)
            if full_content:
                # Parse JSON content if needed
                try:
                    content_data = json.loads(full_content)
                    body = content_data.get("body", "") or content_data.get("snippet", "")
                except (json.JSONDecodeError, TypeError):
                    body = full_content[:4000]

        # Import workflow manager (try multiple paths for different run contexts)
        workflow_manager = None
        import_errors = []

        # Try 1: Absolute import (preferred for Nuitka)
        try:
            from workflows import manager as workflow_manager
        except ImportError as e:
            import_errors.append(f"absolute: {e}")

        # Try 2: Absolute from scripts (if scripts is in path)
        if workflow_manager is None:
            try:
                from scripts.workflows import manager as workflow_manager
            except ImportError as e:
                import_errors.append(f"scripts.*: {e}")

        # Try 3: Direct workflows import (if workflows is in path)
        if workflow_manager is None:
            try:
                from workflows import manager as workflow_manager
            except ImportError as e:
                import_errors.append(f"direct: {e}")

        if workflow_manager is None:
            system_log(f"[EmailWatcher] ERROR: Could not import workflows: {import_errors}")
            return f"Error: Could not import workflows module"

        system_log(f"[EmailWatcher] Workflow manager imported successfully")

        # Discover workflows if not already done
        workflow_manager.discover()

        # Build workflow inputs
        workflow_inputs = {
            "uid": message_id,  # IMAP UID or email ID
            "message_id": message_id,
            "sender": sender,
            "sender_email": sender_email,
            "subject": subject,
            "body": body,
            "pending_label": labels.get("pending", "Ask"),
            "inprogress_label": labels.get("inprogress", "InProgress"),
            "done_label": labels.get("done", "IsDone"),
            "spam_label": labels.get("spam", "AskSpam"),
            # Provider info for multi-provider support
            "provider": provider,
            "folder": folder,  # For IMAP
            "mailbox": mailbox,  # For msgraph
        }

        def run_workflow():
            system_log(f"[EmailWatcher] run_workflow() thread started for {workflow_id}")
            try:
                system_log(f"[EmailWatcher] Calling workflow_manager.start({workflow_id})")
                run_id = workflow_manager.start(workflow_id, **workflow_inputs)
                system_log(f"[EmailWatcher] Workflow {workflow_id} started: {run_id[:8]}... for: {subject}")

                _log_action(state, subject, sender, "trigger_workflow",
                           {"workflow": workflow_id}, "started")

            except Exception as e:
                _log_error(state, f"Workflow {workflow_id} failed: {e}")
            finally:
                if message_id in state.in_progress_ids:
                    state.in_progress_ids.remove(message_id)
                    _save_state(state)

        # Run workflow in background thread
        system_log(f"[EmailWatcher] Starting workflow thread for {workflow_id}")
        threading.Thread(target=run_workflow, daemon=True).start()
        system_log(f"[EmailWatcher] Workflow thread started")

        return {"status": "async", "message": f"Workflow {workflow_id} triggered"}

    else:
        return f"Unknown action type: {action_type}"


def _log_action(state: WatcherState, subject: str, sender: str,
                action: str, params: dict, result: str):
    """Log an action to state."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "time": datetime.now().strftime("%H:%M:%S"),
        "email": subject[:50],
        "from": sender,
        "action": action,
        "params": params,
        "result": result
    }

    state.actions_log.insert(0, entry)
    state.actions_log = state.actions_log[:100]  # Keep last 100

    # Update daily stats
    today = datetime.now().strftime("%Y-%m-%d")
    if today not in state.stats_by_date:
        state.stats_by_date[today] = {"processed": 0, "actions": 0, "by_action": {}}
    state.stats_by_date[today]["actions"] += 1
    by_action = state.stats_by_date[today].setdefault("by_action", {})
    by_action[action] = by_action.get(action, 0) + 1

    _save_state(state)


def _log_error(state: WatcherState, error: str):
    """Log an error to state."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "error": error
    }
    state.errors.insert(0, entry)
    state.errors = state.errors[:20]  # Keep last 20
    _save_state(state)
    system_log(f"[EmailWatcher] Error: {error}")


# =============================================================================
# Watcher Instance
# =============================================================================

class EmailWatcherInstance:
    """A single email watcher instance for one trigger config."""

    def __init__(self, config: dict):
        self.config = config
        self.watcher_id = config.get("id", "unknown")
        self.provider = config.get("provider", "gmail")
        self.state = _load_state(self.watcher_id, self.provider)
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None
        self._lock = threading.Lock()

        # Auto-cleanup: Clear orphaned in_progress_ids on startup
        # These are only for race condition prevention during active processing
        # Gmail labels (IsDone/Ask) are the source of truth, not in_progress_ids
        if self.state.in_progress_ids:
            orphan_count = len(self.state.in_progress_ids)
            self.state.in_progress_ids = []
            _save_state(self.state)
            system_log(f"[EmailWatcher] Cleared {orphan_count} orphaned in-progress IDs on startup: {self.watcher_id}")

        # Recover stuck emails: emails with "InProgress" label but NOT "IsDone" label
        # This can happen if DeskAgent crashes during processing
        # Note: "Ask" label is permanent and never removed
        self._recover_stuck_emails()

    def _recover_stuck_emails(self):
        """Recover emails stuck with InProgress label but no IsDone label.

        This handles the case where DeskAgent crashed after adding the "InProgress"
        label but before adding the "IsDone" label. Without recovery, these emails
        would be permanently excluded by the filter 'exclude_labels: IsDone,InProgress'.

        IMPORTANT: The "Ask" label is NEVER removed - it permanently marks support requests.
        Only the temporary "InProgress" label is removed to allow reprocessing.

        Recovery: Find emails with "InProgress" but NOT "IsDone", then remove "InProgress"
        label so they get reprocessed on the next poll cycle.

        Supports: Gmail, IMAP (msgraph recovery not implemented)
        """
        # Get labels from config
        labels = self.config.get("labels", {})
        inprogress_label = labels.get("inprogress", "InProgress")
        done_label = labels.get("done", "IsDone")
        folder = self.config.get("folder", "INBOX")

        try:
            if self.provider == "gmail":
                self._recover_stuck_emails_gmail(inprogress_label, done_label)
            elif self.provider == "imap":
                self._recover_stuck_emails_imap(inprogress_label, done_label, folder)
            # msgraph: recovery not implemented (categories work differently)

        except json.JSONDecodeError as e:
            system_log(f"[EmailWatcher] Error parsing emails during recovery: {e}")
        except Exception as e:
            # Don't crash on recovery failure - just log and continue
            system_log(f"[EmailWatcher] Error during stuck email recovery: {e}")

    def _recover_stuck_emails_gmail(self, inprogress_label: str, done_label: str):
        """Recover stuck emails for Gmail provider."""
        # Step 1: Get all emails with the InProgress label
        result = _execute_tool("gmail_get_emails_by_label", {
            "label": inprogress_label,
            "limit": 100
        }, mcp_filter="gmail")

        if not result:
            return

        emails_with_inprogress = json.loads(result)
        if not isinstance(emails_with_inprogress, list) or not emails_with_inprogress:
            return

        # Step 2: Filter to find stuck emails (have InProgress but NOT IsDone)
        stuck_emails = []
        for email in emails_with_inprogress:
            email_labels = email.get("labels", [])
            # Check if done label is NOT present
            # Labels can be IDs (Label_xxx) or names, need to check both
            has_done = False
            for lbl in email_labels:
                if lbl.lower() == done_label.lower() or done_label.lower() in lbl.lower():
                    has_done = True
                    break
            if not has_done:
                stuck_emails.append(email)

        if not stuck_emails:
            return

        # Step 3: Remove InProgress label from stuck emails (Ask label stays!)
        system_log(f"[EmailWatcher] Recovering {len(stuck_emails)} stuck email(s) for {self.watcher_id}")

        recovered_count = 0
        for email in stuck_emails:
            message_id = email.get("id")
            subject = email.get("subject", "")[:40]
            if not message_id:
                continue

            try:
                result = _execute_tool("gmail_remove_label", {
                    "message_id": message_id,
                    "label": inprogress_label  # Only remove InProgress, NOT Ask!
                }, mcp_filter="gmail")
                if result and "ERROR" not in result:
                    recovered_count += 1
                    system_log(f"[EmailWatcher] Recovered stuck email: {subject}")
                else:
                    system_log(f"[EmailWatcher] Failed to recover email {message_id}: {result}")
            except Exception as e:
                system_log(f"[EmailWatcher] Error recovering email {message_id}: {e}")

        if recovered_count > 0:
            system_log(f"[EmailWatcher] Successfully recovered {recovered_count} stuck email(s) for {self.watcher_id}")

    def _recover_stuck_emails_imap(self, inprogress_label: str, done_label: str, folder: str):
        """Recover stuck emails for IMAP provider.

        IMAP uses custom keywords (flags) instead of labels.
        Search for: KEYWORD InProgress NOT KEYWORD IsDone
        """
        # Step 1: Search for emails with InProgress but NOT IsDone
        # IMAP search criteria: KEYWORD InProgress NOT KEYWORD IsDone
        search_criteria = f"KEYWORD {inprogress_label} NOT KEYWORD {done_label}"
        result = _execute_tool("imap_search_emails", {
            "folder": folder,
            "search_criteria": search_criteria,
            "limit": 100
        }, mcp_filter="imap")

        if not result:
            return

        stuck_emails = json.loads(result)
        if not isinstance(stuck_emails, list) or not stuck_emails:
            return

        # Step 2: Remove InProgress flag from stuck emails
        system_log(f"[EmailWatcher] Recovering {len(stuck_emails)} stuck email(s) for {self.watcher_id}")

        recovered_count = 0
        for email in stuck_emails:
            uid = email.get("uid")
            subject = email.get("subject", "")[:40]
            if not uid:
                continue

            try:
                result = _execute_tool("imap_remove_custom_flag", {
                    "uid": uid,
                    "keyword": inprogress_label,
                    "folder": folder
                }, mcp_filter="imap")
                if result and "Success" in str(result):
                    recovered_count += 1
                    system_log(f"[EmailWatcher] Recovered stuck email: {subject}")
                else:
                    system_log(f"[EmailWatcher] Failed to recover email UID {uid}: {result}")
            except Exception as e:
                system_log(f"[EmailWatcher] Error recovering email UID {uid}: {e}")

        if recovered_count > 0:
            system_log(f"[EmailWatcher] Successfully recovered {recovered_count} stuck email(s) for {self.watcher_id}")

    def start(self) -> bool:
        """Start the watcher thread."""
        if self._thread and self._thread.is_alive():
            return False

        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._watcher_loop,
            daemon=True,
            name=f"EmailWatcher-{self.watcher_id}"
        )
        self._thread.start()
        system_log(f"[EmailWatcher] Started: {self.watcher_id} ({self.provider})")
        return True

    def stop(self) -> bool:
        """Stop the watcher thread."""
        if self._stop_event:
            self._stop_event.set()
            system_log(f"[EmailWatcher] Stop signal sent: {self.watcher_id}")
            return True
        return False

    def is_running(self) -> bool:
        """Check if watcher is running."""
        return self._thread is not None and self._thread.is_alive()

    def check_now(self) -> dict:
        """Force immediate check."""
        try:
            self._check_emails()
            return {"status": "ok", "message": "Check completed"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def clear_in_progress(self):
        """Clear in-progress email IDs (for recovery/testing)."""
        with self._lock:
            self.state.in_progress_ids = []
            _save_state(self.state)
        system_log(f"[EmailWatcher] Cleared in-progress emails: {self.watcher_id}")

    def get_status(self) -> dict:
        """Get watcher status."""
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = self.state.stats_by_date.get(today, {
            "processed": 0, "actions": 0, "by_action": {}
        })

        # Calculate next check time
        next_check_in = None
        if self.state.last_check and self.is_running():
            try:
                last = datetime.fromisoformat(self.state.last_check)
                interval = self.config.get("poll_interval", 60)
                elapsed = (datetime.now() - last).total_seconds()
                next_check_in = max(0, int(interval - elapsed))
            except (ValueError, TypeError):
                pass

        return {
            "id": self.watcher_id,
            "name": self.config.get("name", self.watcher_id),
            "provider": self.provider,
            "enabled": self.config.get("enabled", False),
            "running": self.is_running(),
            "last_check": self.state.last_check,
            "next_check_in": next_check_in,
            "poll_interval": self.config.get("poll_interval", 60),
            "stats": {
                "processed_today": today_stats.get("processed", 0),
                "actions_today": today_stats.get("actions", 0),
                "total_processed": self.state.processed_count,
                "by_action": today_stats.get("by_action", {})
            },
            "recent_actions": self.state.actions_log[:10],
            "rules_count": len(self.config.get("rules", [])),
            "errors": self.state.errors[:5]
        }

    def _watcher_loop(self):
        """Main watcher loop."""
        system_log(f"[EmailWatcher] Thread started: {self.watcher_id}")

        while not self._stop_event.is_set():
            interval = self.config.get("poll_interval", 60)

            if self.config.get("enabled", False):
                try:
                    self._check_emails()
                except Exception as e:
                    _log_error(self.state, str(e))

            # Interruptible sleep
            self._stop_event.wait(timeout=interval)

        system_log(f"[EmailWatcher] Thread stopped: {self.watcher_id}")

    def _check_emails(self):
        """Check for new emails and apply rules.

        For Gmail: Emails without IsDone label are returned by the server.
        in_progress_ids only prevents race conditions during processing.
        """
        with self._lock:
            self.state.last_check = datetime.now().isoformat()
            _save_state(self.state)

        rules = self.config.get("rules", [])
        if not rules:
            return

        # Get recent emails (Gmail: already filtered by -label:IsDone)
        emails = _get_emails(self.config)
        system_log(f"[EmailWatcher] Got {len(emails) if emails else 0} emails from provider")
        if not emails:
            return

        # Process each email
        for email in emails:
            # IMAP uses "uid", Gmail/msgraph use "id" or "message_id"
            email_id = email.get("uid") or email.get("id") or email.get("message_id")
            system_log(f"[EmailWatcher] Processing: {str(email_id)[:20]} - {email.get('subject', 'no-subject')[:30]}")
            if not email_id:
                continue

            # Skip if currently being processed (race condition prevention)
            if email_id in self.state.in_progress_ids:
                continue

            # Mark as in-progress BEFORE processing
            with self._lock:
                self.state.in_progress_ids.append(email_id)
                _save_state(self.state)

            # Check against rules
            matched = False
            has_async_action = False
            for rule in rules:
                if not rule.get("enabled", True):
                    continue

                if _match_rule(email, rule):
                    matched = True
                    rule_name = rule.get("name", "Unknown")
                    system_log(f"[EmailWatcher] Rule '{rule_name}' matched: {email.get('subject', '')[:40]}")

                    # Execute all actions for this rule
                    for action in rule.get("actions", []):
                        try:
                            result = _execute_action(email, action, self.config, self.state)
                            # Check if action is async (runs in background thread)
                            if isinstance(result, dict) and result.get("status") == "async":
                                has_async_action = True
                        except Exception as e:
                            _log_error(self.state, f"Action failed: {action.get('type')} - {e}")

                    # Stop checking rules after first match
                    break

            # Update stats and remove from in_progress
            with self._lock:
                # Only remove from in_progress for sync actions
                # Async actions (trigger_agent) handle their own cleanup in the background thread
                if not has_async_action and email_id in self.state.in_progress_ids:
                    self.state.in_progress_ids.remove(email_id)

                if matched:
                    self.state.processed_count += 1

                    # Update daily stats
                    today = datetime.now().strftime("%Y-%m-%d")
                    if today not in self.state.stats_by_date:
                        self.state.stats_by_date[today] = {"processed": 0, "actions": 0, "by_action": {}}
                    self.state.stats_by_date[today]["processed"] += 1

                _save_state(self.state)

        # Mark processed emails as read if configured
        if self.config.get("mark_processed_as_read", False):
            folder = self.config.get("folder", "INBOX")
            for email in emails:
                # IMAP uses "uid", Gmail/msgraph use "id" or "message_id"
                email_id = email.get("uid") or email.get("id") or email.get("message_id")
                if email_id and email.get("is_unread", True):
                    _mark_as_read(self.provider, email_id, self.config.get("mailbox"), folder)


# =============================================================================
# Global Watcher Manager
# =============================================================================

_watchers: Dict[str, EmailWatcherInstance] = {}
_manager_lock = threading.Lock()


def start_all_watchers() -> int:
    """Start all enabled email watchers. Returns count of started watchers."""
    global _watchers

    configs = _get_email_watcher_configs()
    started = 0

    with _manager_lock:
        for config in configs:
            watcher_id = config.get("id")
            if not watcher_id:
                continue

            if not config.get("enabled", False):
                continue

            # Create new instance if not exists
            if watcher_id not in _watchers:
                _watchers[watcher_id] = EmailWatcherInstance(config)

            # Start if not running
            if not _watchers[watcher_id].is_running():
                if _watchers[watcher_id].start():
                    started += 1

    return started


def stop_all_watchers() -> int:
    """Stop all running email watchers. Returns count of stopped watchers."""
    stopped = 0

    with _manager_lock:
        for watcher in _watchers.values():
            if watcher.is_running():
                if watcher.stop():
                    stopped += 1

    return stopped


def reload_config():
    """Reload configuration and restart watchers."""
    stop_all_watchers()

    # Clear instances to force reload
    with _manager_lock:
        _watchers.clear()

    # Give threads time to stop
    time.sleep(1)

    return start_all_watchers()


def get_watcher(watcher_id: str) -> Optional[EmailWatcherInstance]:
    """Get a specific watcher instance."""
    with _manager_lock:
        return _watchers.get(watcher_id)


def get_all_statuses() -> List[dict]:
    """Get status of all watchers."""
    configs = _get_email_watcher_configs()
    statuses = []

    with _manager_lock:
        for config in configs:
            watcher_id = config.get("id")
            if not watcher_id:
                continue

            if watcher_id in _watchers:
                statuses.append(_watchers[watcher_id].get_status())
            else:
                # Return config-only status for non-running watchers
                statuses.append({
                    "id": watcher_id,
                    "name": config.get("name", watcher_id),
                    "provider": config.get("provider", "unknown"),
                    "enabled": config.get("enabled", False),
                    "running": False,
                    "last_check": None,
                    "poll_interval": config.get("poll_interval", 60),
                    "rules_count": len(config.get("rules", []))
                })

    return statuses


def is_any_enabled() -> bool:
    """Check if any email watcher is enabled."""
    configs = _get_email_watcher_configs()
    return any(c.get("enabled", False) for c in configs)
