"""Gmail API tool — search, read, draft, send, reply, labels, unread count.

OAuth2 credentials stored in data/credentials/token.json.
Set MOCK_MODE=true to get fake data without any Google API calls.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from nova.config import DATA_DIR, MOCK_MODE

CREDENTIALS_DIR: Path = DATA_DIR / "credentials"
TOKEN_PATH: Path = CREDENTIALS_DIR / "token.json"
GOOGLE_CREDS_PATH: Path = CREDENTIALS_DIR / "google_credentials.json"

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]


# ── Mock data helpers ─────────────────────────────────────────────────────────
_MOCK_EMAILS = [
    {
        "id": "mock_001",
        "threadId": "thread_001",
        "subject": "Meeting tomorrow at 10am",
        "from": "alice@example.com",
        "to": "you@example.com",
        "date": "Mon, 13 Apr 2026 09:00:00 +0000",
        "snippet": "Hi, just confirming our meeting tomorrow at 10am. Please bring the project notes.",
        "body": "Hi,\n\nJust confirming our meeting tomorrow at 10am. Please bring the project notes.\n\nBest,\nAlice",
        "labels": ["INBOX", "UNREAD"],
    },
    {
        "id": "mock_002",
        "threadId": "thread_002",
        "subject": "Invoice #4821 due",
        "from": "billing@vendor.com",
        "to": "you@example.com",
        "date": "Sun, 12 Apr 2026 14:30:00 +0000",
        "snippet": "Your invoice #4821 for $250.00 is due on April 20, 2026.",
        "body": "Dear Customer,\n\nYour invoice #4821 for $250.00 is due on April 20, 2026.\n\nPlease log in to pay.\n\nThanks,\nBilling Team",
        "labels": ["INBOX"],
    },
    {
        "id": "mock_003",
        "threadId": "thread_003",
        "subject": "Re: Project Alpha update",
        "from": "bob@example.com",
        "to": "you@example.com",
        "date": "Sat, 11 Apr 2026 11:15:00 +0000",
        "snippet": "Sounds good, I will have the report ready by Friday.",
        "body": "Sounds good, I will have the report ready by Friday.\n\nOn Fri, Apr 10, 2026 you wrote:\n> Can you have the report ready next week?\n",
        "labels": ["INBOX", "UNREAD"],
    },
]


def _mock_email_summary(email: dict) -> str:
    return (
        f"[{email['id']}] From: {email['from']} | "
        f"Subject: {email['subject']} | "
        f"Date: {email['date']}"
    )


# ── Real Gmail service builder ────────────────────────────────────────────────
def _build_service():  # type: ignore[return]
    """Build and return an authenticated Gmail service object."""
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Google API libraries not installed. Run: "
            "pip install google-auth-oauthlib google-api-python-client google-auth-httplib2"
        ) from exc

    creds = None
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not GOOGLE_CREDS_PATH.exists():
                raise FileNotFoundError(
                    f"Google credentials not found at {GOOGLE_CREDS_PATH}. "
                    "Run: python -m nova.setup.configure_google"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDS_PATH), _SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from a Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    if mime_type.startswith("multipart/"):
        for part in payload.get("parts", []):
            body = _extract_body(part)
            if body:
                return body
    return ""


def _parse_headers(headers: list[dict]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in headers}


# ── EmailTool ────────────────────────────────────────────────────────────────
class EmailTool:
    """Gmail API tool.  All methods are async; sync Gmail calls run in an executor."""

    # ── search_emails ─────────────────────────────────────────────────────────
    async def search_emails(self, query: str, max_results: int = 10) -> str:
        """Search Gmail messages.

        Args:
            query: Gmail search query (e.g. 'from:alice subject:meeting').
            max_results: Maximum number of results to return.

        Returns:
            Newline-separated list of matching email summaries.
        """
        if MOCK_MODE:
            q = query.lower()
            matches = [
                e for e in _MOCK_EMAILS
                if q in e["subject"].lower()
                or q in e["from"].lower()
                or q in e["body"].lower()
                or q in e["snippet"].lower()
            ] or _MOCK_EMAILS
            lines = [_mock_email_summary(e) for e in matches[:max_results]]
            return "[Mock] Search results:\n" + "\n".join(lines)

        def _search() -> str:
            svc = _build_service()
            res = svc.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()
            messages = res.get("messages", [])
            if not messages:
                return "No messages found."
            summaries = []
            for msg in messages:
                detail = svc.users().messages().get(
                    userId="me", id=msg["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()
                hdrs = _parse_headers(detail.get("payload", {}).get("headers", []))
                summaries.append(
                    f"[{msg['id']}] From: {hdrs.get('from', '?')} | "
                    f"Subject: {hdrs.get('subject', '?')} | "
                    f"Date: {hdrs.get('date', '?')}"
                )
            return "\n".join(summaries)

        return await asyncio.get_event_loop().run_in_executor(None, _search)

    # ── read_email ────────────────────────────────────────────────────────────
    async def read_email(self, email_id: str) -> str:
        """Read the full content of an email by ID.

        Args:
            email_id: The Gmail message ID.

        Returns:
            Formatted email with From, To, Subject, Date, and body.
        """
        if MOCK_MODE:
            email = next((e for e in _MOCK_EMAILS if e["id"] == email_id), None)
            if not email:
                return f"[Mock] Email '{email_id}' not found."
            return (
                f"[Mock] Email {email_id}\n"
                f"From: {email['from']}\n"
                f"To: {email['to']}\n"
                f"Subject: {email['subject']}\n"
                f"Date: {email['date']}\n"
                f"\n{email['body']}"
            )

        def _read() -> str:
            svc = _build_service()
            msg = svc.users().messages().get(
                userId="me", id=email_id, format="full"
            ).execute()
            payload = msg.get("payload", {})
            hdrs = _parse_headers(payload.get("headers", []))
            body = _extract_body(payload) or msg.get("snippet", "")
            return (
                f"From: {hdrs.get('from', '?')}\n"
                f"To: {hdrs.get('to', '?')}\n"
                f"Subject: {hdrs.get('subject', '?')}\n"
                f"Date: {hdrs.get('date', '?')}\n"
                f"\n{body}"
            )

        return await asyncio.get_event_loop().run_in_executor(None, _read)

    # ── draft_email ───────────────────────────────────────────────────────────
    async def draft_email(self, to: str, subject: str, body: str) -> str:
        """Create a Gmail draft (does NOT send).

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain text body.

        Returns:
            Confirmation with draft ID.
        """
        if MOCK_MODE:
            return (
                f"[Mock] Draft created.\n"
                f"To: {to}\nSubject: {subject}\nBody preview: {body[:100]}..."
            )

        def _draft() -> str:
            svc = _build_service()
            mime = MIMEMultipart()
            mime["to"] = to
            mime["subject"] = subject
            mime.attach(MIMEText(body, "plain"))
            raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
            draft = svc.users().drafts().create(
                userId="me", body={"message": {"raw": raw}}
            ).execute()
            return f"Draft created. ID: {draft['id']}"

        return await asyncio.get_event_loop().run_in_executor(None, _draft)

    # ── send_email ────────────────────────────────────────────────────────────
    async def send_email(self, to: str, subject: str, body: str) -> str:
        """Send an email via Gmail. REQUIRES approval before calling.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain text body.

        Returns:
            Confirmation with sent message ID.
        """
        if MOCK_MODE:
            return (
                f"[Mock] Email would be sent.\n"
                f"To: {to}\nSubject: {subject}\nBody: {body[:200]}"
            )

        def _send() -> str:
            svc = _build_service()
            mime = MIMEMultipart()
            mime["to"] = to
            mime["subject"] = subject
            mime.attach(MIMEText(body, "plain"))
            raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
            sent = svc.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            return f"Email sent. Message ID: {sent['id']}"

        return await asyncio.get_event_loop().run_in_executor(None, _send)

    # ── reply_email ───────────────────────────────────────────────────────────
    async def reply_email(self, email_id: str, body: str) -> str:
        """Reply to an existing email thread. REQUIRES approval before calling.

        Args:
            email_id: The Gmail message ID to reply to.
            body: Plain text reply body.

        Returns:
            Confirmation with sent message ID.
        """
        if MOCK_MODE:
            email = next((e for e in _MOCK_EMAILS if e["id"] == email_id), _MOCK_EMAILS[0])
            return (
                f"[Mock] Reply would be sent to thread {email['threadId']}.\n"
                f"Replying to: {email['from']}\n"
                f"Body: {body[:200]}"
            )

        def _reply() -> str:
            svc = _build_service()
            original = svc.users().messages().get(
                userId="me", id=email_id, format="metadata",
                metadataHeaders=["From", "Subject", "Message-ID"]
            ).execute()
            hdrs = _parse_headers(original.get("payload", {}).get("headers", []))
            thread_id = original.get("threadId", "")

            mime = MIMEMultipart()
            mime["to"] = hdrs.get("from", "")
            mime["subject"] = "Re: " + hdrs.get("subject", "")
            mime["In-Reply-To"] = hdrs.get("message-id", "")
            mime["References"] = hdrs.get("message-id", "")
            mime.attach(MIMEText(body, "plain"))
            raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
            sent = svc.users().messages().send(
                userId="me", body={"raw": raw, "threadId": thread_id}
            ).execute()
            return f"Reply sent. Message ID: {sent['id']}"

        return await asyncio.get_event_loop().run_in_executor(None, _reply)

    # ── list_labels ───────────────────────────────────────────────────────────
    async def list_labels(self) -> str:
        """List all Gmail labels/folders.

        Returns:
            Formatted list of label names and IDs.
        """
        if MOCK_MODE:
            return (
                "[Mock] Labels:\n"
                "INBOX | SENT | DRAFTS | SPAM | TRASH | STARRED | IMPORTANT\n"
                "Custom: Work, Personal, Newsletters, TODO"
            )

        def _labels() -> str:
            svc = _build_service()
            res = svc.users().labels().list(userId="me").execute()
            labels = res.get("labels", [])
            lines = [f"{lb['name']} (id={lb['id']})" for lb in labels]
            return "\n".join(lines) if lines else "No labels found."

        return await asyncio.get_event_loop().run_in_executor(None, _labels)

    # ── get_unread_count ──────────────────────────────────────────────────────
    async def get_unread_count(self) -> str:
        """Return number of unread messages in INBOX.

        Returns:
            Unread message count as a string.
        """
        if MOCK_MODE:
            unread = sum(1 for e in _MOCK_EMAILS if "UNREAD" in e.get("labels", []))
            return f"[Mock] You have {unread} unread message(s) in your inbox."

        def _unread() -> str:
            svc = _build_service()
            res = svc.users().messages().list(
                userId="me", q="is:unread in:inbox", maxResults=500
            ).execute()
            count = res.get("resultSizeEstimate", 0)
            return f"You have {count} unread message(s) in your inbox."

        return await asyncio.get_event_loop().run_in_executor(None, _unread)
