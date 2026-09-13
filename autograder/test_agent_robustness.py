"""Independent robustness checks for the offline ReAct lab implementation.

These tests complement ``test_agent.py``.  They exercise the public agent
contract and the injected action-selection seam, without changing the
provided grader or the sample data.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from collections.abc import Iterable
from typing import Any

import pytest


SOLUTION_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "starter-code")
)
if SOLUTION_DIR not in sys.path:
    sys.path.insert(0, SOLUTION_DIR)

import template as template_module


ReActAgent = template_module.ReActAgent

MULTI_STEP_QUERY = (
    "Tìm cho tôi chuyến bay từ HAN đi SGN dưới 2 triệu, rồi cho biết "
    "thời tiết SGN nên mặc gì?"
)
WEATHER_QUERY = "Thời tiết ở Đà Nẵng DAD hiện tại thế nào?"


def _scripted_selector(actions: Iterable[Any]):
    """Return a selector compatible with the agent's injection seam."""
    action_iterator = iter(actions)

    def selector(*_args: Any, **_kwargs: Any) -> Any:
        return next(action_iterator)

    return selector


def _observation_text(observation: Any) -> str:
    return json.dumps(observation, ensure_ascii=False, sort_keys=True).lower()


def _has_structured_error(observation: Any) -> bool:
    if isinstance(observation, dict):
        return bool({"error", "message", "type"} & set(observation))
    return any(
        marker in _observation_text(observation)
        for marker in ("error", "invalid", "unknown", "exception", "typeerror")
    )


def _assert_trace_contract(result: dict[str, Any]) -> None:
    assert result["status"] in {"completed", "max_iterations_reached"}
    assert isinstance(result["answer"], str)
    assert isinstance(result["trace"], list)
    assert result["iterations"] == len(result["trace"])

    for expected_iteration, entry in enumerate(result["trace"], start=1):
        assert entry["iteration"] == expected_iteration
        assert isinstance(entry["thought"], str)
        assert "action" in entry
        assert "observation" in entry


def _action_name(entry: dict[str, Any]) -> str:
    action = entry["action"]
    assert isinstance(action, dict)
    assert isinstance(action["name"], str)
    return action["name"].strip().lower()


def test_reusing_an_agent_resets_trace_and_keeps_previous_result_stable():
    agent = ReActAgent(max_iterations=5)

    first_result = agent.run(MULTI_STEP_QUERY)
    _assert_trace_contract(first_result)
    saved_first_result = copy.deepcopy(first_result)

    second_result = agent.run(WEATHER_QUERY)
    _assert_trace_contract(second_result)

    # A later run must not append to, replace, or otherwise mutate a result
    # that the caller already received.
    assert first_result == saved_first_result
    assert second_result["iterations"] == 1
    assert len(second_result["trace"]) == 1
    assert "28°C" in second_result["answer"]


def test_lowercase_airports_and_comma_budget_are_normalized():
    agent = ReActAgent(max_iterations=5)

    result = agent.run("Có chuyến bay nào từ han đi dad giá dưới 1,5 triệu không?")

    _assert_trace_contract(result)
    assert result["status"] == "completed"
    assert result["iterations"] == 1
    assert "QH202" in result["answer"]
    assert _action_name(result["trace"][0]) == "get_flight_info"


def test_no_matching_flight_is_a_completed_single_step_not_a_retry():
    agent = ReActAgent(max_iterations=5)

    result = agent.run("Tìm cho tôi chuyến bay từ SGN đi HAN dưới 500k.")

    _assert_trace_contract(result)
    assert result["status"] == "completed"
    assert result["iterations"] == 1
    assert _action_name(result["trace"][0]) == "get_flight_info"
    assert result["trace"][0]["observation"] == []

    answer = result["answer"].lower()
    assert any(message in answer for message in ("không", "khong", "no matching", "not found"))
    assert not any(flight_number in result["answer"] for flight_number in ("VN213", "VJ151", "QH202", "VN110"))


