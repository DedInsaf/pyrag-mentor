"""Orchestrate Validator, Critic, and Editor with rollback semantics."""

from __future__ import annotations

import copy
import logging

from backend.agents.base import AgentState, BaseAgent
from backend.core.config import get_settings
from backend.core.constants import (
    ADAPTIVE_BUDGET_LOW,
    ADAPTIVE_BUDGET_MID,
    CRITIC_PASS_THRESHOLD,
)

logger = logging.getLogger(__name__)


class Supervisor:
    """Run the quality loop and preserve the best known state."""

    _NON_SNAPSHOT_KEYS = frozenset({"reasoning_log", "editor_rolled_back", "iteration"})

    def __init__(
        self,
        max_iterations: int | None = None,
        engine: str | None = None,
        *,
        validator: BaseAgent | None = None,
        critic: BaseAgent | None = None,
        editor: BaseAgent | None = None,
    ):
        settings = get_settings()
        self.max_iterations = max_iterations or settings.max_agent_iterations
        self.engine = engine or settings.agent_engine
        self._validator = validator
        self._critic = critic
        self._editor = editor
        self._iteration = 0

    def _get_validator(self) -> BaseAgent:
        if self._validator is None:
            from backend.agents.validator import Validator

            self._validator = Validator()
        return self._validator

    def _get_critic(self) -> BaseAgent:
        if self._critic is None:
            from backend.agents.critic import Critic

            self._critic = Critic(engine=self.engine)
        return self._critic

    def _get_editor(self) -> BaseAgent:
        if self._editor is None:
            from backend.agents.editor import Editor

            self._editor = Editor(engine=self.engine)
        return self._editor

    @staticmethod
    def _has_actionable_suggestions(state: AgentState) -> bool:
        return bool(state.get("critic_suggestions") or [])

    @classmethod
    def _adaptive_budget(cls, state: AgentState) -> int:
        score = state.get("critic_score")
        if score is None or score < ADAPTIVE_BUDGET_LOW:
            return 3
        if score < ADAPTIVE_BUDGET_MID:
            return 2
        if not state.get("validation_passed", True):
            return 1
        if cls._has_actionable_suggestions(state):
            return 1
        return 0

    @classmethod
    def _needs_correction(cls, state: AgentState) -> bool:
        if state.get("critic_failed"):
            return False
        score = state.get("critic_score")
        return (
            not state.get("validation_passed", True)
            or (score is not None and score < CRITIC_PASS_THRESHOLD)
            or cls._has_actionable_suggestions(state)
        )

    @staticmethod
    def _is_improvement(previous: AgentState, current: AgentState) -> bool:
        if current.get("critic_failed"):
            return False
        previous_score = previous.get("critic_score")
        current_score = current.get("critic_score")
        if current_score is None and previous_score is not None:
            return False
        if current_score is not None and previous_score is None:
            return True
        if current_score is not None and previous_score is not None:
            if current_score > previous_score:
                return True
            if current_score < previous_score:
                return False
        if current.get("validation_passed") and not previous.get("validation_passed"):
            return True
        if previous.get("validation_passed") and not current.get("validation_passed"):
            return False
        return False

    @classmethod
    def _snapshot(cls, state: AgentState) -> AgentState:
        return {
            key: copy.deepcopy(value)
            for key, value in state.items()
            if key not in cls._NON_SNAPSHOT_KEYS
        }

    @classmethod
    def _restore(cls, state: AgentState, snapshot: AgentState) -> None:
        for key in list(state):
            if key not in snapshot and key not in cls._NON_SNAPSHOT_KEYS:
                del state[key]
        for key, value in snapshot.items():
            state[key] = copy.deepcopy(value)

    @staticmethod
    def _compute_final(state: AgentState) -> bool:
        if state.get("critic_failed") or not state.get("validation_passed", False):
            return False
        score = state.get("critic_score")
        return score is None or score >= CRITIC_PASS_THRESHOLD

    def _finalize(self, state: AgentState, reason: str, budget: int) -> AgentState:
        state.update(
            supervisor_iterations=self._iteration,
            supervisor_final=self._compute_final(state),
            supervisor_stopped_reason=reason,
            supervisor_budget=budget,
        )
        state.setdefault("reasoning_log", []).append(
            {
                "agent": "Supervisor",
                "step": "final",
                "iterations": self._iteration,
                "final_passed": state["supervisor_final"],
                "stopped_reason": reason,
                "editor_rolled_back": state.get("editor_rolled_back", False),
            }
        )
        return state

    async def process(self, state: AgentState) -> AgentState:
        self._iteration = 0
        state["reasoning_log"] = []
        state["editor_rolled_back"] = False
        state["editor_iterations"] = 0

        validator = self._get_validator()
        state = await validator.process(state)
        use_critic = bool(state.get("use_critic", True))
        use_editor = bool(state.get("use_editor", True))
        if not use_critic and not use_editor:
            return self._finalize(state, "agents_disabled", 0)

        critic = self._get_critic() if use_critic else None
        if critic is not None:
            state = await critic.process(state)
            if state.get("critic_failed"):
                return self._finalize(state, "critic_failed", 0)
        if not use_editor:
            return self._finalize(state, "editor_disabled", 0)

        needs_correction = self._needs_correction(state)
        budget = min(
            self.max_iterations,
            self._adaptive_budget(state) if needs_correction else 0,
        )
        if not needs_correction:
            return self._finalize(state, "converged", budget)
        if budget == 0:
            return self._finalize(state, "budget_exhausted", budget)

        editor = self._get_editor()
        snapshot = self._snapshot(state)
        reason = "max_iterations"
        while needs_correction and self._iteration < budget:
            self._iteration += 1
            state["iteration"] = self._iteration
            state = await editor.process(state)
            state = await validator.process(state)
            if critic is not None:
                state = await critic.process(state)

            if state.get("editor_failed") or state.get("critic_failed"):
                self._restore(state, snapshot)
                state["editor_rolled_back"] = True
                reason = "rollback_error"
                break
            if not state.get("editor_changed"):
                reason = "no_change"
                break
            if not self._is_improvement(snapshot, state):
                self._restore(state, snapshot)
                state["editor_rolled_back"] = True
                reason = "rollback_regression"
                break
            snapshot = self._snapshot(state)
            state["editor_rolled_back"] = False
            needs_correction = self._needs_correction(state)
            if not needs_correction:
                reason = "converged"

        logger.info("Supervisor stopped: %s", reason)
        return self._finalize(state, reason, budget)

    def get_status(self) -> AgentState:
        return {
            "iterations": self._iteration,
            "validator": (
                self._validator.get_last_result() if self._validator else None
            ),
            "critic": self._critic.get_last_result() if self._critic else None,
        }
