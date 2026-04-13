"""File tool: search, read, write, move, delete, create_dir, list_dir.

Sensitive paths (system dirs, credential files) are blocked.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path

# ── Blocked path patterns ─────────────────────────────────────────────────────
_BLOCKED_PATHS = [
    "C:/Windows",
    "C:/Program Files",
    "C:/Program Files (x86)",
    os.path.expanduser("~/.ssh"),
    os.path.expanduser("~/AppData/Roaming/Microsoft/Credentials"),
]

_BLOCKED_EXTENSIONS = {".exe", ".dll", ".sys", ".bat", ".cmd", ".ps1", ".msi"}
_SENSITIVE_FILENAMES = {
    ".env", "secrets.json", "credentials.json", "id_rsa", "id_ed25519",
    ".netrc", "htpasswd", "shadow", "passwd",
}
_MAX_READ_BYTES = 512 * 1024  # 512 KB


def _check_path(path: Path) -> None:
    resolved = path.resolve()
    resolved_str = str(resolved).replace("\\", "/")
    for blocked in _BLOCKED_PATHS:
        if resolved_str.startswith(blocked.replace("\\", "/")):
            raise PermissionError(f"Access denied: {path}")
    if resolved.name.lower() in _SENSITIVE_FILENAMES:
        raise PermissionError(f"Access denied: sensitive file {path.name}")


class FileTool:
    async def search(self, query: str, directory: str = ".") -> str:
        """Find files whose name contains *query* (case-insensitive)."""
        base = Path(directory).resolve()
        matches: list[str] = []
        pattern = f"*{query.lower()}*"
        for p in base.rglob("*"):
            if fnmatch.fnmatch(p.name.lower(), pattern):
                matches.append(str(p))
            if len(matches) >= 50:
                break
        if not matches:
            return f"No files matching '{query}' found in {directory}"
        return "\n".join(matches)

    async def read(self, path: str) -> str:
        """Read and return file contents (text, ≤512 KB)."""
        p = Path(path)
        _check_path(p)
        if not p.exists():
            return f"File not found: {path}"
        if not p.is_file():
            return f"Not a file: {path}"
        size = p.stat().st_size
        if size > _MAX_READ_BYTES:
            return f"File too large ({size} bytes) — reading first 512 KB only.\n\n" + p.read_bytes()[:_MAX_READ_BYTES].decode("utf-8", errors="replace")
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"Error reading file: {exc}"

    async def write(self, path: str, content: str) -> str:
        """Write *content* to *path* (creates parent dirs if needed)."""
        p = Path(path)
        _check_path(p)
        if p.suffix.lower() in _BLOCKED_EXTENSIONS:
            raise PermissionError(f"Writing {p.suffix} files is blocked")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} chars to {path}"

    async def move(self, src: str, dst: str) -> str:
        """Move a file or directory."""
        s, d = Path(src), Path(dst)
        _check_path(s)
        _check_path(d)
        shutil.move(str(s), str(d))
        return f"Moved {src} → {dst}"

    async def delete(self, path: str) -> str:
        """Delete a file (not a directory)."""
        p = Path(path)
        _check_path(p)
        if not p.exists():
            return f"Not found: {path}"
        if p.is_dir():
            return "Use delete on files only, not directories."
        p.unlink()
        return f"Deleted {path}"

    async def create_dir(self, path: str) -> str:
        """Create a directory (including parents)."""
        p = Path(path)
        _check_path(p)
        p.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {path}"

    async def list_dir(self, path: str = ".") -> str:
        """List the contents of a directory."""
        p = Path(path)
        _check_path(p)
        if not p.exists():
            return f"Directory not found: {path}"
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        lines = []
        for entry in entries[:200]:
            kind = "DIR " if entry.is_dir() else "FILE"
            size = entry.stat().st_size if entry.is_file() else 0
            lines.append(f"{kind}  {entry.name:<40} {size:>10} bytes" if entry.is_file() else f"{kind}  {entry.name}/")
        return "\n".join(lines) or "(empty)"
