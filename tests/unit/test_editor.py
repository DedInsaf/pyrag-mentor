"""Editor skip, change, and failure behavior."""

import pytest

from backend.agents.editor import Editor


async def test_editor_skips_when_critic_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    editor = Editor(engine="yandexgpt")

    async def must_not_call(_: str) -> str:
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(editor, "_call_llm", must_not_call)
    state = await editor.process({"answer": "original", "critic_failed": True})
    assert state["editor_changed"] is False
    assert state["editor_iterations"] == 0


async def test_editor_skips_without_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    editor = Editor(engine="yandexgpt")

    async def must_not_call(_: str) -> str:
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(editor, "_call_llm", must_not_call)
    state = await editor.process({"answer": "original"})
    assert state["editor_changed"] is False


async def test_editor_updates_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    editor = Editor(engine="yandexgpt")

    async def corrected(_: str) -> str:
        return "A corrected and substantially improved answer."

    monkeypatch.setattr(editor, "_call_llm", corrected)
    state = await editor.process(
        {"answer": "original", "critic_suggestions": ["Add detail"]}
    )
    assert state["editor_changed"] is True
    assert state["answer"].startswith("A corrected")


async def test_editor_marks_model_error(monkeypatch: pytest.MonkeyPatch) -> None:
    editor = Editor(engine="yandexgpt")

    async def broken(_: str) -> str:
        raise RuntimeError("model failed")

    monkeypatch.setattr(editor, "_call_llm", broken)
    state = await editor.process(
        {"answer": "original", "validator_errors": ["Too short"]}
    )
    assert state["editor_failed"] is True
    assert state["answer"] == "original"
