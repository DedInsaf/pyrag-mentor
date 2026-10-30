"""Tests for the abstract agent contracts and engine resolution."""

from typing import Any

import pytest

from backend.agents.base import Agent, AgentState, BaseAgent
from backend.core.constants import DEFAULT_GENERATION_SEED


class DummyAgent(Agent):
    async def process(self, state: AgentState) -> AgentState:
        return state


class FakeHF:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] = {}

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        self.arguments = {"prompt": prompt, **kwargs}
        return "generated"


def test_base_agent_is_abstract() -> None:
    assert "process" in BaseAgent.__abstractmethods__
    with pytest.raises(TypeError):
        BaseAgent()  # type: ignore[abstract]


def test_agent_resolves_concrete_engines() -> None:
    assert DummyAgent(engine="yandexgpt").engine == "yandexgpt"
    assert DummyAgent(engine="huggingface").engine == "huggingface"
    assert DummyAgent(engine="unknown").engine == "yandexgpt"


async def test_huggingface_call_pins_seed() -> None:
    agent = DummyAgent(engine="huggingface")
    fake = FakeHF()
    agent.hf_llm = fake  # type: ignore[assignment]
    assert await agent._call_llm("hello") == "generated"
    assert fake.arguments["seed"] == DEFAULT_GENERATION_SEED == 42


async def test_last_result_defaults_to_none() -> None:
    agent = DummyAgent(engine="yandexgpt")
    assert agent.get_last_result() is None
