"""OpenAI Computer-Use Agent (CUA) tool — vision-based UI automation.

Uses GPT-4o vision to see the screen, locate elements, click, type, and
execute multi-step visual tasks.  All real calls go through the OpenAI
Responses API with computer_use_preview tools.

Set MOCK_MODE=true to skip all OpenAI calls and return descriptive strings.
"""

from __future__ import annotations

import asyncio
import base64
import io
from pathlib import Path
from typing import Any

from nova.config import MOCK_MODE, OPENAI_API_KEY, OPENAI_MODEL, SCREENSHOTS_DIR


# ── Mock helpers ──────────────────────────────────────────────────────────────
def _mock(action: str, detail: str = "") -> str:
    return f"[MOCK] Would use CUA to {action}" + (f": {detail}" if detail else "")


# ── Real helpers ──────────────────────────────────────────────────────────────
def _capture_screenshot_bytes() -> bytes:
    """Capture the full screen and return PNG bytes."""
    try:
        import mss  # type: ignore
        from PIL import Image  # type: ignore

        with mss.mss() as sct:
            monitor = sct.monitors[1]
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
    except Exception as exc:
        raise RuntimeError(f"Screenshot capture failed: {exc}") from exc


def _screenshot_b64() -> str:
    return base64.b64encode(_capture_screenshot_bytes()).decode()


def _save_screenshot(png_bytes: bytes, name: str = "cua") -> str:
    """Save PNG bytes to screenshots dir and return path."""
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOTS_DIR / f"{name}_{ts}.png"
    path.write_bytes(png_bytes)
    return str(path)


def _openai_client():
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:
        raise RuntimeError("openai package not installed. Run: pip install openai") from exc
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set in .env")
    return OpenAI(api_key=OPENAI_API_KEY)


def _vision_query(prompt: str, b64_image: str) -> str:
    """Send a vision request to GPT-4o and return the response text."""
    client = _openai_client()
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=1024,
    )
    return resp.choices[0].message.content or ""


