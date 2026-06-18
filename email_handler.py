"""
IMAP email reading and SMTP email sending (forwarding + report delivery).
"""
import imaplib
import re
import smtplib
import email
import email.utils
import email.header
import textwrap
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path
import html.parser


# ── HTML → plain text ──────────────────────────────────────────────────────────

class _HTMLStripper(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _strip_html(html_text: str) -> str:
    parser = _HTMLStripper()
    try:
        parser.feed(html_text)
        return parser.get_text()
    except Exception:
        return html_text


def _decode_header_field(raw: str) -> str:
    parts = []
    for fragment, charset in email.header.decode_header(raw):
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts)


# ── Email payload extraction ───────────────────────────────────────────────────

def _extract_body(msg: email.message.Message) -> str:
    """Return plain-text body, stripping HTML if necessary."""
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            charset = part.get_content_charset() or "utf-8"
            if ct == "text/plain":
                try:
                    plain_parts.append(part.get_payload(decode=True).decode(charset, errors="replace"))
                except Exception:
                    pass
            elif ct == "text/html":
                try:
                    html_parts.append(_strip_html(part.get_payload(decode=True).decode(charset, errors="replace")))
                except Exception:
                    pass
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(_strip_html(text))
            else:
                plain_parts.append(text)

    body = "\n".join(plain_parts) if plain_parts else "\n".join(html_parts)
    return body.strip()[:4000]  # cap at 4 KB for AI analysis


# ── IMAP connection ────────────────────────────────────────────────────────────

class IMAPClient:
    def __init__(self, config: dict):
        self._config = config
        self._conn: Optional[imaplib.IMAP4_SSL] = None

    def connect(self, retries: int = 5, backoff: int = 15) -> None:
        host = self._config["imap_host"]
        port = self._config["imap_port"]
        for attempt in range(1, retries + 1):
            try:
                print(f"[IMAP] Connecting to {host}:{port} (attempt {attempt}/{retries}) …")
                self._conn = imaplib.IMAP4_SSL(host, port)
                self._conn.login(self._config["email"], self._config["password"])
                print("[IMAP] Logged in successfully.")
                return
            except (OSError, imaplib.IMAP4.error) as exc:
                print(f"[IMAP] Connection failed: {exc}")
                if attempt < retries:
                    wait = backoff * attempt
                    print(f"[IMAP] Retrying in {wait}s …")
                    import time
                    time.sleep(wait)
                else:
                    raise

    def disconnect(self) -> None:
        if self._conn:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def fetch_new_emails(self, processed_uids: set[str]) -> list[dict]:
        """Fetch emails that have NOT been processed before (by UID)."""
        if not self._conn:
            raise RuntimeError("Not connected — call connect() first.")

        self._conn.select("INBOX")

        mode = self._config.get("fetch_mode", "last1hour").lower()
        if mode == "last1hour":
            # IMAP SINCE is date-only; fetch today's emails then filter by time below
            since = datetime.now(timezone.utc).strftime("%d-%b-%Y")
            criteria = f'SINCE "{since}"'
        elif mode == "unread":
            criteria = "UNSEEN"
        elif mode == "last7days":
            since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%d-%b-%Y")
            criteria = f'SINCE "{since}"'
        else:
            criteria = "ALL"

        _status, data = self._conn.search(None, criteria)
        all_ids = data[0].split()

        # For last1hour mode: IMAP SINCE is date-only, so filter by received time here
        if mode == "last1hour":
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            filtered_ids = []
            for uid in all_ids:
                try:
                    _s, hdr = self._conn.fetch(uid, "(INTERNALDATE)")
                    if hdr and hdr[0]:
                        date_match = re.search(
                            rb'"([^"]+)"', hdr[0]
                        )
                        if date_match:
                            recv = email.utils.parsedate_to_datetime(
                                date_match.group(1).decode()
                            )
                            if recv.tzinfo is None:
                                recv = recv.replace(tzinfo=timezone.utc)
                            if recv >= cutoff:
                                filtered_ids.append(uid)
                            continue
                except Exception:
                    pass
                filtered_ids.append(uid)  # include if date parse fails
            all_ids = filtered_ids

        # Filter out already-processed UIDs
        new_ids = [uid for uid in all_ids if uid.decode() not in processed_uids]
        print(f"[IMAP] {len(all_ids)} in window | {len(new_ids)} new (unprocessed)")

        emails: list[dict] = []
        for uid in new_ids:
            try:
                _s, raw = self._conn.fetch(uid, "(RFC822)")
                if not raw or not raw[0]:
                    continue
                raw_bytes = raw[0][1]
                msg = email.message_from_bytes(raw_bytes)

                subject    = _decode_header_field(msg.get("Subject", "(no subject)"))
                sender     = _decode_header_field(msg.get("From", ""))
                date_str   = msg.get("Date", "")
                message_id = msg.get("Message-ID", "")
                body       = _extract_body(msg)

                emails.append({
                    "uid":        uid.decode(),
                    "subject":    subject,
                    "sender":     sender,
                    "date":       date_str,
                    "message_id": message_id,
                    "body":       body,
                    "raw_bytes":  raw_bytes,
                })
            except Exception as exc:
                print(f"[IMAP] Could not fetch UID {uid}: {exc}")

        return emails


