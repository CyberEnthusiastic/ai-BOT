"""Screen tool: mss screen capture + pytesseract OCR."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Literal

from nova.config import SCREENSHOTS_DIR

RegionName = Literal["full", "left", "right", "top", "bottom"]


class ScreenTool:
    async def capture_and_ocr(self, region: str = "full") -> str:
        """Capture the screen (or a region) and return OCR-extracted text."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_capture_ocr, region
        )

    async def capture(self, region: str = "full") -> Path:
        """Capture the screen and save to disk. Returns the image path."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_capture, region
        )

    def _sync_capture(self, region: str = "full") -> Path:
        import mss  # type: ignore[import]
        import mss.tools

        ts = int(time.time())
        out_path = SCREENSHOTS_DIR / f"screen_{region}_{ts}.png"

        with mss.mss() as sct:
            monitor = self._get_monitor(sct, region)
            img = sct.grab(monitor)
            mss.tools.to_png(img.rgb, img.size, output=str(out_path))

        return out_path

    def _sync_capture_ocr(self, region: str = "full") -> str:
        try:
            import pytesseract  # type: ignore[import]
            from PIL import Image  # type: ignore[import]
            import mss  # type: ignore[import]
            import mss.tools
            import io

            with mss.mss() as sct:
                monitor = self._get_monitor(sct, region)
                img = sct.grab(monitor)
                png_bytes = mss.tools.to_png(img.rgb, img.size)

            pil_image = Image.open(io.BytesIO(png_bytes))
            text = pytesseract.image_to_string(pil_image)
            return text.strip()[:8_000]

        except Exception as exc:
            return f"Screen capture/OCR error: {exc}"

    @staticmethod
    def _get_monitor(sct: object, region: str) -> dict:  # type: ignore[type-arg]
        monitors = sct.monitors  # type: ignore[attr-defined]
        full = monitors[0]  # monitor[0] is the combined virtual screen

        if region == "full":
            return full

        w, h = full["width"], full["height"]
        left, top = full["left"], full["top"]

        regions: dict[str, dict] = {  # type: ignore[type-arg]
            "left":   {"left": left,         "top": top,        "width": w // 2, "height": h},
            "right":  {"left": left + w // 2, "top": top,       "width": w // 2, "height": h},
            "top":    {"left": left,          "top": top,        "width": w,      "height": h // 2},
            "bottom": {"left": left,          "top": top + h//2, "width": w,      "height": h // 2},
        }
        return regions.get(region, full)