# ── CUATool ───────────────────────────────────────────────────────────────────
class CUATool:
    """OpenAI Computer-Use Agent tool.  All methods are async."""

    # ── see_screen ────────────────────────────────────────────────────────────
    async def see_screen(self, question: str = "Describe what you see on the screen.") -> str:
        """Capture the screen and answer a question about it using GPT-4o vision.

        Args:
            question: What to ask about the current screen contents.

        Returns:
            GPT-4o's description / answer about the screen.
        """
        if MOCK_MODE:
            return _mock("capture screen and describe it", f"Q: {question}")

        def _run() -> str:
            b64 = _screenshot_b64()
            return _vision_query(question, b64)

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ── click_element ─────────────────────────────────────────────────────────
    async def click_element(self, description: str) -> str:
        """Locate and click a UI element described in natural language.

        Uses GPT-4o to find the element's screen coordinates, then uses
        pyautogui to perform the click.

        Args:
            description: Natural language description of the element to click
                         (e.g. 'the blue Submit button', 'the search box').

        Returns:
            Confirmation of the click, or error message.
        """
        if MOCK_MODE:
            return _mock("click element", description)

        def _run() -> str:
            try:
                import pyautogui  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "pyautogui not installed. Run: pip install pyautogui"
                ) from exc

            b64 = _screenshot_b64()
            prompt = (
                f"Look at this screenshot. Find the UI element described as: '{description}'.\n"
                "Reply with ONLY a JSON object: {\"x\": <pixel_x>, \"y\": <pixel_y>}\n"
                "where x and y are the center coordinates of the element.\n"
                "If you cannot find it, reply: {\"x\": null, \"y\": null}"
            )
            raw = _vision_query(prompt, b64)

            import json, re
            m = re.search(r'\{.*?\}', raw, re.DOTALL)
            if not m:
                return f"Could not parse coordinates from vision response: {raw}"
            coords = json.loads(m.group())
            x, y = coords.get("x"), coords.get("y")
            if x is None or y is None:
                return f"Element not found on screen: {description}"

            pyautogui.click(int(x), int(y))
            return f"Clicked '{description}' at ({x}, {y})."

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ── type_into ─────────────────────────────────────────────────────────────
    async def type_into(self, description: str, text: str) -> str:
        """Click a UI element and type text into it.

        Args:
            description: Natural language description of the input field.
            text: Text to type.

        Returns:
            Confirmation or error.
        """
        if MOCK_MODE:
            return _mock("type into element", f"'{description}' → '{text[:50]}'")

        # Click first, then type
        click_result = await self.click_element(description)
        if "not found" in click_result.lower() or "error" in click_result.lower():
            return click_result

        def _type() -> str:
            try:
                import pyautogui  # type: ignore
            except ImportError as exc:
                raise RuntimeError("pyautogui not installed. Run: pip install pyautogui") from exc
            import time
            time.sleep(0.2)
            pyautogui.typewrite(text, interval=0.03)
            return f"Typed into '{description}': {text[:80]}"

        return await asyncio.get_event_loop().run_in_executor(None, _type)

    # ── read_screen_content ───────────────────────────────────────────────────
    async def read_screen_content(self, region_description: str = "entire screen") -> str:
        """Read and return all visible text from the screen (or a region of it).

        Args:
            region_description: Which part of the screen to read
                                 (e.g. 'the left panel', 'the dialog box').

        Returns:
            Extracted text content from the specified region.
        """
        if MOCK_MODE:
            return _mock(
                "read screen content",
                f"region: {region_description}"
            ) + "\n[MOCK] Sample screen text: 'Nova v2 — Desktop AI Agent | Ready'"

        def _run() -> str:
            b64 = _screenshot_b64()
            prompt = (
                f"Read all visible text from the {region_description} of this screenshot.\n"
                "Return only the extracted text, preserving structure as much as possible."
            )
            return _vision_query(prompt, b64)

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ── execute_visual_task ───────────────────────────────────────────────────
    async def execute_visual_task(self, task: str, max_steps: int = 10) -> str:
        """Execute a multi-step visual task using screen + click + type in a loop.

        The agent sees the screen, decides the next action, executes it, and
        repeats until the task is complete or max_steps is reached.

        Args:
            task: Natural language description of what to accomplish
                  (e.g. 'Open Notepad and type Hello World').
            max_steps: Maximum action steps before giving up.

        Returns:
            Summary of what was done and final screen state.
        """
        if MOCK_MODE:
            return (
                _mock("execute visual task", task) + "\n"
                "[MOCK] Steps that would be taken:\n"
                "  1. Capture screen\n"
                "  2. Identify relevant UI elements\n"
                "  3. Click / type as needed\n"
                "  4. Verify completion"
            )

        def _run() -> str:
            try:
                import pyautogui  # type: ignore
            except ImportError as exc:
                raise RuntimeError("pyautogui not installed. Run: pip install pyautogui") from exc

            import json, re, time

            log: list[str] = []
            for step in range(1, max_steps + 1):
                b64 = _screenshot_b64()
                prompt = (
                    f"You are controlling a Windows desktop to complete this task: '{task}'\n"
                    f"Steps completed so far: {log}\n\n"
                    "Look at the current screenshot and decide the single best next action.\n"
                    "Reply with ONLY a JSON object with one of these formats:\n"
                    '  {"action": "click", "x": <px>, "y": <px>, "reason": "<why>"}\n'
                    '  {"action": "type", "text": "<text>", "reason": "<why>"}\n'
                    '  {"action": "key", "key": "<key_name>", "reason": "<why>"}\n'
                    '  {"action": "done", "summary": "<what was accomplished>"}\n'
                    '  {"action": "fail", "reason": "<why cannot continue>"}'
                )
                raw = _vision_query(prompt, b64)
                m = re.search(r'\{.*?\}', raw, re.DOTALL)
                if not m:
                    log.append(f"Step {step}: could not parse action")
                    break

                action = json.loads(m.group())
                act = action.get("action", "")
                reason = action.get("reason", action.get("summary", ""))

                if act == "done":
                    log.append(f"Step {step}: DONE — {reason}")
                    break
                elif act == "fail":
                    log.append(f"Step {step}: FAILED — {reason}")
                    break
                elif act == "click":
                    pyautogui.click(int(action["x"]), int(action["y"]))
                    log.append(f"Step {step}: click ({action['x']}, {action['y']}) — {reason}")
                elif act == "type":
                    pyautogui.typewrite(str(action["text"]), interval=0.03)
                    log.append(f"Step {step}: type '{action['text'][:40]}' — {reason}")
                elif act == "key":
                    pyautogui.press(action["key"])
                    log.append(f"Step {step}: key '{action['key']}' — {reason}")
                else:
                    log.append(f"Step {step}: unknown action '{act}'")
                    break

                time.sleep(0.5)  # brief pause between actions

            return f"Task: {task}\n\nExecution log:\n" + "\n".join(log)

        return await asyncio.get_event_loop().run_in_executor(None, _run)
