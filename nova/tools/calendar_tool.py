"""Google Calendar API tool — list, get, create, update, delete events, free slots.

OAuth2 token shared with email_tool (data/credentials/token.json).
Set MOCK_MODE=true to get fake data without any Google API calls.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from nova.config import DATA_DIR, MOCK_MODE

CREDENTIALS_DIR: Path = DATA_DIR / "credentials"
TOKEN_PATH: Path = CREDENTIALS_DIR / "token.json"
GOOGLE_CREDS_PATH: Path = CREDENTIALS_DIR / "google_credentials.json"

_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

# ── Mock data ─────────────────────────────────────────────────────────────────
_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

_MOCK_EVENTS = [
    {
        "id": "event_001",
        "summary": "Team standup",
        "description": "Daily 15-minute team sync",
        "location": "Zoom",
        "start": (_today + timedelta(hours=9)).isoformat(),
        "end": (_today + timedelta(hours=9, minutes=15)).isoformat(),
        "attendees": ["alice@example.com", "bob@example.com"],
        "status": "confirmed",
    },
    {
        "id": "event_002",
        "summary": "Lunch with Alice",
        "description": "",
        "location": "Corner Cafe",
        "start": (_today + timedelta(hours=12)).isoformat(),
        "end": (_today + timedelta(hours=13)).isoformat(),
        "attendees": ["alice@example.com"],
        "status": "confirmed",
    },
    {
        "id": "event_003",
        "summary": "Project review",
        "description": "Q2 project review with stakeholders",
        "location": "Conference room B",
        "start": (_today + timedelta(hours=15)).isoformat(),
        "end": (_today + timedelta(hours=16)).isoformat(),
        "attendees": ["manager@example.com", "alice@example.com"],
        "status": "confirmed",
    },
    {
        "id": "event_004",
        "summary": "Doctor appointment",
        "description": "",
        "location": "City Medical Center",
        "start": (_today + timedelta(days=2, hours=10)).isoformat(),
        "end": (_today + timedelta(days=2, hours=11)).isoformat(),
        "attendees": [],
        "status": "confirmed",
    },
]


def _fmt_event(ev: dict) -> str:
    attendees = ", ".join(ev.get("attendees", [])) or "none"
    return (
        f"[{ev['id']}] {ev['summary']}\n"
        f"  When: {ev['start']} → {ev['end']}\n"
        f"  Where: {ev.get('location') or 'N/A'}\n"
        f"  Attendees: {attendees}"
    )


# ── Real Calendar service builder ─────────────────────────────────────────────
def _build_service():  # type: ignore[return]
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

    # Merge Calendar scope with any existing token scopes
    all_scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar",
    ]

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), all_scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not GOOGLE_CREDS_PATH.exists():
                raise FileNotFoundError(
                    f"Google credentials not found at {GOOGLE_CREDS_PATH}. "
                    "Run: python -m nova.setup.configure_google"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDS_PATH), all_scopes)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ── CalendarTool ──────────────────────────────────────────────────────────────
class CalendarTool:
    """Google Calendar API tool.  All methods are async."""

    # ── list_events ───────────────────────────────────────────────────────────
    async def list_events(
        self,
        days_ahead: int = 7,
        max_results: int = 20,
        calendar_id: str = "primary",
    ) -> str:
        """List upcoming calendar events.

        Args:
            days_ahead: How many days into the future to look.
            max_results: Maximum events to return.
            calendar_id: Google Calendar ID (default 'primary').

        Returns:
            Formatted list of events.
        """
        if MOCK_MODE:
            cutoff = _today + timedelta(days=days_ahead)
            events = [
                e for e in _MOCK_EVENTS
                if datetime.fromisoformat(e["start"]) <= cutoff
            ][:max_results]
            if not events:
                return "[Mock] No upcoming events."
            return "[Mock] Upcoming events:\n\n" + "\n\n".join(_fmt_event(e) for e in events)

        def _list() -> str:
            svc = _build_service()
            now = datetime.now(timezone.utc)
            end = now + timedelta(days=days_ahead)
            res = (
                svc.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=_to_rfc3339(now),
                    timeMax=_to_rfc3339(end),
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            items = res.get("items", [])
            if not items:
                return "No upcoming events."
            lines = []
            for item in items:
                start = item.get("start", {}).get("dateTime", item.get("start", {}).get("date", "?"))
                end_t = item.get("end", {}).get("dateTime", item.get("end", {}).get("date", "?"))
                lines.append(
                    f"[{item['id']}] {item.get('summary', 'No title')}\n"
                    f"  When: {start} → {end_t}\n"
                    f"  Where: {item.get('location', 'N/A')}"
                )
            return "\n\n".join(lines)

        return await asyncio.get_event_loop().run_in_executor(None, _list)

    # ── get_event ─────────────────────────────────────────────────────────────
    async def get_event(self, event_id: str, calendar_id: str = "primary") -> str:
        """Get details of a specific calendar event.

        Args:
            event_id: The Google Calendar event ID.
            calendar_id: Google Calendar ID (default 'primary').

        Returns:
            Formatted event details.
        """
        if MOCK_MODE:
            ev = next((e for e in _MOCK_EVENTS if e["id"] == event_id), None)
            if not ev:
                return f"[Mock] Event '{event_id}' not found."
            return "[Mock] " + _fmt_event(ev) + f"\n  Description: {ev.get('description') or 'none'}"

        def _get() -> str:
            svc = _build_service()
            item = svc.events().get(calendarId=calendar_id, eventId=event_id).execute()
            start = item.get("start", {}).get("dateTime", item.get("start", {}).get("date", "?"))
            end_t = item.get("end", {}).get("dateTime", item.get("end", {}).get("date", "?"))
            attendees = ", ".join(
                a.get("email", "?") for a in item.get("attendees", [])
            ) or "none"
            return (
                f"[{item['id']}] {item.get('summary', 'No title')}\n"
                f"  When: {start} → {end_t}\n"
                f"  Where: {item.get('location', 'N/A')}\n"
                f"  Description: {item.get('description', 'none')}\n"
                f"  Attendees: {attendees}\n"
                f"  Status: {item.get('status', 'unknown')}"
            )

        return await asyncio.get_event_loop().run_in_executor(None, _get)

    # ── create_event ──────────────────────────────────────────────────────────
    async def create_event(
        self,
        summary: str,
        start_iso: str,
        end_iso: str,
        description: str = "",
        location: str = "",
        attendees: list[str] | None = None,
        calendar_id: str = "primary",
    ) -> str:
        """Create a new calendar event. REQUIRES approval before calling.

        Args:
            summary: Event title.
            start_iso: Start datetime in ISO 8601 format (e.g. '2026-04-15T10:00:00').
            end_iso: End datetime in ISO 8601 format.
            description: Optional event description.
            location: Optional location string.
            attendees: Optional list of attendee email addresses.
            calendar_id: Google Calendar ID (default 'primary').

        Returns:
            Confirmation with new event ID.
        """
        if MOCK_MODE:
            return (
                f"[Mock] Event would be created.\n"
                f"Title: {summary}\n"
                f"When: {start_iso} → {end_iso}\n"
                f"Where: {location or 'N/A'}\n"
                f"Attendees: {', '.join(attendees or []) or 'none'}"
            )

        def _create() -> str:
            svc = _build_service()
            body: dict[str, Any] = {
                "summary": summary,
                "start": {"dateTime": start_iso, "timeZone": "UTC"},
                "end": {"dateTime": end_iso, "timeZone": "UTC"},
            }
            if description:
                body["description"] = description
            if location:
                body["location"] = location
            if attendees:
                body["attendees"] = [{"email": a} for a in attendees]

            event = svc.events().insert(calendarId=calendar_id, body=body).execute()
            return f"Event created. ID: {event['id']}  Link: {event.get('htmlLink', 'N/A')}"

        return await asyncio.get_event_loop().run_in_executor(None, _create)

    # ── update_event ──────────────────────────────────────────────────────────
    async def update_event(
        self,
        event_id: str,
        summary: str | None = None,
        start_iso: str | None = None,
        end_iso: str | None = None,
        description: str | None = None,
        location: str | None = None,
        calendar_id: str = "primary",
    ) -> str:
        """Update an existing calendar event. REQUIRES approval before calling.

        Args:
            event_id: The event ID to update.
            summary: New title (optional).
            start_iso: New start time ISO 8601 (optional).
            end_iso: New end time ISO 8601 (optional).
            description: New description (optional).
            location: New location (optional).
            calendar_id: Google Calendar ID (default 'primary').

        Returns:
            Confirmation of update.
        """
        if MOCK_MODE:
            changes = {k: v for k, v in {
                "summary": summary, "start": start_iso,
                "end": end_iso, "description": description, "location": location
            }.items() if v is not None}
            return f"[Mock] Event '{event_id}' would be updated with: {changes}"

        def _update() -> str:
            svc = _build_service()
            event = svc.events().get(calendarId=calendar_id, eventId=event_id).execute()
            if summary is not None:
                event["summary"] = summary
            if description is not None:
                event["description"] = description
            if location is not None:
                event["location"] = location
            if start_iso is not None:
                event["start"] = {"dateTime": start_iso, "timeZone": "UTC"}
            if end_iso is not None:
                event["end"] = {"dateTime": end_iso, "timeZone": "UTC"}
            updated = svc.events().update(
                calendarId=calendar_id, eventId=event_id, body=event
            ).execute()
            return f"Event updated. ID: {updated['id']}"

        return await asyncio.get_event_loop().run_in_executor(None, _update)

    # ── delete_event ──────────────────────────────────────────────────────────
    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> str:
        """Delete a calendar event. REQUIRES approval before calling.

        Args:
            event_id: The event ID to delete.
            calendar_id: Google Calendar ID (default 'primary').

        Returns:
            Confirmation of deletion.
        """
        if MOCK_MODE:
            ev = next((e for e in _MOCK_EVENTS if e["id"] == event_id), None)
            name = ev["summary"] if ev else event_id
            return f"[Mock] Event '{name}' ({event_id}) would be deleted."

        def _delete() -> str:
            svc = _build_service()
            svc.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            return f"Event '{event_id}' deleted."

        return await asyncio.get_event_loop().run_in_executor(None, _delete)

    # ── find_free_slots ───────────────────────────────────────────────────────
    async def find_free_slots(
        self,
        date_iso: str,
        duration_minutes: int = 60,
        work_start_hour: int = 9,
        work_end_hour: int = 18,
        calendar_id: str = "primary",
    ) -> str:
        """Find free time slots on a given day.

        Args:
            date_iso: Date to check in ISO format (e.g. '2026-04-15').
            duration_minutes: Minimum slot length in minutes.
            work_start_hour: Start of working hours (24h, default 9).
            work_end_hour: End of working hours (24h, default 18).
            calendar_id: Google Calendar ID (default 'primary').

        Returns:
            List of available time slots.
        """
        if MOCK_MODE:
            # Simulate busy slots from mock events on the given date
            day = datetime.fromisoformat(date_iso).replace(tzinfo=timezone.utc)
            day_events = [
                e for e in _MOCK_EVENTS
                if datetime.fromisoformat(e["start"]).date() == day.date()
            ]
            busy = [(
                datetime.fromisoformat(e["start"]),
                datetime.fromisoformat(e["end"])
            ) for e in day_events]

            work_start = day.replace(hour=work_start_hour, minute=0)
            work_end = day.replace(hour=work_end_hour, minute=0)
            slots = _compute_free_slots(work_start, work_end, busy, duration_minutes)
            if not slots:
                return f"[Mock] No free slots of {duration_minutes}min on {date_iso}."
            lines = [f"  {s.strftime('%H:%M')} – {e.strftime('%H:%M')}" for s, e in slots]
            return f"[Mock] Free slots on {date_iso}:\n" + "\n".join(lines)

        def _free() -> str:
            svc = _build_service()
            day = datetime.fromisoformat(date_iso).replace(tzinfo=timezone.utc)
            work_start = day.replace(hour=work_start_hour, minute=0)
            work_end = day.replace(hour=work_end_hour, minute=0)

            res = (
                svc.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=_to_rfc3339(work_start),
                    timeMax=_to_rfc3339(work_end),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            items = res.get("items", [])
            busy = []
            for item in items:
                s_str = item.get("start", {}).get("dateTime")
                e_str = item.get("end", {}).get("dateTime")
                if s_str and e_str:
                    busy.append((
                        datetime.fromisoformat(s_str),
                        datetime.fromisoformat(e_str),
                    ))
            slots = _compute_free_slots(work_start, work_end, busy, duration_minutes)
            if not slots:
                return f"No free slots of {duration_minutes}min on {date_iso}."
            lines = [f"  {s.strftime('%H:%M')} – {e.strftime('%H:%M')}" for s, e in slots]
            return f"Free slots on {date_iso}:\n" + "\n".join(lines)

        return await asyncio.get_event_loop().run_in_executor(None, _free)

    # ── get_today_schedule ────────────────────────────────────────────────────
    async def get_today_schedule(self, calendar_id: str = "primary") -> str:
        """Get today's full schedule.

        Args:
            calendar_id: Google Calendar ID (default 'primary').

        Returns:
            Formatted list of today's events.
        """
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if MOCK_MODE:
            today_events = [
                e for e in _MOCK_EVENTS
                if datetime.fromisoformat(e["start"]).date().isoformat() == today_str
            ]
            if not today_events:
                return "[Mock] No events today. Your schedule is clear!"
            return "[Mock] Today's schedule:\n\n" + "\n\n".join(
                _fmt_event(e) for e in today_events
            )

        def _today_schedule() -> str:
            svc = _build_service()
            day_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_end = day_start + timedelta(days=1)
            res = (
                svc.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=_to_rfc3339(day_start),
                    timeMax=_to_rfc3339(day_end),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            items = res.get("items", [])
            if not items:
                return "No events today. Your schedule is clear!"
            lines = []
            for item in items:
                start = item.get("start", {}).get("dateTime", item.get("start", {}).get("date", "?"))
                end_t = item.get("end", {}).get("dateTime", item.get("end", {}).get("date", "?"))
                lines.append(
                    f"[{item['id']}] {item.get('summary', 'No title')}\n"
                    f"  {start} → {end_t}\n"
                    f"  {item.get('location', '')}"
                )
            return "Today's schedule:\n\n" + "\n\n".join(lines)

        return await asyncio.get_event_loop().run_in_executor(None, _today_schedule)


# ── Helper: free slot computation ─────────────────────────────────────────────
def _compute_free_slots(
    work_start: datetime,
    work_end: datetime,
    busy: list[tuple[datetime, datetime]],
    duration_minutes: int,
) -> list[tuple[datetime, datetime]]:
    """Return free time windows between busy blocks."""
    delta = timedelta(minutes=duration_minutes)
    busy_sorted = sorted(busy, key=lambda x: x[0])

    slots: list[tuple[datetime, datetime]] = []
    cursor = work_start

    for b_start, b_end in busy_sorted:
        if cursor + delta <= b_start:
            slots.append((cursor, b_start))
        cursor = max(cursor, b_end)

    if cursor + delta <= work_end:
        slots.append((cursor, work_end))

    return slots
