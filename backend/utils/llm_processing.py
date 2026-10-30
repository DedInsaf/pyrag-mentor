"""Normalize model output before it enters the agent state."""

import re

_ANSWER_PREFIX = re.compile(r"^(answer|ответ)\s*:\s*", flags=re.IGNORECASE)


def clean_answer(value: str) -> str:
    """Remove common wrappers without damaging Markdown or code blocks."""

    cleaned = value.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3 and lines[0].strip() in {"```", "```markdown", "```text"}:
            cleaned = "\n".join(lines[1:-1]).strip()
    return _ANSWER_PREFIX.sub("", cleaned).strip()
