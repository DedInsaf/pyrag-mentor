"""Critic JSON scanner, success, and failure paths."""

import pytest

from backend.agents.critic import Critic


def test_extract_json_ignores_braces_inside_strings() -> None:
    spans = Critic._extract_json_spans('prefix {"text": "a } b", "score": 8} suffix')
    assert spans == ['{"text": "a } b", "score": 8}']


def test_parse_json_from_markdown_text() -> None:
    parsed = Critic._parse_json_response('Result:\n```json\n{"overall_score": 8}\n```')
    assert parsed["overall_score"] == 8


async def test_valid_stub_sets_score() -> None:
    critic = Critic(engine="yandexgpt")
    state = await critic.process({"question": "Q", "answer": "A"})
    assert state["critic_score"] == 8.0
    assert state["critic_failed"] is False


async def test_invalid_json_uses_none_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    critic = Critic(engine="yandexgpt")

    async def invalid(_: str) -> str:
        return "not-json"

    monkeypatch.setattr(critic, "_call_llm", invalid)
    state = await critic.process({"question": "Q", "answer": "A"})
    assert state["critic_score"] is None
    assert state["critic_failed"] is True


async def test_out_of_range_score_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    critic = Critic(engine="yandexgpt")

    async def invalid_score(_: str) -> str:
        return '{"overall_score": 11}'

    monkeypatch.setattr(critic, "_call_llm", invalid_score)
    state = await critic.process({"question": "Q", "answer": "A"})
    assert state["critic_score"] is None
