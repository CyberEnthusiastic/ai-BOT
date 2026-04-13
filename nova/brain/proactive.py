"""Proactive suggestions engine.

After Nova completes a task, this module examines the last action and suggests
logical follow-ups via pattern matching.

Examples
--------
  "Email sent."                → "Want me to add a follow-up reminder?"
  "File moved."                → "Want me to clean up the old folder?"
  "Calendar event created."    → "Want me to set a reminder 15 minutes before?"
  "Web search completed."      → "Want me to save those results to a document?"

Suggestions can be disabled via PROACTIVE_SUGGESTIONS=false in .env.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Coroutine, Any

from nova.config import PROACTIVE_SUGGESTIONS


@dataclass
class Suggestion:
    trigger_pattern: re.Pattern[str]
    suggestion: str
    follow_up_prompt: str  # sent to the agent if the user says yes


# ── Suggestion rules ──────────────────────────────────────────────────────────

_RULES: list[Suggestion] = [
    Suggestion(
        re.compile(r"\b(email|message)\s+(sent|delivered)\b", re.I),
        "Email sent. Want me to add a follow-up reminder?",
        "Add a follow-up reminder for the email I just sent in 3 days.",
    ),
    Suggestion(
        re.compile(r"\b(email|message)\s+draft(ed)?\b", re.I),
        "Draft saved. Want me to schedule it to send tomorrow morning?",
        "Schedule the draft email to send tomorrow at 9am.",
    ),
    Suggestion(
        re.compile(r"\bfile\s+(moved|copied|renamed)\b", re.I),
        "File moved. Want me to clean up the old folder?",
        "Check if the source folder is now empty and delete it if so.",
    ),
    Suggestion(
        re.compile(r"\b(calendar\s+event|meeting|appointment)\s+created\b", re.I),
        "Event created. Want me to set a reminder 15 minutes before?",
        "Add a 15-minute reminder to the calendar event I just created.",
    ),
    Suggestion(
        re.compile(r"\b(calendar\s+event|meeting)\s+updated\b", re.I),
        "Event updated. Want me to notify the other attendees?",
        "Send an email to the attendees of the updated calendar event with the changes.",
    ),
    Suggestion(
        re.compile(r"\b(web\s+search|search)\s+(complete|done|finished)\b", re.I),
        "Search complete. Want me to save those results to a document?",
        "Save the search results to a new document in my Documents folder.",
    ),
    Suggestion(
        re.compile(r"\bdownload(ed|s)?\s+(complete|finished|done)\b", re.I),
        "Download finished. Want me to open the file?",
        "Open the file I just downloaded.",
    ),
    Suggestion(
        re.compile(r"\bdocument\s+(created|written|saved)\b", re.I),
        "Document saved. Want me to email it to you?",
        "Email the document I just created to me.",
    ),
    Suggestion(
        re.compile(r"\b(app|application|program)\s+(opened|launched|started)\b", re.I),
        "App opened. Want me to remember to close it in an hour?",
        "Remind me in 1 hour to close this application.",
    ),
    Suggestion(
        re.compile(r"\breminder\s+set\b", re.I),
        "Reminder set. Want me to add it to your calendar too?",
        "Add the reminder I just set as a calendar event.",
    ),
]


class ProactiveSuggestions:
    """Suggest follow-up actions after Nova completes a task.

    Usage
    -----
        engine = ProactiveSuggestions()
        suggestion = engine.suggest(nova_response_text)
        if suggestion:
            # Ask the user and pass follow_up_prompt to orchestrator if they say yes
    """

    def __init__(self) -> None:
        self._last_follow_up: str = ""

    def suggest(self, nova_text: str) -> str | None:
        """Return a suggestion string if one matches, else None.

        Disabled when PROACTIVE_SUGGESTIONS=false.
        """
        if not PROACTIVE_SUGGESTIONS:
            return None

        for rule in _RULES:
            if rule.trigger_pattern.search(nova_text):
                self._last_follow_up = rule.follow_up_prompt
                return rule.suggestion

        return None

    @property
    def last_follow_up_prompt(self) -> str:
        """The agent prompt to use if the user accepted the last suggestion."""
        return self._last_follow_up

    def accepts_followup(self, user_text: str) -> bool:
        """Return True if the user's reply is affirmative."""
        affirmative = re.compile(
            r"\b(yes|yeah|yep|sure|ok|okay|go ahead|do it|please|yup|absolutely)\b",
            re.I,
        )
        return bool(affirmative.search(user_text))

    def declines_followup(self, user_text: str) -> bool:
        """Return True if the user's reply is negative."""
        negative = re.compile(
            r"\b(no|nope|nah|not now|skip|cancel|never mind|nevermind)\b", re.I
        )
        return bool(negative.search(user_text))
