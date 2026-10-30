"""Rule-based Validator scenarios."""

from backend.agents.validator import Validator


async def test_valid_answer_passes() -> None:
    state = await Validator().process(
        {
            "question": "What is a list?",
            "answer": "A list is a mutable ordered collection in Python.",
            "sources": ["https://docs.python.org/3/library/stdtypes.html"],
        }
    )
    assert state["validation_passed"] is True
    assert state["validator_errors"] == []


async def test_missing_question_fails() -> None:
    state = await Validator().process({"answer": "A sufficiently long answer."})
    assert "Question is required" in state["validator_errors"]


async def test_short_answer_fails() -> None:
    state = await Validator().process({"question": "Q", "answer": "short"})
    assert "Answer is too short" in state["validator_errors"]


async def test_placeholder_fails() -> None:
    state = await Validator().process(
        {"question": "Q", "answer": "TODO: provide a sufficiently long answer"}
    )
    assert "Answer contains a placeholder" in state["validator_errors"]


async def test_unclosed_code_fence_fails() -> None:
    state = await Validator().process(
        {"question": "Q", "answer": "Here is an example:\n```python\nprint('x')"}
    )
    assert "Unclosed Markdown code fence" in state["validator_errors"]


async def test_missing_sources_warns_without_failing() -> None:
    state = await Validator().process(
        {"question": "Q", "answer": "This answer is comfortably long enough."}
    )
    assert state["validation_passed"] is True
    assert "No supporting sources were attached" in state["validator_warnings"]
