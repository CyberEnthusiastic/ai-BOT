"""App tool: launch Windows applications and list running processes."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

# Common app aliases → executable / UWP app names
_APP_ALIASES: dict[str, str] = {
    "notepad": "notepad.exe",
    "explorer": "explorer.exe",
    "chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "outlook": "OUTLOOK.EXE",
    "vscode": "code.exe",
    "terminal": "wt.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "snip": "SnippingTool.exe",
    "task manager": "taskmgr.exe",
}

# Applications that must never be launched by Nova
_BLOCKED_APPS = {
    "regedit.exe", "regedit", "msconfig.exe", "msconfig",
    "gpedit.msc", "secpol.msc", "compmgmt.msc",
    "diskpart.exe", "format.com",
}


class AppTool:
    async def launch(self, app_name: str) -> str:
        """Launch a Windows application by common name or full executable path."""
        lower = app_name.lower().strip()

        if lower in _BLOCKED_APPS:
            return f"BLOCKED: launching '{app_name}' is not permitted."

        executable = _APP_ALIASES.get(lower, app_name)

        try:
            if sys.platform == "win32":
                proc = await asyncio.create_subprocess_exec(
                    "cmd", "/c", "start", "", executable,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode not in (0, None):
                    err = stderr.decode("utf-8", errors="replace").strip()
                    return f"Failed to launch '{app_name}': {err}"
            else:
                return "App launch is only supported on Windows."
        except asyncio.TimeoutError:
            return f"Launch timed out for '{app_name}'."
        except Exception as exc:
            return f"Error launching '{app_name}': {exc}"

        return f"Launched: {executable}"

    async def list_running(self) -> str:
        """Return a list of running processes via PowerShell."""
        if sys.platform != "win32":
            return "Process listing is only supported on Windows."
        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-Process | Select-Object -First 50 Name, Id, CPU | Format-Table -AutoSize",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            return stdout.decode("utf-8", errors="replace").strip()
        except Exception as exc:
            return f"Error listing processes: {exc}"

    async def kill(self, process_name: str) -> str:
        """Terminate a process by name (requires user confirmation flow upstream)."""
        if sys.platform != "win32":
            return "Process management is only supported on Windows."
        # Additional safety: block system-critical processes
        _critical = {"system", "smss", "csrss", "wininit", "services", "lsass", "winlogon"}
        if process_name.lower().replace(".exe", "") in _critical:
            return f"BLOCKED: cannot terminate system process '{process_name}'."
        try:
            proc = await asyncio.create_subprocess_exec(
                "taskkill", "/F", "/IM", process_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()
            return out or err or "Done."
        except Exception as exc:
            return f"Error: {exc}"
