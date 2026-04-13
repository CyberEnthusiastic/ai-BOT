"""Clipboard tool — get and set the system clipboard using pyperclip.

Works on Windows, macOS, and Linux (requires xclip/xsel on Linux).
All methods are async; clipboard I/O runs in an executor.
"""

from __future__ import annotations

import asyncio


def _get_pyperclip():
    try:
        import pyperclip  # type: ignore
        return pyperclip
    except ImportError as exc:
        raise RuntimeError(
            "pyperclip not installed. Run: pip install pyperclip"
        ) from exc


class ClipboardTool:

    async def get_clipboard(self) -> str:
        """Read the current contents of the system clipboard.

        Returns:
            Current clipboard text, or a message if clipboard is empty/unavailable.
        """
        def _get() -> str:
            pc = _get_pyperclip()
            try:
                text = pc.paste()
                if not text:
                    return "(Clipboard is empty)"
                # Truncate very large clipboard contents
                if len(text) > 8000:
                    return text[:8000] + f"\n\n... (truncated, total {len(text)} chars)"
                return text
            except Exception as exc:
                return f"Could not read clipboard: {exc}"

        return await asyncio.get_event_loop().run_in_executor(None, _get)

    async def set_clipboard(self, text: str) -> str:
        """Write text to the system clipboard.

        Args:
            text: The text to place on the clipboard.

        Returns:
            Confirmation message.
        """
        def _set() -> str:
            pc = _get_pyperclip()
            try:
                pc.copy(text)
                preview = text[:80] + ("..." if len(text) > 80 else "")
                return f"Clipboard updated ({len(text)} chars): {preview}"
            except Exception as exc:
                return f"Could not write to clipboard: {exc}"

        return await asyncio.get_event_loop().run_in_executor(None, _set)
