"""Agent orchestrator: OpenAI Agents SDK (real) or rule-based dispatcher (mock).

Phase 3 additions:
  - Email, Calendar, CUA, Document, Clipboard, Skills agents
  - Improved intent routing (keyword → specialist agent)
  - Workflow learning: successful multi-step tasks are persisted to memory
  - Contact auto-save: names/emails mentioned in email context are stored
"""

from __future__ import annotations

import re
from typing import Any

from nova.config import (
    MOCK_MODE, OPENAI_API_KEY, OPENAI_MODEL,
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    OLLAMA_MODEL, OLLAMA_HOST,
    LLM_PROVIDER,
)
from nova.brain.system_prompt import build_system_prompt


# ── Intent routing patterns ───────────────────────────────────────────────────
_EMAIL_RE = re.compile(
    r"\b(email|mail|inbox|unread|send|reply|draft|gmail|message|subject)\b", re.I
)
_CALENDAR_RE = re.compile(
    r"\b(calendar|event|schedule|meeting|appointment|reminder|invite"
    r"|free\s+slot|today'?s?\s+plan)\b", re.I
)
_CUA_RE = re.compile(
    r"\b(click|type\s+into|fill\s+(in|out)|visual\s+task"
    r"|automate\s+(the\s+)?(ui|app|window))\b", re.I
)
_DOCUMENT_RE = re.compile(
    r"\b(docx|\.docx|word\s+doc|xlsx|\.xlsx|spreadsheet|excel|pdf|\.pdf)\b", re.I
)
_CLIPBOARD_RE = re.compile(
    r"\b(clipboard|copy\s+to|paste\s+from|what'?s\s+in\s+(my\s+)?clipboard)\b", re.I
)
_SKILL_RE = re.compile(
    r"\b(scrape|morning\s+briefing|run\s+skill|use\s+skill|list\s+skills)\b", re.I
)


def _detect_intent(text: str) -> str:
    if _EMAIL_RE.search(text):
        return "email"
    if _CALENDAR_RE.search(text):
        return "calendar"
    if _CUA_RE.search(text):
        return "cua"
    if _DOCUMENT_RE.search(text):
        return "document"
    if _CLIPBOARD_RE.search(text):
        return "clipboard"
    if _SKILL_RE.search(text):
        return "skill"
    return "general"


def _extract_after(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.I)
    if m:
        return text[m.end():].strip()
    return text.strip()


# ── Contact auto-extraction ───────────────────────────────────────────────────
_EMAIL_ADDR_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")
_NAME_FROM_RE = re.compile(r"from:\s*([A-Za-z][A-Za-z '-]{1,40})\b", re.I)


async def _maybe_save_contact(text: str) -> None:
    """Best-effort: extract email addresses from text and upsert to contacts."""
    try:
        from nova.memory.store import MemoryStore
        store = MemoryStore()
        await store.init()

        emails_found = _EMAIL_ADDR_RE.findall(text)
        name_matches = _NAME_FROM_RE.findall(text)

        for email_addr in emails_found:
            # Try to pair the address with a nearby sender name
            name = next((nm.strip() for nm in name_matches if nm.strip()), "")
            notes = f"email: {email_addr}"
            contact_name = name or email_addr.split("@")[0]
            await store.upsert_contact(contact_name, notes)
    except Exception:
        pass  # non-critical


# ── Workflow learning ─────────────────────────────────────────────────────────
async def _record_workflow(name: str, description: str, steps: list[str]) -> None:
    """Persist a successful multi-step task to the workflows memory table."""
    try:
        from nova.memory.store import MemoryStore
        store = MemoryStore()
        await store.init()
        await store.save_workflow(name, description, steps)
    except Exception:
        pass  # non-critical


