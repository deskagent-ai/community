"""
DeskAgent Order Processing Workflow
====================================
Process orders from deskagent-website: validate, create invoice, send.

Folder flow: INBOX → InProcess → Done (or Clarify if invalid)
"""

import json
import re
from typing import Optional

from workflows import Workflow, step


class OrderProcessWorkflow(Workflow):
    """Process DeskAgent orders and create invoices."""

    name = "DeskAgent Order Processing"
    icon = "shopping_cart"
    category = "sales"
    description = "Process website orders: validate, invoice, send"
    allowed_mcp = ["imap", "billomat", "desk"]

    # Folders
    INBOX = "INBOX"
    INPROCESS = "InProcess"
    DONE = "Done"
    CLARIFY = "Clarify"

    # Products - Billomat article numbers (keys match order JSON edition field)
    PRODUCTS = {
        "DESK-M1": {"article": "DESK-M1", "cycle": "MONTHLY", "recurring": True},
        "DESK-Y1": {"article": "DESK-Y1", "cycle": "YEARLY", "recurring": False},
    }

    @step
    def validate_order(self):
        """Parse and validate order using AI agent."""
        body = getattr(self, "body", "")
        self.log(f"Processing: {getattr(self, 'subject', '')[:50]}")

        # Parse JSON from email - try full body first, then extract
        self.order_data = None

        # Try parsing full body as JSON
        try:
            data = json.loads(body.strip())
            if data.get("type") == "order":
                self.order_data = data
        except json.JSONDecodeError:
            pass

        # If not found, try to extract JSON block from email
        if not self.order_data:
            # Find JSON by matching balanced braces
            start = body.find('{"type":"order"')
            if start == -1:
                start = body.find('{"type": "order"')
            if start >= 0:
                depth = 0
                end = start
                for i, c in enumerate(body[start:], start):
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                try:
                    self.order_data = json.loads(body[start:end])
                except json.JSONDecodeError:
                    pass

        if not self.order_data:
            self._move_to_clarify("No order JSON found")
            return "skip"

        client = self.order_data.get("client", {})
        order = self.order_data.get("order", {})

        # Check required fields
        if not all(client.get(f) for f in ["name", "email", "street", "zip", "city"]):
            self._move_to_clarify("Missing required fields")
            return "skip"

        # Check product
        edition = order.get("edition", "")
        if edition not in self.PRODUCTS:
            self._move_to_clarify(f"Unknown edition: {edition}")
            return "skip"

        # AI validation for spam/test detection
        self.log("AI validation...")
        order_json = json.dumps(self.order_data, ensure_ascii=False, indent=2)
        result = self.tool.desk_run_agent_sync(
            "order_validator",
            f"Validate this order:\n\n{order_json}",
            session_name="Order Validation"
        )
        result_text = str(result).upper()
        self.log(f"AI result: {result_text[:100]}")

        # Check for explicit VALID response (must contain VALID but not SPAM/TEST)
        if "SPAM" in result_text:
            self._move_to_clarify("AI rejected: SPAM")
            return "skip"
        if "TEST" in result_text and "VALID" not in result_text:
            self._move_to_clarify("AI rejected: TEST order")
            return "skip"
        if "VALID" not in result_text:
            self._move_to_clarify(f"AI unclear: {str(result)[:50]}")
            return "skip"

        self.client = client
        self.order = order
        self.product = self.PRODUCTS[edition]
        self.log(f"Valid: {client.get('name')} - {edition}")

    @step
    def create_customer_and_invoice(self):
        """Find/create customer and set up invoice or recurring."""
        self._move_email(self.INBOX, self.INPROCESS)

        # Find or create customer
        name = self.client.get("name", "")
        search = self.tool.billomat_search_customers(name)

        if "ID" in str(search) and "Keine" not in str(search):
            self.customer_id = int(re.search(r"ID\s*(\d+)", str(search)).group(1))
            self.log(f"Found customer: {self.customer_id}")
        else:
            result = self.tool.billomat_create_customer(
                name=name, email=self.client.get("email", ""),
                company=name,
                first_name=self.client.get("first_name", ""),
                last_name=self.client.get("last_name", ""),
                street=self.client.get("street", ""),
                zip_code=self.client.get("zip", ""),
                city=self.client.get("city", ""),
                country_code=self.client.get("country_code", "DE"),
                phone=self.client.get("phone", "")
            )
            self.customer_id = int(re.search(r"ID:\s*(\d+)", str(result)).group(1))
            self.log(f"Created customer: {self.customer_id}")

        # Create invoice - first invoice is always created manually and sent immediately
        edition = self.order.get("edition", "")
        intro = f"Thank you for your DeskAgent {edition} order!"

        # Create first invoice with today's Leistungsdatum
        result = self.tool.billomat_create_invoice(
            customer_id=self.customer_id,
            intro=intro,
            template="rechnung-en-software",
            label=f"DeskAgent {edition}"
            # supply_date defaults to today
        )
        self.invoice_id = int(re.search(r"ID:\s*(\d+)", str(result)).group(1))
        self.tool.billomat_add_article_to_invoice(
            invoice_id=self.invoice_id,
            article_number=self.product["article"],
            quantity=1
        )
        self.tool.billomat_complete_invoice(self.invoice_id)
        self.log(f"Created invoice: {self.invoice_id}")

        if self.product.get("recurring"):
            # For subscriptions: also create recurring for future months
            items = json.dumps([{"article": self.product["article"], "quantity": 1}])
            result = self.tool.billomat_create_recurring(
                customer_id=self.customer_id,
                title=f"DeskAgent {edition}",
                cycle=self.product["cycle"],
                action="EMAIL",
                intro=intro,
                template="rechnung-en-software",
                items=items
            )
            self.log(f"Recurring result: {str(result)[:200]}")
            id_match = re.search(r"- ID:\s*(\d+)", str(result)) or re.search(r"ID:\s*(\d+)", str(result))
            if id_match:
                self.recurring_id = int(id_match.group(1))
                self.log(f"Created recurring for future: {self.recurring_id}")
            self.is_recurring = True
        else:
            self.is_recurring = False

    def _get_email_config(self) -> tuple[str, str]:
        """Get company name and from_addr from config for order emails."""
        try:
            from config import load_config
            config = load_config()
            branding = config.get("branding", {})
            app = config.get("app", {})
            company = branding.get("company_name", "DeskAgent")
            from_addr = app.get("support_email", "invoice@deskagent.de")
            return company, from_addr
        except Exception:
            return "DeskAgent", "invoice@deskagent.de"

    @step
    def send_email_and_complete(self):
        """Send confirmation/invoice email via SMTP and archive."""
        email = self.client.get("email", "")
        name = f"{self.client.get('first_name', '')} {self.client.get('last_name', '')}".strip()
        edition = self.order.get("edition", "")
        company_name, from_addr = self._get_email_config()

        if self.is_recurring:
            # Subscription confirmation - invoice sent separately via Billomat
            self.tool.smtp_send_email(
                to=email,
                subject=f"Your DeskAgent Subscription - {edition}",
                body=f"""Dear {name},

Thank you for subscribing to DeskAgent ({edition})!

Your invoice will be sent separately via email. Please use the payment link on the invoice to activate your subscription.

Future invoices will be sent automatically each month.

Best regards,
{company_name}
""",
                from_addr=from_addr
            )
            self.log(f"Sent subscription confirmation to {email}")
        else:
            # Invoice email with PDF - download and send via SMTP from invoice@
            pdf = self.tool.billomat_download_invoice_pdf(self.invoice_id, save_path=".temp")
            pdf_path = re.search(r"([A-Za-z]:\\[^\n]+\.pdf)", str(pdf))
            if pdf_path:
                self.tool.smtp_send_with_attachment(
                    to=email,
                    subject=f"Your DeskAgent Invoice - {edition}",
                    body=f"""Dear {name},

Thank you for your order of DeskAgent ({edition}).

Please find your invoice attached.

Best regards,
{company_name}
""",
                    attachment_path=pdf_path.group(1),
                    from_addr=from_addr
                )
                self.log(f"Sent invoice email to {email}")

        self._move_email(self.INPROCESS, self.DONE)
        self.log(f"Completed: {self.client.get('name')}")
        self.save_response(f"Order processed: {self.client.get('name')} ({edition})")

    # Helpers
    def _move_email(self, from_folder: str, to_folder: str):
        if hasattr(self, "uid"):
            self.tool.imap_move_email(self.uid, from_folder, to_folder)

    def _move_to_clarify(self, reason: str):
        self.skip_reason = reason
        self.log(f"Clarify: {reason}")
        if hasattr(self, "uid"):
            self.tool.imap_move_email(self.uid, self.INBOX, self.CLARIFY)
