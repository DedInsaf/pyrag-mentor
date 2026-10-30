"""LLM-as-a-Judge agent with defensive JSON extraction."""

from __future__ import annotations

import json
from typing import Any

from backend.agents.base import Agent, AgentState


class Critic(Agent):
    """Score relevance, correctness, completeness, clarity, and grounding."""

    temperature = 0.0

    @staticmethod
    def _extract_json_spans(value: str) -> list[str]:
        """Extract balanced JSON objects while respecting quoted braces."""

        spans: list[str] = []
        depth = 0
        start: int | None = None
        in_string = False
        escaped = False
        for index, char in enumerate(value):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                if depth == 0:
                    start = index
                depth += 1
            elif char == "}" and depth:
                depth -= 1
                if depth == 0 and start is not None:
                    spans.append(value[start : index + 1])
                    start = None
        return spans

    @classmethod
    def _parse_json_response(cls, value: str) -> dict[str, Any]:
        candidates = [value.strip(), *cls._extract_json_spans(value)]
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("Critic response does not contain a valid JSON object")

    async def _call_llm(self, prompt: str) -> str:
        """Temporary deterministic stub; replaced by the real call later."""

        del prompt
        return json.dumps(
            {
                "relevance": 8.0,
                "correctness": 8.0,
                "completeness": 8.0,
                "clarity": 8.0,
                "grounding": 8.0,
                "overall_score": 8.0,
                "reasoning": "Stage-5 deterministic critic stub",
                "suggestions": [],
            }
        )

    async def process(self, state: AgentState) -> AgentState:
        prompt = (
            "Evaluate this QA answer and return JSON with scores 0-10.\n"
            f"Question: {state.get('question', '')}\n"
            f"Answer: {state.get('answer', '')}\n"
            f"Sources: {state.get('sources', [])}"
        )
        try:
            parsed = self._parse_json_response(await self._call_llm(prompt))
            overall = float(parsed["overall_score"])
            if not 0 <= overall <= 10:
                raise ValueError("overall_score must be between 0 and 10")
            suggestions = parsed.get("suggestions", [])
            if not isinstance(suggestions, list):
                suggestions = [str(suggestions)]
            result = {
                "overall_score": overall,
                "reasoning": str(parsed.get("reasoning", "")),
                "suggestions": [str(item) for item in suggestions],
                "scores": {
                    key: float(parsed.get(key, overall))
                    for key in (
                        "relevance",
                        "correctness",
                        "completeness",
                        "clarity",
                        "grounding",
                    )
                },
                "failed": False,
            }
        except (KeyError, TypeError, ValueError):
            result = {
                "overall_score": None,
                "reasoning": "Critic response parsing failed",
                "suggestions": [],
                "scores": {},
                "failed": True,
            }

        self._last_result = result
        state.update(
            critic_score=result["overall_score"],
            critic_reasoning=result["reasoning"],
            critic_suggestions=result["suggestions"],
            critic_scores=result["scores"],
            critic_failed=result["failed"],
        )
        state.setdefault("reasoning_log", []).append(
            {
                "agent": self.name,
                "score": result["overall_score"],
                "failed": result["failed"],
            }
        )
        return state
