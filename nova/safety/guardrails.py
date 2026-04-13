"""Input guardrails and output redaction for Nova."""

from __future__ import annotations

import re

# ── Input block patterns ─────────────────────────────────────────────────────
_BLOCKED_INPUT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Prompt injection attempts
    (re.compile(r"ignore\s+.{0,20}instructions", re.I), "prompt injection"),
    (re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", re.I), "role override"),
    (re.compile(r"(jailbreak|dan mode|developer mode)", re.I), "jailbreak attempt"),
    (re.compile(r"(pretend|act)\s+(you\s+(are|have|can)|as\s+(if|though))", re.I), "persona override"),
    (re.compile(r"(no\s+restrictions|no\s+limits|without\s+restrictions)", re.I), "restrictions bypass"),
    # Dangerous code / shell injection
    (re.compile(r"(os\.system|subprocess\.run|eval\(|exec\()", re.I), "code injection"),
    (re.compile(r"(__import__|importlib)", re.I), "dynamic import"),
    # Social engineering
    (re.compile(r"(your\s+creator|anthropic|openai)\s+(said|told|wants)\s+you", re.I), "social engineering"),
]

# ── Output redaction patterns ─────────────────────────────────────────────────
_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # API keys
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[OPENAI_KEY]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.I), "[BEARER_TOKEN]"),
    # Passwords / secrets in common formats
    (re.compile(r"(password|passwd|pwd)\s*[=:]\s*\S+", re.I), r"\1=[REDACTED]"),
    (re.compile(r"(secret|token|api_key|apikey)\s*[=:]\s*\S+", re.I), r"\1=[REDACTED]"),
    # Credit card-like patterns
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD_NUMBER]"),
    # SSN-like
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    # Phone numbers (US formats: 555-867-5309, (555) 867-5309, +1 555 867 5309)
    (re.compile(r"\b(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"), "[PHONE]"),
]


class Guardrails:
    def check_input(self, text: str) -> bool:
        """Return False if the input should be blocked entirely."""
        for pat, reason in _BLOCKED_INPUT_PATTERNS:
            if pat.search(text):
                print(f"[Guardrails] Input blocked: {reason}")
                return False
        return True

    def redact_output(self, text: str) -> str:
        """Strip sensitive values from Nova's output before display/TTS."""
        result = text
        for pat, replacement in _REDACT_PATTERNS:
            result = pat.sub(replacement, result)
        return result

    def sanitise_tool_arg(self, arg: str, max_len: int = 4096) -> str:
        """Basic sanitisation for tool arguments (length limit + null-byte removal)."""
        clean = arg.replace("\x00", "").strip()
        return clean[:max_len]
