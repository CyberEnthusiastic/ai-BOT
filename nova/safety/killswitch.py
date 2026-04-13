"""Kill switch: Ctrl+Shift+K terminates Nova immediately.

Registers a global hotkey using the `keyboard` library.
Works even when the terminal is not in focus.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import threading
from typing import Callable

_HOTKEY = "ctrl+shift+k"
_registered = False


def register(callback: Callable[[], None] | None = None) -> None:
    """Register the Ctrl+Shift+K global hotkey.

    If *callback* is provided it is called on activation before exit.
    Falls back gracefully if the `keyboard` library is unavailable (e.g. CI).
    """
    global _registered
    if _registered:
        return
    _registered = True

    def _handler() -> None:
        print("\n[KillSwitch] Ctrl+Shift+K detected — shutting down Nova.")
        from nova.safety.logger import session_log
        session_log("killswitch_triggered", {"hotkey": _HOTKEY})
        if callback:
            try:
                callback()
            except Exception:
                pass
        # Signal the main process to terminate cleanly
        if sys.platform == "win32":
            os.kill(os.getpid(), signal.SIGTERM)
        else:
            os.kill(os.getpid(), signal.SIGINT)

    try:
        import keyboard  # type: ignore[import]
        keyboard.add_hotkey(_HOTKEY, _handler, suppress=False)
        print(f"[KillSwitch] Registered {_HOTKEY.upper()} global kill switch.")
    except Exception as exc:
        print(f"[KillSwitch] Could not register hotkey ({exc}). "
              "Send SIGTERM or press Ctrl+C to stop Nova.")


def unregister() -> None:
    """Remove the kill-switch hotkey binding."""
    global _registered
    if not _registered:
        return
    try:
        import keyboard  # type: ignore[import]
        keyboard.remove_hotkey(_HOTKEY)
    except Exception:
        pass
    _registered = False
