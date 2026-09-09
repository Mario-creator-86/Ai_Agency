"""Prompt Injection defense and external web text isolation.

Enforces Zone D (untrusted web data) constraints according to
40_THREAT_MODEL_SECURITY_BOUNDARIES.md and 30_PROMPT_CONTEXT_MEMORY_ARCHITECTURE.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Common LLM prompt/chat delimiter tokens that must never leak from untrusted text
DISALLOWED_DELIMITERS: list[str] = [
    "<|im_start|>",
    "<|im_end|>",
    "<<SYS>>",
    "<</SYS>>",
    "[INST]",
    "[/INST]",
    "### System:",
    "### Human:",
    "### Assistant:",
    "System Prompt:",
]

# Patterns characteristic of prompt injections and jailbreaks
INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"\b(ignore|disregard|forget|override)\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules|directives|commands)\b",
            re.IGNORECASE,
        ),
        "INSTRUCTION_OVERRIDE",
    ),
    (
        re.compile(
            r"\b(system\s+prompt|developer\s+mode|jailbreak|reveal\s+(your\s+)?(system|internal|original|secret)\s+(prompt|instructions))\b",
            re.IGNORECASE,
        ),
        "SYSTEM_PROMPT_PROBE",
    ),
    (
        re.compile(
            r"\b(you\s+are\s+now|act\s+as|pretend\s+to\s+be)\s+(DAN|unrestricted|god\s+mode|chaos)\b",
            re.IGNORECASE,
        ),
        "PERSONA_HIJACK",
    ),
    (re.compile(r"<script[\s>].*?</script>", re.IGNORECASE | re.DOTALL), "HTML_SCRIPT_TAG"),
    (re.compile(r"\beval\s*\(|exec\s*\(|__import__", re.IGNORECASE), "CODE_EXEC_PROBE"),
]


@dataclass
class SanitizationResult:
    sanitized_text: str
    has_injection: bool = False
    flagged_reasons: list[str] = field(default_factory=list)
    tokens_removed_count: int = 0


def strip_llm_delimiters(text: str) -> tuple[str, int]:
    """Strip dangerous LLM control tokens from untrusted external text."""
    removed = 0
    cleaned = text
    for delim in DISALLOWED_DELIMITERS:
        if delim in cleaned:
            count = cleaned.count(delim)
            cleaned = cleaned.replace(delim, " ")
            removed += count
    return cleaned, removed


def detect_prompt_injections(text: str) -> list[str]:
    """Scan text for adversarial prompt injection signatures."""
    reasons = []
    for pattern, name in INJECTION_PATTERNS:
        if pattern.search(text):
            reasons.append(name)
    return reasons


def sanitize_untrusted_text(text: str) -> SanitizationResult:
    """Sanitize external text from Zone D before feeding into context or storage."""
    cleaned, tokens_removed = strip_llm_delimiters(text)
    reasons = detect_prompt_injections(cleaned)

    # Neutralize matched injection phrases by redacting them
    for pattern, _ in INJECTION_PATTERNS:
        cleaned = pattern.sub("[FILTERED_ADVERSARIAL_INSTRUCTION]", cleaned)

    # Normalize excessive newlines/spaces
    cleaned = re.sub(r"\r\n|\r", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return SanitizationResult(
        sanitized_text=cleaned.strip(),
        has_injection=len(reasons) > 0,
        flagged_reasons=reasons,
        tokens_removed_count=tokens_removed,
    )


def wrap_in_inert_boundary(text: str, content_hash: str) -> str:
    """Wrap untrusted research text in boundary tags for prompt templates.

    Instructs the model explicitly that everything within the boundary is
    passive reference data, never executable instructions.
    """
    return (
        f'<untrusted_source_evidence hash="{content_hash}">\n{text}\n</untrusted_source_evidence>'
    )
