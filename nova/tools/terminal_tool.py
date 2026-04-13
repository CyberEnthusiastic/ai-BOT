"""Terminal tool: sandboxed shell execution.

Blocks dangerous commands, strips environment secrets from output.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from pathlib import Path

# ── Blocked command patterns ─────────────────────────────────────────────────
_BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+(-[a-zA-Z]*f|--force)"),      # rm -rf
    re.compile(r"\brmdir\b.*\/[sS]"),                   # rmdir /s
    re.compile(r"\bdel\b.*\/[fF]"),                     # del /f
    re.compile(r"\bformat\b"),                           # format disk
    re.compile(r"\bregistry\b.*delete", re.I),          # registry delete
    re.compile(r"\bnet\s+user\b", re.I),                # net user
    re.compile(r"\bshutdown\b"),                         # shutdown
    re.compile(r"\bpoweroff\b"),                         # poweroff
    re.compile(r"\b(wget|curl)\s+.*\|\s*(bash|sh|cmd|powershell)", re.I),  # pipe to shell
    re.compile(r"\bchmod\s+777\b"),                      # chmod 777
    re.compile(r"\bsudo\b"),                             # sudo
    re.compile(r">\s*/dev/sd"),                          # overwrite block device
    re.compile(r"\bmkfs\b"),                             # make filesystem
    re.compile(r"\bdd\b.*\bof=/dev"),                   # dd to device
]

# Regex to redact potential secrets in output
_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|"           # OpenAI keys
    r"[A-Za-z0-9]{32,}|"               # Generic long tokens
    r"password\s*=\s*\S+|"            # password=...
    r"token\s*=\s*\S+|"               # token=...
    r"key\s*=\s*\S+)",                 # key=...
    re.I,
)

_MAX_OUTPUT = 16_000  # chars
_TIMEOUT = 30         # seconds


def _is_blocked(cmd: str) -> bool:
    lower = cmd.lower()
    for pat in _BLOCKED_PATTERNS:
        if pat.search(lower):
            return True
    return False


def _redact_secrets(text: str) -> str:
    return _SECRET_PATTERN.sub("[REDACTED]", text)


class TerminalTool:
    async def run(self, command: str) -> str:
        """Execute *command* in a subprocess. Returns stdout + stderr."""
        if _is_blocked(command):
            return f"BLOCKED: '{command}' matches a dangerous command pattern."

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ},  # inherit env (secrets stripped from output)
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                return f"TIMEOUT: command exceeded {_TIMEOUT}s"

        except Exception as exc:
            return f"ERROR: {exc}"

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        combined = (out + ("\n[stderr]\n" + err if err.strip() else "")).strip()
        return _redact_secrets(combined[:_MAX_OUTPUT])

    async def run_powershell(self, script: str) -> str:
        """Run a PowerShell script snippet."""
        cmd = f'powershell -NoProfile -NonInteractive -Command "{script}"'
        return await self.run(cmd)