# ── Mock dispatcher ───────────────────────────────────────────────────────────
class MockOrchestrator:
    """Lightweight rule-based dispatcher used when MOCK_MODE=true."""

    async def run(self, user_text: str, memory_context: str = "") -> str:
        t = user_text.lower().strip()
        intent = _detect_intent(t)

        # ── Email ─────────────────────────────────────────────────────────────
        if intent == "email":
            if re.search(r"\b(unread|count|how\s+many)\b", t):
                from nova.tools.email_tool import EmailTool
                return await EmailTool().get_unread_count()
            if re.search(r"\bsearch\b", t):
                query = _extract_after(t, r"\bsearch\b")
                from nova.tools.email_tool import EmailTool
                return await EmailTool().search_emails(query or "")
            if re.search(r"\b(send|draft)\b", t):
                return "[Mock] I would draft/send an email. Please provide To, Subject, and body."
            if re.search(r"\breply\b", t):
                return "[Mock] I would reply to that email thread."
            if re.search(r"\blabel\b", t):
                from nova.tools.email_tool import EmailTool
                return await EmailTool().list_labels()
            # Default: show inbox summary
            from nova.tools.email_tool import EmailTool
            return await EmailTool().search_emails(user_text)

        # ── Calendar ──────────────────────────────────────────────────────────
        if intent == "calendar":
            if re.search(r"\b(today|schedule)\b", t):
                from nova.tools.calendar_tool import CalendarTool
                return await CalendarTool().get_today_schedule()
            if re.search(r"\bfree\s*slot\b", t):
                from datetime import datetime, timezone
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                from nova.tools.calendar_tool import CalendarTool
                return await CalendarTool().find_free_slots(today)
            if re.search(r"\b(create|add|new)\b", t):
                return (
                    "[Mock] I would create an event. "
                    "Please provide title, start time, and end time."
                )
            if re.search(r"\b(delete|remove|cancel)\b", t):
                return "[Mock] I would delete that calendar event after you confirm."
            from nova.tools.calendar_tool import CalendarTool
            return await CalendarTool().list_events()

        # ── CUA ───────────────────────────────────────────────────────────────
        if intent == "cua":
            if re.search(r"\bclick\b", t):
                target = _extract_after(t, r"\bclick\b")
                from nova.tools.cua_tool import CUATool
                return await CUATool().click_element(target)
            if re.search(r"\btype\b", t):
                return "[Mock] I would type text into the specified element."
            from nova.tools.cua_tool import CUATool
            return await CUATool().see_screen()

        # ── Document ──────────────────────────────────────────────────────────
        if intent == "document":
            if re.search(r"\bpdf\b", t):
                return "[Mock] I would read that PDF and extract the text."
            if re.search(r"\b(xlsx|spreadsheet|excel)\b", t):
                return "[Mock] I would read/write that Excel spreadsheet."
            return "[Mock] I would read/write that Word document."

        # ── Clipboard ─────────────────────────────────────────────────────────
        if intent == "clipboard":
            if re.search(r"\b(set|copy|put)\b", t):
                content = _extract_after(t, r"\b(set|copy|put)\b")
                from nova.tools.clipboard_tool import ClipboardTool
                return await ClipboardTool().set_clipboard(content)
            from nova.tools.clipboard_tool import ClipboardTool
            return await ClipboardTool().get_clipboard()

        # ── Skills ────────────────────────────────────────────────────────────
        if intent == "skill":
            from nova.tools.skills_loader import get_loader
            loader = get_loader()
            matched = loader.match_trigger(user_text)
            if matched:
                return await loader.run_skill(matched.source_dir.name, user_text)
            return loader.list_skills()

        # ── Original Phase 1+2 intents ────────────────────────────────────────
        if re.search(r"\b(open|launch|start)\b", t):
            app = _extract_after(t, r"\b(open|launch|start)\b")
            return f"[Mock] I would launch '{app}' for you."

        if re.search(r"\bsearch\b", t):
            query = _extract_after(t, r"\bsearch\b")
            return f"[Mock] Searching the web for: {query}"

        if re.search(r"\b(read|show|open)\s+file\b", t):
            return "[Mock] I would read that file and show you the contents."

        if re.search(r"\b(screenshot|screen|capture)\b", t):
            return "[Mock] I would capture your screen and describe what's on it."

        if re.search(r"\b(run|execute|terminal|shell)\b", t):
            return "[Mock] I would run that command in a sandboxed terminal."

        if re.search(r"\b(remember|note|save)\b", t):
            return "[Mock] Noted! I've saved that to memory."

        if re.search(r"\b(time|date|today)\b", t):
            from datetime import datetime, timezone
            return f"It's {datetime.now(timezone.utc).strftime('%A, %B %d, %Y %H:%M UTC')}."

        if re.search(r"\b(hello|hi|hey)\b", t):
            return "Hello! How can I help you today?"

        if re.search(r"\b(bye|goodbye|quit|exit)\b", t):
            return "Goodbye! Shutting down Nova."

        return (
            f"[Mock] I received your request: \"{user_text}\". "
            "In real mode I would dispatch this to the appropriate agent."
        )


