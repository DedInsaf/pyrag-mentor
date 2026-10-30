"""Supervisor adaptive budget, rollback, and orchestration tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from backend.agents.base import AgentState, BaseAgent
from backend.agents.supervisor import Supervisor


class SequenceAgent(BaseAgent):
    def __init__(self, updates: Iterable[dict[str, Any]]):
        super().__init__()
        self.updates = iter(updates)

    async def process(self, state: AgentState) -> AgentState:
        update = next(self.updates, {})
        state.update(update)
        self._last_result = update
        state.setdefault("reasoning_log", []).append({"agent": self.name, **update})
        return state


def test_adaptive_budget_rules() -> None:
    assert Supervisor._adaptive_budget({"critic_score": None}) == 3
    assert Supervisor._adaptive_budget({"critic_score": 3.9}) == 3
    assert Supervisor._adaptive_budget({"critic_score": 5.0}) == 2
    assert (
        Supervisor._adaptive_budget({"critic_score": 8.0, "validation_passed": False})
        == 1
    )
    assert (
        Supervisor._adaptive_budget(
            {"critic_score": 8.0, "critic_suggestions": ["Improve"]}
        )
        == 1
    )
    assert (
        Supervisor._adaptive_budget({"critic_score": 8.0, "validation_passed": True})
        == 0
    )


def test_is_improvement_rejects_regressions() -> None:
    assert not Supervisor._is_improvement({"critic_score": 8.0}, {"critic_score": 7.0})
    assert not Supervisor._is_improvement(
        {"critic_score": 8.0}, {"critic_score": 9.0, "critic_failed": True}
    )
    assert not Supervisor._is_improvement(
        {"critic_score": 8.0, "validation_passed": True},
        {"critic_score": 8.0, "validation_passed": False},
    )


def test_is_improvement_accepts_score_or_validation_gain() -> None:
    assert Supervisor._is_improvement({"critic_score": 5.0}, {"critic_score": 6.0})
    assert Supervisor._is_improvement(
        {"critic_score": 8.0, "validation_passed": False},
        {"critic_score": 8.0, "validation_passed": True},
    )


def test_equal_state_is_not_improvement() -> None:
    assert not Supervisor._is_improvement(
        {"critic_score": 8.0, "validation_passed": True},
        {"critic_score": 8.0, "validation_passed": True},
    )


def test_snapshot_restore_keeps_reasoning_log() -> None:
    state: AgentState = {
        "answer": "best",
        "critic_score": 8.0,
        "reasoning_log": [{"step": "before"}],
    }
    snapshot = Supervisor._snapshot(state)
    state.update(answer="worse", critic_score=4.0, new_key=True)
    state["reasoning_log"].append({"step": "failed attempt"})
    Supervisor._restore(state, snapshot)
    assert state["answer"] == "best"
    assert state["critic_score"] == 8.0
    assert "new_key" not in state
    assert len(state["reasoning_log"]) == 2


async def test_agents_disabled_stops_after_validator() -> None:
    validator = SequenceAgent([{"validation_passed": True}])
    supervisor = Supervisor(validator=validator)
    result = await supervisor.process(
        {"use_critic": False, "use_editor": False, "answer": "answer"}
    )
    assert result["supervisor_stopped_reason"] == "agents_disabled"
    assert result["supervisor_iterations"] == 0


async def test_critic_failure_stops_early() -> None:
    validator = SequenceAgent([{"validation_passed": True}])
    critic = SequenceAgent([{"critic_failed": True, "critic_score": None}])
    supervisor = Supervisor(validator=validator, critic=critic)
    result = await supervisor.process({"answer": "answer", "use_editor": True})
    assert result["supervisor_stopped_reason"] == "critic_failed"
    assert result["supervisor_final"] is False


async def test_good_answer_converges_without_editor() -> None:
    validator = SequenceAgent([{"validation_passed": True}])
    critic = SequenceAgent(
        [{"critic_failed": False, "critic_score": 8.0, "critic_suggestions": []}]
    )
    editor = SequenceAgent([{"editor_changed": True}])
    supervisor = Supervisor(validator=validator, critic=critic, editor=editor)
    result = await supervisor.process({"answer": "good answer"})
    assert result["supervisor_stopped_reason"] == "converged"
    assert result["supervisor_iterations"] == 0


async def test_regression_rolls_back_answer() -> None:
    validator = SequenceAgent(
        [{"validation_passed": True}, {"validation_passed": True}]
    )
    critic = SequenceAgent(
        [
            {
                "critic_failed": False,
                "critic_score": 5.0,
                "critic_suggestions": ["Improve"],
            },
            {
                "critic_failed": False,
                "critic_score": 4.0,
                "critic_suggestions": ["Worse"],
            },
        ]
    )
    editor = SequenceAgent(
        [{"answer": "worse answer", "editor_changed": True, "editor_failed": False}]
    )
    supervisor = Supervisor(validator=validator, critic=critic, editor=editor)
    result = await supervisor.process({"answer": "best answer"})
    assert result["answer"] == "best answer"
    assert result["editor_rolled_back"] is True
    assert result["supervisor_stopped_reason"] == "rollback_regression"
