"""System tray icon for Nova (Windows compatible via pystray + Pillow).

States
------
  idle      → blue icon
  listening → green icon
  error     → red icon
  muted     → grey icon

Right-click menu
----------------
  Status        — show current state
  Mute/Unmute   — toggle microphone
  Open Web UI   — open http://localhost:8765 in browser
  Settings      — placeholder (future web settings page)
  Quit          — clean shutdown

Double-click  → toggle listening on/off.

Mock mode fallback
------------------
If pystray/Pillow are not installed, logs to stdout and continues without a tray icon.
"""

from __future__ import annotations

import threading
import webbrowser
from typing import Callable

from nova.config import HOST, PORT

# ── Icon colours ──────────────────────────────────────────────────────────────
_COLOURS = {
    "idle":      (70, 130, 180),   # steel blue
    "listening": (50, 205, 50),    # lime green
    "error":     (220, 50, 47),    # red
    "muted":     (150, 150, 150),  # grey
}

_ICON_SIZE = 64


def _make_icon_image(colour: tuple[int, int, int]):
    """Return a Pillow Image with a filled circle on transparent background."""
    try:
        from PIL import Image, ImageDraw  # type: ignore[import]
    except ImportError:
        return None

    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse(
        [margin, margin, _ICON_SIZE - margin, _ICON_SIZE - margin],
        fill=colour + (255,),
    )
    return img


class TrayIcon:
    """System tray icon controller.

    Parameters
    ----------
    on_quit:
        Callable invoked when the user selects Quit from the tray menu.
    on_toggle_mute:
        Callable invoked when the user toggles Mute/Unmute.
    """

    def __init__(
        self,
        on_quit: Callable[[], None] | None = None,
        on_toggle_mute: Callable[[], None] | None = None,
    ) -> None:
        self._on_quit = on_quit or (lambda: None)
        self._on_toggle_mute = on_toggle_mute or (lambda: None)
        self._state: str = "idle"
        self._muted: bool = False
        self._icon = None          # pystray.Icon instance
        self._thread: threading.Thread | None = None
        self._available: bool = False  # set True if pystray+PIL load successfully

    # ── Public API ────────────────────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        """Update icon colour.  state ∈ {"idle", "listening", "error", "muted"}"""
        self._state = state
        if self._icon and self._available:
            colour = _COLOURS.get(state, _COLOURS["idle"])
            img = _make_icon_image(colour)
            if img:
                self._icon.icon = img
                self._icon.title = f"Nova — {state}"

    def notify(self, title: str, message: str) -> None:
        """Show a notification balloon."""
        if self._icon and self._available:
            try:
                self._icon.notify(message, title)
            except Exception:
                pass
        print(f"[Nova] {title}: {message}")

    def start(self) -> None:
        """Start the tray icon in a background thread (non-blocking)."""
        self._thread = threading.Thread(
            target=self._run_tray,
            daemon=True,
            name="nova-tray",
        )
        self._thread.start()

    def stop(self) -> None:
        if self._icon and self._available:
            try:
                self._icon.stop()
            except Exception:
                pass

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run_tray(self) -> None:
        try:
            import pystray  # type: ignore[import]
            from PIL import Image  # type: ignore[import]  # noqa: F401
            self._available = True
        except ImportError:
            print(
                "[Tray] pystray or Pillow not installed — tray icon disabled.\n"
                "       Install with: pip install pystray Pillow"
            )
            return

        import pystray  # type: ignore[import]

        icon_img = _make_icon_image(_COLOURS["idle"])
        if icon_img is None:
            return

        menu = pystray.Menu(
            pystray.MenuItem("Nova Status", self._show_status, default=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._mute_label, self._toggle_mute),
            pystray.MenuItem("Open Web UI", self._open_web_ui),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Nova", self._quit),
        )

        self._icon = pystray.Icon(
            name="Nova",
            icon=icon_img,
            title="Nova — idle",
            menu=menu,
        )
        # Double-click toggles listening
        self._icon.run(setup=self._setup)

    def _setup(self, icon) -> None:
        icon.visible = True

    def _mute_label(self, item) -> str:  # dynamic menu label
        return "Unmute" if self._muted else "Mute"

    def _show_status(self, icon, item) -> None:
        self.notify("Nova Status", f"State: {self._state} | Muted: {self._muted}")

    def _toggle_mute(self, icon, item) -> None:
        self._muted = not self._muted
        new_state = "muted" if self._muted else "idle"
        self.set_state(new_state)
        print(f"[Tray] {'Muted' if self._muted else 'Unmuted'}")
        self._on_toggle_mute()

    def _open_web_ui(self, icon, item) -> None:
        url = f"http://{HOST}:{PORT}"
        print(f"[Tray] Opening {url}")
        webbrowser.open(url)

    def _quit(self, icon, item) -> None:
        print("[Tray] Quit requested.")
        self.stop()
        self._on_quit()


# ── Singleton accessor ────────────────────────────────────────────────────────

_tray: TrayIcon | None = None


def get_tray() -> TrayIcon:
    global _tray
    if _tray is None:
        _tray = TrayIcon()
    return _tray