# ── Real orchestrator (OpenAI Agents SDK) ─────────────────────────────────────
class RealOrchestrator:
    """Uses the openai-agents SDK to run Nova's multi-agent pipeline."""

    def __init__(self) -> None:
        self._agent = None

    def _build_agent(self) -> Any:
        from agents import Agent, function_tool  # type: ignore[import]

        from nova.tools.browser_tool import BrowserTool
        from nova.tools.file_tool import FileTool
        from nova.tools.terminal_tool import TerminalTool
        from nova.tools.app_tool import AppTool
        from nova.tools.screen_tool import ScreenTool
        from nova.tools.email_tool import EmailTool
        from nova.tools.calendar_tool import CalendarTool
        from nova.tools.cua_tool import CUATool
        from nova.tools.document_tool import DocumentTool
        from nova.tools.clipboard_tool import ClipboardTool
        from nova.tools.skills_loader import get_loader

        browser = BrowserTool()
        files = FileTool()
        terminal = TerminalTool()
        apps = AppTool()
        screen = ScreenTool()
        email = EmailTool()
        calendar = CalendarTool()
        cua = CUATool()
        docs = DocumentTool()
        clip = ClipboardTool()
        skills = get_loader()

        # ── Browser ───────────────────────────────────────────────────────────
        @function_tool
        async def navigate_browser(url: str) -> str:
            """Navigate the browser to a URL and return the page title."""
            return await browser.navigate(url)

        @function_tool
        async def search_web(query: str) -> str:
            """Search the web using the default search engine."""
            return await browser.search_web(query)

        @function_tool
        async def click_element(selector: str) -> str:
            """Click an element on the current browser page by CSS selector."""
            return await browser.click(selector)

        @function_tool
        async def extract_page_text() -> str:
            """Extract all visible text from the current browser page."""
            return await browser.extract_text()

        # ── Files ─────────────────────────────────────────────────────────────
        @function_tool
        async def read_file(path: str) -> str:
            """Read a file from the filesystem."""
            return await files.read(path)

        @function_tool
        async def write_file(path: str, content: str) -> str:
            """Write content to a file on the filesystem."""
            return await files.write(path, content)

        @function_tool
        async def search_files(query: str, directory: str = ".") -> str:
            """Search for files matching a query in a directory."""
            return await files.search(query, directory)

        # ── Terminal ──────────────────────────────────────────────────────────
        @function_tool
        async def run_command(command: str) -> str:
            """Run a sandboxed shell command and return stdout."""
            return await terminal.run(command)

        # ── Apps ──────────────────────────────────────────────────────────────
        @function_tool
        async def launch_app(app_name: str) -> str:
            """Launch a Windows application by name."""
            return await apps.launch(app_name)

        @function_tool
        async def list_apps() -> str:
            """List running Windows applications."""
            return await apps.list_running()

        # ── Screen ────────────────────────────────────────────────────────────
        @function_tool
        async def capture_screen(region: str = "full") -> str:
            """Capture the screen and return OCR text."""
            return await screen.capture_and_ocr(region)

        # ── Email ─────────────────────────────────────────────────────────────
        @function_tool
        async def search_emails(query: str, max_results: int = 10) -> str:
            """Search Gmail messages using a query string (Gmail search syntax)."""
            return await email.search_emails(query, max_results)

        @function_tool
        async def read_email(email_id: str) -> str:
            """Read the full content of an email by its ID."""
            return await email.read_email(email_id)

        @function_tool
        async def draft_email(to: str, subject: str, body: str) -> str:
            """Create a Gmail draft without sending it."""
            return await email.draft_email(to, subject, body)

        @function_tool
        async def send_email(to: str, subject: str, body: str) -> str:
            """Send an email via Gmail. REQUIRES explicit user approval first."""
            return await email.send_email(to, subject, body)

        @function_tool
        async def reply_email(email_id: str, body: str) -> str:
            """Reply to an existing email thread. REQUIRES explicit user approval first."""
            return await email.reply_email(email_id, body)

        @function_tool
        async def list_email_labels() -> str:
            """List all Gmail labels and folders."""
            return await email.list_labels()

        @function_tool
        async def get_unread_count() -> str:
            """Return the number of unread emails in the inbox."""
            return await email.get_unread_count()

        # ── Calendar ──────────────────────────────────────────────────────────
        @function_tool
        async def list_calendar_events(days_ahead: int = 7) -> str:
            """List upcoming calendar events for the next N days."""
            return await calendar.list_events(days_ahead=days_ahead)

        @function_tool
        async def get_calendar_event(event_id: str) -> str:
            """Get details for a specific calendar event by ID."""
            return await calendar.get_event(event_id)

        @function_tool
        async def create_calendar_event(
            summary: str, start_iso: str, end_iso: str,
            description: str = "", location: str = "",
        ) -> str:
            """Create a new calendar event. REQUIRES explicit user approval first."""
            return await calendar.create_event(
                summary, start_iso, end_iso, description, location
            )

        @function_tool
        async def update_calendar_event(
            event_id: str, summary: str = "",
            start_iso: str = "", end_iso: str = "",
        ) -> str:
            """Update an existing calendar event. REQUIRES explicit user approval first."""
            return await calendar.update_event(
                event_id,
                summary=summary or None,
                start_iso=start_iso or None,
                end_iso=end_iso or None,
            )

        @function_tool
        async def delete_calendar_event(event_id: str) -> str:
            """Delete a calendar event. REQUIRES explicit user approval first."""
            return await calendar.delete_event(event_id)

        @function_tool
        async def find_free_slots(date_iso: str, duration_minutes: int = 60) -> str:
            """Find free time slots on a given date (YYYY-MM-DD)."""
            return await calendar.find_free_slots(date_iso, duration_minutes)

        @function_tool
        async def get_today_schedule() -> str:
            """Get the owner's schedule for today."""
            return await calendar.get_today_schedule()

        # ── CUA ───────────────────────────────────────────────────────────────
        @function_tool
        async def see_screen(question: str = "Describe what you see on the screen.") -> str:
            """Capture and describe the current screen using GPT-4o vision."""
            return await cua.see_screen(question)

        @function_tool
        async def click_ui_element(description: str) -> str:
            """Locate and click a UI element described in natural language."""
            return await cua.click_element(description)

        @function_tool
        async def type_into_element(description: str, text: str) -> str:
            """Click a UI element and type text into it."""
            return await cua.type_into(description, text)

        @function_tool
        async def read_screen_content(region_description: str = "entire screen") -> str:
            """Read all visible text from the screen or a described region."""
            return await cua.read_screen_content(region_description)

        @function_tool
        async def execute_visual_task(task: str, max_steps: int = 10) -> str:
            """Execute a multi-step visual UI task using screen + click + type."""
            return await cua.execute_visual_task(task, max_steps)

        # ── Documents ─────────────────────────────────────────────────────────
        @function_tool
        async def read_docx(path: str) -> str:
            """Read a Word (.docx) document and return its text."""
            return await docs.read_docx(path)

        @function_tool
        async def write_docx(path: str, content: str, title: str = "") -> str:
            """Write content to a Word (.docx) document."""
            return await docs.write_docx(path, content, title)

        @function_tool
        async def read_xlsx(path: str, sheet_name: str = "") -> str:
            """Read an Excel (.xlsx) spreadsheet and return its data."""
            return await docs.read_xlsx(path, sheet_name)

        @function_tool
        async def read_pdf(path: str) -> str:
            """Extract text from a PDF file."""
            return await docs.read_pdf(path)

        # ── Clipboard ─────────────────────────────────────────────────────────
        @function_tool
        async def get_clipboard() -> str:
            """Read the current contents of the system clipboard."""
            return await clip.get_clipboard()

        @function_tool
        async def set_clipboard(text: str) -> str:
            """Write text to the system clipboard."""
            return await clip.set_clipboard(text)

        # ── Skills ────────────────────────────────────────────────────────────
        @function_tool
        async def run_skill(skill_key: str, user_input: str) -> str:
            """Run a named Nova skill. Call list_skills first to see available ones."""
            return await skills.run_skill(skill_key, user_input)

        @function_tool
        async def list_skills() -> str:
            """List all available Nova skills loaded from nova/skills/."""
            return skills.list_skills()

        all_tools = [
            # Browser
            navigate_browser, search_web, click_element, extract_page_text,
            # Files
            read_file, write_file, search_files,
            # Terminal
            run_command,
            # Apps
            launch_app, list_apps,
            # Screen
            capture_screen,
            # Email
            search_emails, read_email, draft_email, send_email,
            reply_email, list_email_labels, get_unread_count,
            # Calendar
            list_calendar_events, get_calendar_event,
            create_calendar_event, update_calendar_event,
            delete_calendar_event, find_free_slots, get_today_schedule,
            # CUA
            see_screen, click_ui_element, type_into_element,
            read_screen_content, execute_visual_task,
            # Documents
            read_docx, write_docx, read_xlsx, read_pdf,
            # Clipboard
            get_clipboard, set_clipboard,
            # Skills
            run_skill, list_skills,
        ]

        return Agent(
            name="Nova",
            instructions=build_system_prompt(),
            model=OPENAI_MODEL,
            tools=all_tools,
        )

    async def run(self, user_text: str, memory_context: str = "") -> str:
        if LLM_PROVIDER == "ollama":
            response = await self._run_ollama(user_text, memory_context)
        elif LLM_PROVIDER == "claude":
            response = await self._run_claude(user_text, memory_context)
        else:
            response = await self._run_openai(user_text, memory_context)

        await _maybe_save_contact(response)

        step_markers = re.findall(r"\bStep\s+\d+\b|\d+\.\s+\w", response)
        if len(step_markers) >= 2:
            await _record_workflow(
                name=user_text[:60],
                description=f"Auto-recorded from: {user_text[:120]}",
                steps=step_markers[:10],
            )

        return response

    async def _run_ollama(self, user_text: str, memory_context: str = "") -> str:
        """Run via local Ollama — completely free, no API key needed."""
        import httpx  # type: ignore[import]

        system = build_system_prompt(memory_context)
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]

    async def _run_claude(self, user_text: str, memory_context: str = "") -> str:
        """Run via Anthropic Claude API (no Agents SDK needed)."""
        import anthropic  # type: ignore[import]

        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        system = build_system_prompt(memory_context)

        message = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_text}],
        )
        return message.content[0].text  # type: ignore[index]

    async def _run_openai(self, user_text: str, memory_context: str = "") -> str:
        """Run via OpenAI Agents SDK."""
        from agents import Runner  # type: ignore[import]

        if self._agent is None:
            self._agent = self._build_agent()

        self._agent.instructions = build_system_prompt(memory_context)
        result = await Runner.run(self._agent, user_text)  # type: ignore[attr-defined]
        return str(result.final_output)


# ── Public factory ────────────────────────────────────────────────────────────
class AgentOrchestrator:
    """Thin wrapper that picks Real or Mock based on config."""

    def __init__(self) -> None:
        if MOCK_MODE:
            self._impl: MockOrchestrator | RealOrchestrator = MockOrchestrator()
        else:
            self._impl = RealOrchestrator()

    async def run(self, user_text: str, memory_context: str = "") -> str:
        response = await self._impl.run(user_text, memory_context)
        # Contact auto-save in mock mode too
        if MOCK_MODE:
            await _maybe_save_contact(response)
        return response
