"""Answer-improvement agent driven by Validator and Critic feedback."""

from __future__ import annotations

from backend.agents.base import Agent, AgentState
from backend.utils.llm_processing import clean_answer


class Editor(Agent):
    """Improve an answer only when actionable issues are available."""

    temperature = 0.3

    async def _call_llm(self, prompt: str) -> str:
        """Temporary no-op stub; real model generation is added later."""

        del prompt
        return ""

    async def process(self, state: AgentState) -> AgentState:
        issues = [
            *state.get("validator_errors", []),
            *state.get("validator_warnings", []),
            *state.get("critic_suggestions", []),
        ]
        original = str(state.get("answer", ""))

        if state.get("critic_failed") or not issues:
            result = {
                "changed": False,
                "failed": False,
                "original": original,
                "corrected": original,
                "skipped": True,
            }
        else:
            prompt = (
                "Improve the answer without changing verified facts.\n"
                f"Question: {state.get('question', '')}\n"
                f"Answer: {original}\n"
                f"Issues: {issues}"
            )
            try:
                candidate = clean_answer(await self._call_llm(prompt)) or original
                result = {
                    "changed": candidate != original,
                    "failed": False,
                    "original": original,
                    "corrected": candidate,
                    "skipped": False,
                }
                state["answer"] = candidate
            except Exception:
                result = {
                    "changed": False,
                    "failed": True,
                    "original": original,
                    "corrected": original,
                    "skipped": False,
                }

        self._last_result = result
        state.update(
            editor_changed=result["changed"],
            editor_failed=result["failed"],
            editor_original=result["original"],
            editor_corrected=result["corrected"],
            editor_iterations=int(state.get("editor_iterations", 0))
            + (0 if result["skipped"] else 1),
        )
        state.setdefault("reasoning_log", []).append(
            {
                "agent": self.name,
                "changed": result["changed"],
                "failed": result["failed"],
                "skipped": result["skipped"],
            }
        )
        return state