def test_multistep_request_respects_the_exact_iteration_limit():
    agent = ReActAgent(max_iterations=2)

    result = agent.run(MULTI_STEP_QUERY)

    _assert_trace_contract(result)
    assert result["status"] == "max_iterations_reached"
    assert result["iterations"] == 2
    assert len(result["trace"]) == 2


def test_whitespace_and_case_in_a_tool_name_still_dispatches_through_registry(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []
    original_weather_tool = template_module.TOOL_MAP["get_weather_forecast"]

    def tracked_weather_tool(city_code: str) -> dict[str, Any]:
        calls.append(city_code)
        return original_weather_tool(city_code)

    monkeypatch.setitem(
        template_module.TOOL_MAP, "get_weather_forecast", tracked_weather_tool
    )
    agent = ReActAgent(
        max_iterations=5,
        action_selector=_scripted_selector(
            [
                {"name": "  GET_WEATHER_FORECAST  ", "args": {"city_code": "DAD"}},
                None,
            ]
        ),
    )

    result = agent.run(WEATHER_QUERY)

    _assert_trace_contract(result)
    assert result["status"] == "completed"
    assert calls == ["DAD"]
    assert _action_name(result["trace"][0]) == "get_weather_forecast"
    assert "28°C" in result["answer"]


@pytest.mark.parametrize(
    ("scripted_action", "required_words"),
    [
        ("{this is not valid JSON", ("invalid", "json")),
        ({"name": "missing_tool", "args": {}}, ()),
        ({"name": "get_flight_info", "args": {"origin": "HAN"}}, ()),
        ({"name": "get_weather_forecast", "args": "DAD"}, ()),
    ],
    ids=(
        "invalid_json",
        "unknown_tool",
        "missing_tool_arguments",
        "non_object_tool_arguments",
    ),
)
def test_bad_actions_become_error_observations_instead_of_crashing(
    scripted_action: Any, required_words: tuple[str, ...]
):
    agent = ReActAgent(
        max_iterations=5,
        action_selector=_scripted_selector([scripted_action, None]),
    )

    result = agent.run("Kiểm thử action lỗi")

    _assert_trace_contract(result)
    assert result["status"] == "completed"
    assert result["iterations"] <= 2
    error_observations = [
        entry["observation"]
        for entry in result["trace"]
        if _has_structured_error(entry["observation"])
    ]
    assert error_observations
    combined_error_text = " ".join(_observation_text(item) for item in error_observations)
    assert all(word in combined_error_text for word in required_words)


def test_a_tool_exception_is_recorded_and_does_not_leak_stale_data(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []

    def unavailable_weather_tool(city_code: str) -> dict[str, Any]:
        calls.append(city_code)
        raise RuntimeError("simulated weather outage")

    monkeypatch.setitem(
        template_module.TOOL_MAP, "get_weather_forecast", unavailable_weather_tool
    )
    agent = ReActAgent(
        max_iterations=5,
        action_selector=_scripted_selector(
            [{"name": "get_weather_forecast", "args": {"city_code": "DAD"}}, None]
        ),
    )

    result = agent.run("Kiểm thử tool lỗi")

    _assert_trace_contract(result)
    assert result["status"] == "completed"
    assert result["iterations"] <= 2
    assert calls == ["DAD"]
    assert any(_has_structured_error(entry["observation"]) for entry in result["trace"])
    assert "28°C" not in result["answer"]


def test_repeated_identical_errors_stop_after_two_attempts():
    selector_calls = 0
    invalid_action = {"name": "missing_tool", "args": {}}

    def repeating_selector(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal selector_calls
        selector_calls += 1
        return invalid_action

    agent = ReActAgent(max_iterations=5, action_selector=repeating_selector)
    result = agent.run("Kiểm thử safeguard lỗi lặp lại")

    _assert_trace_contract(result)
    assert result["status"] == "completed"
    assert result["iterations"] == 2
    assert selector_calls == 2
    assert all(_has_structured_error(entry["observation"]) for entry in result["trace"])
