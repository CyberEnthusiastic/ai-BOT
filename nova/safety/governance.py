"""Risk classification for Nova actions.

Risk levels
-----------
SAFE     — read-only, low-impact (web search, read file, screen capture,
           search_emails, read_email, list_labels, get_unread_count,
           list_calendar_events, get_calendar_event, get_today_schedule,
           find_free_slots, see_screen, read_screen_content,
           read_docx, read_xlsx, read_pdf, get_clipboard, list_skills)
MODERATE — reversible writes (create file, launch app,
           draft_email, set_clipboard, run_skill,
           click_ui_element, type_into_element)
HIGH     — hard-to-reverse or externally visible changes
           (send_email, reply_email, create_calendar_event,
           update_calendar_event, execute_visual_task)
CRITICAL — destructive / privileged (format, regedit, credential access,
           delete_calendar_event)
BLOCKED  — always denied regardless of confirmation
"""

from __future__ import annotations

import re
from enum import Enum, auto
from dataclasses import dataclass
from typing import Callable

from nova.config import SAFETY_BLOCK_CRITICAL, SAFETY_CONFIRM_HIGH


class RiskLevel(Enum):
    SAFE = auto()
    MODERATE = auto()
    HIGH = auto()
    CRITICAL = auto()
    BLOCKED = auto()

    def __lt__(self, other: "RiskLevel") -> bool:
        _order = [RiskLevel.SAFE, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.CRITICAL, RiskLevel.BLOCKED]
        return _order.index(self) < _order.index(other)

    def __le__(self, other: "RiskLevel") -> bool:
        return self == other or self < other


@dataclass
class RiskAssessment:
    level: RiskLevel
    reason: str
    tool: str
    action: str


# ── Classification rules ─────────────────────────────────────────────────────
_BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bformat\b.*(c:|d:|disk)", re.I), "format disk"),
    (re.compile(r"\bregedit\b", re.I), "registry editor"),
    (re.compile(r"\bdiskpart\b", re.I), "diskpart"),
    (re.compile(r"\bnet\s+user\b.*\bpassword\b", re.I), "change user password"),
    (re.compile(r"\bcredential\b", re.I), "credential access"),
    (re.compile(r"\bshadow\b.*\bcopy\b", re.I), "shadow copy manipulation"),
]

_CRITICAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+-rf\b", re.I), "recursive delete"),
    (re.compile(r"\brmdir\s+/s\b", re.I), "recursive directory delete"),
    (re.compile(r"\bchmod\s+777\b"), "permissive chmod"),
    (re.compile(r"\bsudo\b"), "sudo"),
    (re.compile(r"program files", re.I), "write to Program Files"),
    (re.compile(r"\bC:\\Windows\b", re.I), "write to Windows dir"),
    (re.compile(r"\btaskkill\b.*\b/f\b", re.I), "force kill process"),
    (re.compile(r"\bpoweroff\b|\bshutdown\b", re.I), "system shutdown"),
    # Calendar: delete is hard-to-reverse and potentially high-impact
    (re.compile(r"\bdelete_calendar_event\b", re.I), "delete calendar event"),
]

_HIGH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bdelete\b|\bdel\b|\bunlink\b", re.I), "delete file"),
    (re.compile(r"\bmove\b.*\.\.\.", re.I), "move file"),
    (re.compile(r"\bwrite\b.*\.(py|js|ts|sh|ps1|bat|cmd)\b", re.I), "write script"),
    (re.compile(r"\binstall\b", re.I), "install software"),
    (re.compile(r"\bpip\s+install\b", re.I), "pip install"),
    (re.compile(r"\bnpm\s+install\b", re.I), "npm install"),
    # Email: sending is externally visible and irreversible
    (re.compile(r"\bsend_email\b|\breply_email\b", re.I), "send/reply email"),
    # Calendar: create/update changes shared external state
    (re.compile(r"\bcreate_calendar_event\b|\bupdate_calendar_event\b", re.I), "create/update calendar event"),
    # CUA: visual task automation has broad impact
    (re.compile(r"\bexecute_visual_task\b", re.I), "execute visual task"),
]

_MODERATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bwrite\b|\bcreate\b|\bsave\b", re.I), "write/create file"),
    (re.compile(r"\blaunch\b|\bopen\b|\bstart\b", re.I), "launch application"),
    (re.compile(r"\btype\b|\bclick\b|\bfill\b", re.I), "browser interaction"),
    # Email: drafting is local and reversible
    (re.compile(r"\bdraft_email\b", re.I), "draft email"),
    # Clipboard write is local and reversible
    (re.compile(r"\bset_clipboard\b", re.I), "write to clipboard"),
    # CUA single-step actions are moderate (user can see screen)
    (re.compile(r"\bclick_ui_element\b|\btype_into_element\b", re.I), "CUA UI interaction"),
    # Skills: runs a prompt, may have side effects
    (re.compile(r"\brun_skill\b", re.I), "run skill"),
    # Document writes are local
    (re.compile(r"\bwrite_docx\b|\bwrite_xlsx\b", re.I), "write document"),
]

