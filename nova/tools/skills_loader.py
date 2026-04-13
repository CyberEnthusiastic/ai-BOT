"""Skills loader — discovers SKILL.md files in nova/skills/, parses their
frontmatter, and registers each skill as a callable tool.

Directory layout expected:
    nova/skills/
        <skill-name>/
            SKILL.md          ← frontmatter + prompt template
            (optional files)

SKILL.md frontmatter keys (YAML between --- markers):
    name:        Human-readable skill name (required)
    description: One-line description shown to the LLM (required)
    trigger:     Keywords / phrase that should invoke this skill (optional)
    version:     Skill version string (optional, default "1.0")

Everything after the closing --- is the skill's prompt template.
Use {{input}} as placeholder for the user's request.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Skills directory sits next to this file's parent package
_SKILLS_DIR: Path = Path(__file__).parent.parent / "skills"


@dataclass
class Skill:
    name: str
    description: str
    trigger: str
    version: str
    prompt_template: str
    source_dir: Path

    def render_prompt(self, user_input: str) -> str:
        """Fill {{input}} placeholder with the user's request."""
        return self.prompt_template.replace("{{input}}", user_input)


# ── Frontmatter parser ────────────────────────────────────────────────────────
_FM_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def _parse_skill_md(path: Path) -> Skill | None:
    """Parse a SKILL.md file and return a Skill, or None on error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    m = _FM_PATTERN.match(text)
    if not m:
        return None

    frontmatter_raw, body = m.group(1), m.group(2)

    # Minimal YAML key: value parser (no nested structures needed)
    fm: dict[str, str] = {}
    for line in frontmatter_raw.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"').strip("'")

    name = fm.get("name", "")
    description = fm.get("description", "")
    if not name or not description:
        return None

    return Skill(
        name=name,
        description=description,
        trigger=fm.get("trigger", ""),
        version=fm.get("version", "1.0"),
        prompt_template=body.strip(),
        source_dir=path.parent,
    )


# ── SkillsLoader ──────────────────────────────────────────────────────────────
class SkillsLoader:
    """Scans nova/skills/ for SKILL.md files and exposes them as tools."""

    def __init__(self, skills_dir: Path = _SKILLS_DIR) -> None:
        self._dir = skills_dir
        self._skills: dict[str, Skill] = {}

    def load(self) -> list[Skill]:
        """Scan the skills directory and load all valid SKILL.md files.

        Returns:
            List of successfully loaded Skill objects.
        """
        self._skills.clear()
        if not self._dir.exists():
            return []

        for skill_md in sorted(self._dir.rglob("SKILL.md")):
            skill = _parse_skill_md(skill_md)
            if skill:
                key = skill_md.parent.name  # folder name as key
                self._skills[key] = skill

        return list(self._skills.values())

    def list_skills(self) -> str:
        """Return a formatted list of all loaded skills."""
        if not self._skills:
            return "No skills loaded. Add skills to nova/skills/<name>/SKILL.md"
        lines = [f"Loaded {len(self._skills)} skill(s):"]
        for key, skill in self._skills.items():
            lines.append(f"  [{key}] {skill.name} v{skill.version} — {skill.description}")
            if skill.trigger:
                lines.append(f"    Trigger: {skill.trigger}")
        return "\n".join(lines)

    def get(self, skill_key: str) -> Skill | None:
        """Return a skill by its folder-name key."""
        return self._skills.get(skill_key)

    async def run_skill(self, skill_key: str, user_input: str) -> str:
        """Execute a skill by routing its rendered prompt through the LLM.

        In mock mode the rendered prompt is returned directly.
        In real mode the prompt is sent to the OpenAI API.

        Args:
            skill_key: Folder name of the skill (e.g. 'web-scraper').
            user_input: The user's request / data to fill into {{input}}.

        Returns:
            LLM response or rendered prompt (mock mode).
        """
        from nova.config import MOCK_MODE, OPENAI_API_KEY, OPENAI_MODEL

        skill = self._skills.get(skill_key)
        if not skill:
            return f"Skill '{skill_key}' not found. Run load() first."

        prompt = skill.render_prompt(user_input)

        if MOCK_MODE:
            return (
                f"[Mock] Skill '{skill.name}' would run with this prompt:\n\n"
                + "-" * 60 + "\n"
                + prompt[:500]
                + ("\n..." if len(prompt) > 500 else "")
            )

        def _call() -> str:
            try:
                from openai import OpenAI  # type: ignore
            except ImportError as exc:
                raise RuntimeError("openai not installed. Run: pip install openai") from exc
            if not OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY not set")
            client = OpenAI(api_key=OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content or ""

        return await asyncio.get_event_loop().run_in_executor(None, _call)

    def match_trigger(self, user_text: str) -> Skill | None:
        """Return the first skill whose trigger phrase appears in user_text."""
        lower = user_text.lower()
        for skill in self._skills.values():
            if skill.trigger and skill.trigger.lower() in lower:
                return skill
        return None


# Module-level singleton — shared across the agent
_loader: SkillsLoader | None = None


def get_loader() -> SkillsLoader:
    global _loader
    if _loader is None:
        _loader = SkillsLoader()
        _loader.load()
    return _loader