# ── SMTP connection ────────────────────────────────────────────────────────────

def _parse_recipients(raw: str) -> list[str]:
    """Split a recipient string that may contain multiple addresses separated by , ; or /."""
    import re
    parts = re.split(r"[,;/]", raw)
    return [p.strip() for p in parts if p.strip()]


class SMTPClient:
    def __init__(self, config: dict):
        self._config = config
        self._conn: Optional[smtplib.SMTP] = None

    def connect(self) -> None:
        print(f"[SMTP] Connecting to {self._config['smtp_host']}:{self._config['smtp_port']} …")
        self._conn = smtplib.SMTP(self._config["smtp_host"], self._config["smtp_port"])
        self._conn.ehlo()
        self._conn.starttls()
        self._conn.ehlo()
        self._conn.login(self._config["email"], self._config["password"])
        print("[SMTP] Logged in successfully.")

    def disconnect(self) -> None:
        if self._conn:
            try:
                self._conn.quit()
            except Exception:
                pass

    def forward_complaint(self, original: dict) -> None:
        """Forward a product complaint to complaint_to (vikas@ksaptech.com)."""
        recipients = _parse_recipients(self._config["complaint_to"])
        sender_email = self._config["email"]

        msg = MIMEMultipart("mixed")
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = f"[COMPLAINT] {original['subject']}"
        msg["Date"] = email.utils.formatdate(localtime=True)

        note = textwrap.dedent(f"""
            AUTOMATED ALERT — Desktop Support Agent
            ─────────────────────────────────────────────────────────
            Its important as it complain of product.

            Original email details:
              From    : {original['sender']}
              Subject : {original['subject']}
              Date    : {original['date']}
              Category: {original.get('category', '')}
              AI Summary: {original.get('summary', '')}
            ─────────────────────────────────────────────────────────

            Original message body:

            {original['body']}
        """).strip()

        msg.attach(MIMEText(note, "plain", "utf-8"))

        print(f"[SMTP] Complaint → {recipients}  |  {original['subject'][:60]}")
        self._conn.sendmail(sender_email, recipients, msg.as_bytes())
        print("[SMTP] Complaint forwarded.")

    def reply_to_customer(self, original: dict) -> None:
        """Send an acknowledgement reply to the customer who raised a complaint."""
        # Extract the raw From address (strip display name)
        customer_address = email.utils.parseaddr(original["sender"])[1]
        if not customer_address:
            print(f"[SMTP] Could not parse customer address from: {original['sender']}")
            return

        sender_email = self._config["email"]

        msg = MIMEText(
            "Dear Customer,\n\n"
            "Thank you for reaching out to us.\n\n"
            "Your problem will be attend shortly, please bear with us.\n\n"
            "We appreciate your patience and will get back to you as soon as possible.\n\n"
            "Regards,\n"
            "Support Team",
            "plain",
            "utf-8",
        )
        msg["From"]    = sender_email
        msg["To"]      = customer_address
        msg["Subject"] = f"Re: {original['subject']}"
        msg["Date"]    = email.utils.formatdate(localtime=True)
        # Thread the reply to the original message if possible
        msg_id = original.get("message_id")
        if msg_id:
            msg["In-Reply-To"] = msg_id
            msg["References"]  = msg_id

        print(f"[SMTP] Auto-reply → {customer_address}")
        self._conn.sendmail(sender_email, [customer_address], msg.as_bytes())
        print("[SMTP] Customer acknowledgement sent.")

    def send_excel_report(self, excel_path: Path) -> None:
        """Email the Excel decision chart to report_to (sumant.chakravarty@gmail.com)."""
        recipients = _parse_recipients(self._config["report_to"])
        sender_email = self._config["email"]

        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = f"Email Decision Chart — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        msg["Date"] = email.utils.formatdate(localtime=True)

        body = textwrap.dedent("""
            Hi,

            Please find attached the automated email decision chart generated by
            the Desktop Support Agent.

            The chart contains categorisation and importance analysis for all
            recently received non-complaint emails. Product complaints were
            forwarded separately to vikas@ksaptech.com.

            Regards,
            Desktop Support Agent
        """).strip()

        msg.attach(MIMEText(body, "plain", "utf-8"))

        with open(excel_path, "rb") as f:
            attachment = MIMEBase("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            attachment.set_payload(f.read())
        encoders.encode_base64(attachment)
        attachment.add_header("Content-Disposition", f'attachment; filename="{excel_path.name}"')
        msg.attach(attachment)

        print(f"[SMTP] Sending Excel report → {recipients}")
        self._conn.sendmail(sender_email, recipients, msg.as_bytes())
        print("[SMTP] Excel report sent.")