# ── Explicit tool-name → risk level map (fast path) ──────────────────────────
# Used by classify_tool() for direct tool-name lookups without regex.
TOOL_RISK_MAP: dict[str, "RiskLevel"] = {}  # populated after RiskLevel is defined


def _init_tool_risk_map() -> None:
    TOOL_RISK_MAP.update({
        # ── SAFE ──────────────────────────────────────────────────────────────
        "search_emails": RiskLevel.SAFE,
        "read_email": RiskLevel.SAFE,
        "list_email_labels": RiskLevel.SAFE,
        "get_unread_count": RiskLevel.SAFE,
        "list_calendar_events": RiskLevel.SAFE,
        "get_calendar_event": RiskLevel.SAFE,
        "get_today_schedule": RiskLevel.SAFE,
        "find_free_slots": RiskLevel.SAFE,
        "see_screen": RiskLevel.SAFE,
        "read_screen_content": RiskLevel.SAFE,
        "read_docx": RiskLevel.SAFE,
        "read_xlsx": RiskLevel.SAFE,
        "read_pdf": RiskLevel.SAFE,
        "get_clipboard": RiskLevel.SAFE,
        "list_skills": RiskLevel.SAFE,
        "navigate_browser": RiskLevel.SAFE,
        "search_web": RiskLevel.SAFE,
        "extract_page_text": RiskLevel.SAFE,
        "read_file": RiskLevel.SAFE,
        "search_files": RiskLevel.SAFE,
        "list_apps": RiskLevel.SAFE,
        "capture_screen": RiskLevel.SAFE,
        # ── MODERATE ──────────────────────────────────────────────────────────
        "draft_email": RiskLevel.MODERATE,
        "set_clipboard": RiskLevel.MODERATE,
        "click_ui_element": RiskLevel.MODERATE,
        "type_into_element": RiskLevel.MODERATE,
        "run_skill": RiskLevel.MODERATE,
        "write_docx": RiskLevel.MODERATE,
        "write_xlsx": RiskLevel.MODERATE,
        "write_file": RiskLevel.MODERATE,
        "launch_app": RiskLevel.MODERATE,
        "click_element": RiskLevel.MODERATE,
        # ── HIGH ──────────────────────────────────────────────────────────────
        "send_email": RiskLevel.HIGH,
        "reply_email": RiskLevel.HIGH,
        "create_calendar_event": RiskLevel.HIGH,
        "update_calendar_event": RiskLevel.HIGH,
        "execute_visual_task": RiskLevel.HIGH,
        "run_command": RiskLevel.HIGH,
        # ── CRITICAL ──────────────────────────────────────────────────────────
        "delete_calendar_event": RiskLevel.CRITICAL,
    })


def classify_tool(tool_name: str) -> RiskAssessment:
    """Fast-path classification by exact tool function name.

    Returns a RiskAssessment using the TOOL_RISK_MAP lookup table.
    Falls back to classify() if the name is not found.
    """
    if not TOOL_RISK_MAP:
        _init_tool_risk_map()
    level = TOOL_RISK_MAP.get(tool_name)
    if level is not None:
        return RiskAssessment(level, f"tool: {tool_name}", tool_name, tool_name)
    return classify(tool_name, tool_name)


def classify(tool: str, action: str, context: str = "") -> RiskAssessment:
    """Classify the risk level of a proposed tool action."""
    combined = f"{tool} {action} {context}".lower()

    for pat, reason in _BLOCKED_PATTERNS:
        if pat.search(combined):
            return RiskAssessment(RiskLevel.BLOCKED, reason, tool, action)

    for pat, reason in _CRITICAL_PATTERNS:
        if pat.search(combined):
            return RiskAssessment(RiskLevel.CRITICAL, reason, tool, action)

    for pat, reason in _HIGH_PATTERNS:
        if pat.search(combined):
            return RiskAssessment(RiskLevel.HIGH, reason, tool, action)

    for pat, reason in _MODERATE_PATTERNS:
        if pat.search(combined):
            return RiskAssessment(RiskLevel.MODERATE, reason, tool, action)

    return RiskAssessment(RiskLevel.SAFE, "read-only or benign action", tool, action)


async def enforce(
    assessment: RiskAssessment,
    confirm_callback: Callable[[str], bool] | None = None,
) -> bool:
    """Return True if the action should proceed, False if it must be blocked.

    confirm_callback(prompt) → bool  — should ask the user; defaults to print+input.
    """
    if assessment.level == RiskLevel.BLOCKED:
        print(f"[Safety] BLOCKED: {assessment.reason}")
        return False

    if assessment.level == RiskLevel.CRITICAL and SAFETY_BLOCK_CRITICAL:
        print(f"[Safety] CRITICAL action blocked by policy: {assessment.reason}")
        return False

    if assessment.level in (RiskLevel.CRITICAL, RiskLevel.HIGH) and SAFETY_CONFIRM_HIGH:
        prompt = (
            f"[Safety] {assessment.level.name} risk action: {assessment.reason}\n"
            f"  Tool: {assessment.tool}  Action: {assessment.action}\n"
            "  Proceed? [y/N] "
        )
        if confirm_callback:
            return confirm_callback(prompt)
        answer = input(prompt).strip().lower()
        return answer in ("y", "yes")

    return True
