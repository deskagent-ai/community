"""
Email Auto-Reply Workflow
=========================
Process support emails: check blocklist, generate AI reply, send, archive.

Folder flow: INBOX → InProcess → Done (or Spam if blocked)
"""

import json

from workflows import Workflow, step
from email_utils import (
    build_reply_body,
    build_reply_subject,
    build_email_context,
    build_email_prompt,
    format_email_log,
    truncate_for_log,
)


class EmailReplyWorkflow(Workflow):
    """Auto-reply to support emails via IMAP/SMTP."""

    name = "Email Auto-Reply"
    icon = "envelope"
    category = "email"
    description = "Process support emails: check blocklist, generate reply, send"
    allowed_mcp = ["imap", "smtp", "desk", "db"]

    # Folders (override via inputs)
    INBOX = "INBOX"
    INPROCESS = "InProcess"
    DONE = "Done"
    SPAM = "Spam"

    @step
    def start_processing(self):
        """Log input and move to InProcess."""
        self.log(format_email_log(
            self.uid,
            getattr(self, "sender", ""),
            getattr(self, "sender_email", ""),
            getattr(self, "subject", ""),
            getattr(self, "body", "")
        ))
        result = self.tool.imap_move_email(self.uid, self.INBOX, self.INPROCESS)
        if result and "Error" in str(result):
            raise RuntimeError(f"Failed to move email to InProcess: {result}")

    @step
    def check_blocklist(self):
        """Skip if sender is blocked."""
        if self.tool.db_contains("blocked_senders", self.sender_email) == "true":
            result = self.tool.imap_move_email(self.uid, self.INPROCESS, self.SPAM)
            if result and "Error" in str(result):
                self.log(f"Warning: Failed to move to Spam: {result}")
            return "skip"

    @step
    def generate_reply(self):
        """Generate reply using AI agent."""
        context = build_email_context(
            self.uid,
            getattr(self, "message_id", ""),
            self.sender,
            self.sender_email,
            self.subject,
            getattr(self, "body", "")
        )

        self.reply = self.tool.desk_run_agent_sync(
            "deskagent_support_reply",
            json.dumps(context, ensure_ascii=False),
            initial_prompt=build_email_prompt(
                self.sender, self.sender_email, self.subject,
                getattr(self, "body", ""), lang="en"
            ),
            session_name="Email Auto-Reply"
        )
        self.log(f"Reply: {truncate_for_log(str(self.reply), 500)}")

        # Save agent response to workflow history for display
        self.save_response(str(self.reply))

    @step
    def send_and_archive(self):
        """Send reply and move to Done."""
        # Build complete reply: response + footer + quoted original
        reply_body = build_reply_body(
            response=str(self.reply),
            sender=self.sender,
            sender_email=self.sender_email,
            subject=self.subject,
            original_body=getattr(self, "body", ""),
            lang="en"
        )

        result = self.tool.smtp_send_reply(
            to=self.sender_email,
            subject=build_reply_subject(self.subject),
            body=reply_body,
            in_reply_to=getattr(self, "message_id", ""),
            html=True
        )
        self.log(f"Sent: {result}")

        result = self.tool.imap_move_email(self.uid, self.INPROCESS, self.DONE)
        if result and "Error" in str(result):
            raise RuntimeError(f"Failed to archive email to Done: {result}")
        self.log("Archived to Done")
