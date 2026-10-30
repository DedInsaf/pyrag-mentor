"""Deterministic rule-based validation for QA answers."""

from __future__ import annotations

import re

from backend.agents.base import AgentState, BaseAgent

_PLACEHOLDER_RE = re.compile(r"\b(todo|fixme|lorem ipsum|заглушка)\b", re.IGNORECASE)


class Validator(BaseAgent):
    """Validate required fields, answer shape, and obvious quality defects."""

    def __init__(self, min_answer_length: int = 20):
        super().__init__()
        self.min_answer_length = min_answer_length

    async def process(self, state: AgentState) -> AgentState:
        question = str(state.get("question", "")).strip()
        answer = str(state.get("answer", "")).strip()
        errors: list[str] = []
        warnings: list[str] = []

        if not question:
            errors.append("Question is required")
        if not answer:
            errors.append("Answer is required")
        elif len(answer) < self.min_answer_length:
            errors.append("Answer is too short")
        if _PLACEHOLDER_RE.search(answer):
            errors.append("Answer contains a placeholder")
        if answer.count("```") % 2:
            errors.append("Unclosed Markdown code fence")

        paragraphs = [
            part.strip().lower() for part in answer.split("\n\n") if part.strip()
        ]
        if len(paragraphs) != len(set(paragraphs)):
            warnings.append("Answer contains repeated paragraphs")
        if not state.get("sources"):
            warnings.append("No supporting sources were attached")

        passed = not errors
        result = {"passed": passed, "errors": errors, "warnings": warnings}
        self._last_result = result
        state.update(
            validation_passed=passed,
            validator_errors=errors,
            validator_warnings=warnings,
        )
        state.setdefault("reasoning_log", []).append(
            {
                "agent": self.name,
                "passed": passed,
                "errors": errors,
                "warnings": warnings,
            }
        )
        return state
