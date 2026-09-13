"""
Lab #3: Baseline Chatbot vs ReAct Agent.

The agent in this file is intentionally an offline, deterministic ReAct
simulation. Its action-selection seam can later be replaced by an LLM without
changing validation, tool dispatch, trace logging, or safeguards.
"""

import argparse
import copy
import inspect
import json
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    from tools import TOOL_DEFINITIONS, TOOL_MAP
except ImportError:  # Supports importing this file as part of a package too.
    from .tools import TOOL_DEFINITIONS, TOOL_MAP


SYSTEM_PROMPT = """Bạn là một ReAct Agent thông minh hỗ trợ khách hàng Vingroup.
Bạn chỉ sử dụng các công cụ sau:
{tools}

Quy trình trả lời bắt buộc:
Thought: <Suy nghĩ bước tiếp theo>
Action: {{"name": "<tên tool>", "args": {{<tham số>}}}}
Observation: <Kết quả từ tool>
... (Lặp lại cho tới khi có đủ dữ liệu)
Final Answer: <Câu trả lời hoàn chỉnh cho khách hàng>
"""


class ChatbotBaseline:
    """A chatbot response that deliberately does not access any tools."""

    def query(self, user_input: str) -> Dict[str, Any]:
        return {
            "status": "success",
            "answer": (
                "Tôi chưa có quyền truy cập dữ liệu chuyến bay hoặc thời tiết "
                "trong chế độ chatbot cơ bản."
            ),
            "tool_calls": [],
        }


RawAction = Union[str, Dict[str, Any], None]
ActionSelector = Callable[[str, Dict[str, Any]], RawAction]


class ReActAgent:
    """Offline ReAct agent with safe JSON action parsing and tool execution."""

    DEFAULT_MAX_PRICE = 5_000_000
    _CITY_ALIASES = {
        "han": "HAN",
        "ha noi": "HAN",
        "hanoi": "HAN",
        "sgn": "SGN",
        "ho chi minh": "SGN",
        "thanh pho ho chi minh": "SGN",
        "tp ho chi minh": "SGN",
        "sai gon": "SGN",
        "dad": "DAD",
        "da nang": "DAD",
    }

    def __init__(
        self,
        max_iterations: int = 5,
        action_selector: Optional[ActionSelector] = None,
    ):
        try:
            self.max_iterations = max(0, int(max_iterations))
        except (TypeError, ValueError):
            self.max_iterations = 5
        self.action_selector = action_selector
        self.trace: List[Dict[str, Any]] = []

    def run(self, user_input: str) -> Dict[str, Any]:
        """Run the Thought-Action-Observation loop for one independent query."""
        # Rebind rather than clear so a result from an earlier run remains stable.
        self.trace = []
        query = user_input if isinstance(user_input, str) else str(user_input)
        state = {
            "intent": self._analyze_query(query),
            "observations": [],
            "attempted_steps": [],
            "action_errors": {},
        }

        if self.max_iterations == 0:
            return self._result(
                status="max_iterations_reached",
                answer="Không thể hoàn thành trong số bước tối đa.",
                iterations=0,
            )

        for iteration in range(1, self.max_iterations + 1):
            thought = self._thought_for(state)
            try:
                raw_action = self._next_action(query, state)
            except Exception as exc:  # A custom selector must not crash the agent.
                observation = {
                    "error": "Action selection failed",
                    "detail": str(exc),
                }
                entry = {
                    "iteration": iteration,
                    "thought": thought,
                    "action": None,
                    "observation": observation,
                }
                answer = "Tôi chưa thể xác định bước tra cứu tiếp theo. Vui lòng thử lại."
                entry["answer"] = answer
                self.trace.append(entry)
                return self._result("completed", answer, iteration)

            selected_final_answer = self._selector_final_answer(raw_action)
            if selected_final_answer is not None:
                entry = {
                    "iteration": iteration,
                    "thought": thought,
                    "action": None,
                    "observation": "Selector returned a final answer.",
                    "answer": selected_final_answer,
                }
                self.trace.append(entry)
                return self._result("completed", selected_final_answer, iteration)

            if raw_action is None:
                answer = self._build_answer(state)
                entry = {
                    "iteration": iteration,
                    "thought": thought,
                    "action": None,
                    "observation": "Đã có đủ thông tin để trả lời.",
                    "answer": answer,
                }
                self.trace.append(entry)
                return self._result("completed", answer, iteration)

            action, observation, is_error = self._execute_action(raw_action)
            entry = {
                "iteration": iteration,
                "thought": thought,
                "action": action,
                "observation": observation,
            }
            self.trace.append(entry)

            tool_name = action.get("name") if action else None
            # Keep every observation, including an action-format error, in
            # state so a later selector can react to it instead of retrying
            # blindly.
            self._record_observation(state, tool_name, observation)

            if is_error:
                error_key = self._action_error_key(raw_action, action)
                error_count = state["action_errors"].get(error_key, 0) + 1
                state["action_errors"][error_key] = error_count
                if error_count >= 2:
                    answer = (
                        "Tôi không thể hoàn thành tra cứu vì cùng một thao tác "
                        "tiếp tục gặp lỗi. Vui lòng kiểm tra thông tin và thử lại."
                    )
                    entry["answer"] = answer
                    return self._result("completed", answer, iteration)

            if self._can_finish_in_current_iteration(state):
                answer = self._build_answer(state)
                entry["answer"] = answer
                return self._result("completed", answer, iteration)

        partial_answer = self._build_answer(state)
        answer = "Không thể hoàn thành trong số bước tối đa."
        if partial_answer:
            answer = f"{answer} Thông tin đã thu thập: {partial_answer}"
        return self._result("max_iterations_reached", answer, self.max_iterations)

    # `_next_action` is the stable seam for an LLM or for robustness tests.
    # It returns a JSON action string, an action dict, or None for Final Answer.
    def _next_action(self, user_input: str, state: Dict[str, Any]) -> RawAction:
        return self._select_action(user_input, state)

    def _select_action(self, user_input: str, state: Dict[str, Any]) -> RawAction:
        """Select an action using an injected selector or the offline policy."""
        if self.action_selector is not None:
            return self.action_selector(user_input, state)
        return self._rule_based_action(state)

    def _rule_based_action(self, state: Dict[str, Any]) -> RawAction:
        intent = state["intent"]
        if intent["is_faq"] or not intent["steps"]:
            return None

        attempted = set(state["attempted_steps"])
        for step in intent["steps"]:
            if step in attempted:
                continue
            if step == "flight":
                return json.dumps(
                    {
                        "name": "get_flight_info",
                        "args": {
                            "origin": intent["origin"],
                            "destination": intent["destination"],
                            "max_price": intent["max_price"],
                        },
                    },
                    ensure_ascii=False,
                )
            if step == "weather":
                return json.dumps(
                    {
                        "name": "get_weather_forecast",
                        "args": {"city_code": intent["weather_city"]},
                    },
                    ensure_ascii=False,
                )
        return None

    def _execute_action(
        self, raw_action: RawAction
    ) -> Tuple[Optional[Dict[str, Any]], Any, bool]:
        action, parse_error = self._parse_action(raw_action)
        if parse_error is not None:
            return None, parse_error, True

        assert action is not None
        tool_name = action["name"]
        if tool_name not in TOOL_MAP:
            return action, {"error": "Unknown tool", "tool": tool_name}, True

        args, argument_error = self._normalise_and_validate_args(tool_name, action["args"])
        action["args"] = args
        if argument_error is not None:
            return action, argument_error, True

        tool = TOOL_MAP[tool_name]
        try:
            signature = inspect.signature(tool)
            signature.bind(**args)
        except TypeError as exc:
            return (
                action,
                {
                    "error": "Invalid tool arguments",
                    "tool": tool_name,
                    "detail": str(exc),
                },
                True,
            )
        except (ValueError, AttributeError):
            # Some callable objects do not expose a signature. The call below
            # still catches a resulting TypeError as a structured tool error.
            pass

        try:
            observation = tool(**args)
        except Exception as exc:
            return (
                action,
                {
                    "error": "Tool execution failed",
                    "tool": tool_name,
                    "detail": str(exc),
                },
                True,
            )

        return action, observation, self._is_error_observation(observation)

    def _parse_action(
        self, raw_action: RawAction
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Any]]:
        if isinstance(raw_action, str):
            try:
                candidate = json.loads(raw_action)
            except (TypeError, ValueError, json.JSONDecodeError):
                return None, "Invalid JSON format"
        elif isinstance(raw_action, dict):
            candidate = copy.deepcopy(raw_action)
        else:
            return None, {
                "error": "Invalid action format",
                "detail": "Action must be a JSON object.",
            }

        if not isinstance(candidate, dict):
            return None, {
                "error": "Invalid action format",
                "detail": "Action must be a JSON object.",
            }

        name = candidate.get("name")
        args = candidate.get("args")
        if not isinstance(name, str) or not name.strip():
            return None, {
                "error": "Invalid action format",
                "detail": "Action name must be a non-empty string.",
            }
        if not isinstance(args, dict):
            return None, {
                "error": "Invalid action format",
                "detail": "Action args must be an object.",
            }

        return {"name": name.strip().lower(), "args": copy.deepcopy(args)}, None

    def _normalise_and_validate_args(
        self, tool_name: str, args: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        normalised = copy.deepcopy(args)

        if tool_name == "get_flight_info":
            for key in ("origin", "destination"):
                if key in normalised:
                    if not isinstance(normalised[key], str) or not normalised[key].strip():
                        return normalised, {
                            "error": "Invalid tool arguments",
                            "tool": tool_name,
                            "detail": f"{key} must be a non-empty string.",
                        }
                    normalised[key] = normalised[key].strip().upper()
            if "max_price" in normalised:
                price = self._coerce_price(normalised["max_price"])
                if price is None:
                    return normalised, {
                        "error": "Invalid tool arguments",
                        "tool": tool_name,
                        "detail": "max_price must be a positive number.",
                    }
                normalised["max_price"] = price

        if tool_name == "get_weather_forecast" and "city_code" in normalised:
            city_code = normalised["city_code"]
            if not isinstance(city_code, str) or not city_code.strip():
                return normalised, {
                    "error": "Invalid tool arguments",
                    "tool": tool_name,
                    "detail": "city_code must be a non-empty string.",
                }
            normalised["city_code"] = city_code.strip().upper()

        return normalised, None

    @staticmethod
    def _is_error_observation(observation: Any) -> bool:
        return isinstance(observation, dict) and bool(observation.get("error"))

    @staticmethod
    def _selector_final_answer(raw_action: RawAction) -> Optional[str]:
        if isinstance(raw_action, dict) and isinstance(raw_action.get("final_answer"), str):
            return raw_action["final_answer"]
        return None

    def _record_observation(
        self, state: Dict[str, Any], tool_name: Optional[str], observation: Any
    ) -> None:
        state["observations"].append({"tool": tool_name, "observation": observation})
        step = {
            "get_flight_info": "flight",
            "get_weather_forecast": "weather",
        }.get(tool_name)
        if step and step not in state["attempted_steps"]:
            state["attempted_steps"].append(step)

    @staticmethod
    def _action_error_key(raw_action: RawAction, action: Optional[Dict[str, Any]]) -> str:
        if action is not None:
            return json.dumps(action, ensure_ascii=False, sort_keys=True, default=str)
        return f"raw:{raw_action!r}"

    def _can_finish_in_current_iteration(self, state: Dict[str, Any]) -> bool:
        """Single-tool questions answer in the same iteration as their tool call."""
        steps = state["intent"]["steps"]
        return len(steps) == 1 and set(steps).issubset(state["attempted_steps"])

    def _thought_for(self, state: Dict[str, Any]) -> str:
        intent = state["intent"]
        pending = [step for step in intent["steps"] if step not in state["attempted_steps"]]
        if pending and pending[0] == "flight":
            return "Tra cứu chuyến bay theo hành trình và ngân sách đã nêu."
        if pending and pending[0] == "weather":
            return "Tra cứu thời tiết tại địa điểm được hỏi."
        if intent["is_faq"]:
            return "Trả lời thận trọng vì không có dữ liệu chính sách chi tiết."
        if intent["missing_message"]:
            return "Xác định thông tin còn thiếu trước khi tra cứu."
        return "Tổng hợp dữ liệu đã quan sát để trả lời khách hàng."

    def _analyze_query(self, query: str) -> Dict[str, Any]:
        normalised = self._fold_text(query)
        occurrences = self._location_occurrences(normalised)
        unique_codes: List[str] = []
        for _, code in occurrences:
            if code not in unique_codes:
                unique_codes.append(code)

        is_faq = any(
            phrase in normalised
            for phrase in ("chinh sach", "doi tra", "hoan ve", "refund policy")
        )
        asks_weather = any(
            phrase in normalised
            for phrase in (
                "thoi tiet",
                "weather",
                "nhiet do",
                "temperature",
                "mac gi",
                "trang phuc",
                "outfit",
            )
        )
        asks_flight = (
            not is_faq
            and (
                any(
                    phrase in normalised
                    for phrase in ("chuyen bay", "flight", "dat ve", "tim ve")
                )
                or bool(re.search(r"\bve\b", normalised))
                or (
                    len(unique_codes) >= 2
                    and bool(re.search(r"\b(tu|from|di|den|toi|to)\b", normalised))
                )
            )
        )

        origin = unique_codes[0] if len(unique_codes) >= 1 else None
        destination = unique_codes[1] if len(unique_codes) >= 2 else None
        weather_city = self._weather_city_from_occurrences(
            normalised, occurrences, destination
        )
        budget = self._extract_budget(normalised) or self.DEFAULT_MAX_PRICE

        missing: List[str] = []
        if asks_flight and (origin is None or destination is None):
            missing.append("điểm đi và điểm đến")
        if asks_weather and weather_city is None:
            missing.append("thành phố cần xem thời tiết")

        steps: List[str] = []
        if asks_flight and origin and destination:
            steps.append("flight")
        if asks_weather and weather_city:
            steps.append("weather")

        missing_message = (
            "Bạn vui lòng cung cấp " + " và ".join(missing) + "." if missing else ""
        )
        return {
            "is_faq": is_faq,
            "asks_flight": asks_flight,
            "asks_weather": asks_weather,
            "origin": origin,
            "destination": destination,
            "weather_city": weather_city,
            "max_price": budget,
            "steps": steps,
            "missing_message": missing_message,
        }

    @classmethod
    def _fold_text(cls, text: str) -> str:
        lowered = text.casefold().replace("đ", "d")
        decomposed = unicodedata.normalize("NFD", lowered)
        return "".join(
            character for character in decomposed if not unicodedata.combining(character)
        )

    def _location_occurrences(self, normalised_query: str) -> List[Tuple[int, str]]:
        occurrences: List[Tuple[int, str]] = []
        for alias, code in sorted(self._CITY_ALIASES.items(), key=lambda item: -len(item[0])):
            for match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", normalised_query):
                occurrences.append((match.start(), code))
        return sorted(occurrences, key=lambda item: item[0])

    @staticmethod
    def _weather_city_from_occurrences(
        normalised_query: str,
        occurrences: List[Tuple[int, str]],
        destination: Optional[str],
    ) -> Optional[str]:
        marker = re.search(
            r"thoi tiet|weather|nhiet do|temperature|mac gi|trang phuc|outfit",
            normalised_query,
        )
        if marker:
            for position, code in occurrences:
                if position >= marker.start():
                    return code
        return destination or (occurrences[0][1] if occurrences else None)

    @classmethod
    def _extract_budget(cls, normalised_query: str) -> Optional[int]:
        number_pattern = re.compile(
            r"(?<!\d)(\d{1,3}(?:[,.]\d{3})+|\d+(?:[,.]\d+)?)\s*"
            r"(trieu|tr|million|k|nghin|ngan|vnd|dong)?\b"
        )
        candidates: List[Tuple[int, int]] = []
        for match in number_pattern.finditer(normalised_query):
            number_text, unit = match.groups()
            value = cls._number_with_unit_to_vnd(number_text, unit)
            if value is not None:
                candidates.append((match.start(), value))

        if not candidates:
            return None
        budget_terms = ("duoi", "toi da", "gia", "ngan sach", "under", "budget")
        for position, value in candidates:
            context = normalised_query[max(0, position - 30) : position]
            if any(term in context for term in budget_terms):
                return value
        return candidates[0][1]

    @staticmethod
    def _number_with_unit_to_vnd(number_text: str, unit: Optional[str]) -> Optional[int]:
        unit = (unit or "").lower()
        try:
            if unit in {"trieu", "tr", "million"}:
                return int(float(number_text.replace(",", ".")) * 1_000_000)
            if unit in {"k", "nghin", "ngan"}:
                return int(float(number_text.replace(",", ".")) * 1_000)
            compact = number_text.replace(",", "").replace(".", "")
            value = int(compact)
            return value if value > 0 else None
        except ValueError:
            return None

    @staticmethod
    def _coerce_price(value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, float):
            return int(value) if value > 0 and value.is_integer() else None
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                parsed = int(stripped)
                return parsed if parsed > 0 else None
        return None

    def _build_answer(self, state: Dict[str, Any]) -> str:
        intent = state["intent"]
        if intent["is_faq"]:
            return (
                "Với vé máy bay Vinpearl, tôi không có dữ liệu chính sách đổi trả "
                "chi tiết trong dữ liệu mô phỏng. Bạn nên kiểm tra điều kiện của "
                "hạng vé hoặc liên hệ nơi bán để được xác nhận."
            )

        observations = state["observations"]
        parts: List[str] = []
        if intent["asks_flight"]:
            flight_observation = self._latest_observation(observations, "get_flight_info")
            if flight_observation is not None:
                parts.append(self._format_flight_answer(flight_observation, intent))
            elif intent["origin"] is None or intent["destination"] is None:
                parts.append(intent["missing_message"])
            else:
                parts.append("Tôi chưa thể hoàn tất tra cứu chuyến bay.")

        if intent["asks_weather"]:
            weather_observation = self._latest_observation(
                observations, "get_weather_forecast"
            )
            if weather_observation is not None:
                parts.append(self._format_weather_answer(weather_observation, intent))
            elif intent["weather_city"] is None:
                if intent["missing_message"] not in parts:
                    parts.append(intent["missing_message"])
            else:
                parts.append("Tôi chưa thể hoàn tất tra cứu thời tiết.")

        if not parts:
            if intent["missing_message"]:
                return intent["missing_message"]
            return "Tôi có thể hỗ trợ tìm chuyến bay hoặc tra cứu thời tiết khi bạn cung cấp thông tin cần thiết."
        return " ".join(part for part in parts if part)

    @staticmethod
    def _latest_observation(
        observations: List[Dict[str, Any]], tool_name: str
    ) -> Optional[Any]:
        for item in reversed(observations):
            if item["tool"] == tool_name:
                return item["observation"]
        return None

    def _format_flight_answer(self, observation: Any, intent: Dict[str, Any]) -> str:
        if self._is_error_observation(observation):
            return f"Tôi chưa thể tra cứu chuyến bay: {self._describe_error(observation)}."
        if not isinstance(observation, list):
            return "Tôi nhận được dữ liệu chuyến bay không hợp lệ."
        if not observation:
            return (
                "Không tìm thấy chuyến bay phù hợp từ "
                f"{intent['origin']} đến {intent['destination']} với giá tối đa "
                f"{self._format_vnd(intent['max_price'])}."
            )

        details: List[str] = []
        for flight in observation:
            if not isinstance(flight, dict):
                continue
            number = flight.get("flight_number", "không rõ mã")
            airline = flight.get("airline", "hãng bay không rõ")
            departure = flight.get("departure_time", "không rõ giờ")
            price = flight.get("price_vnd")
            price_text = self._format_vnd(price) if isinstance(price, (int, float)) else "không rõ giá"
            details.append(f"{number} ({airline}) lúc {departure}, {price_text}")

        if not details:
            return "Tôi nhận được dữ liệu chuyến bay không đầy đủ."
        return "Các chuyến bay phù hợp: " + "; ".join(details) + "."

    def _format_weather_answer(self, observation: Any, intent: Dict[str, Any]) -> str:
        if self._is_error_observation(observation):
            return f"Tôi chưa thể tra cứu thời tiết: {self._describe_error(observation)}."
        if not isinstance(observation, dict):
            return "Tôi nhận được dữ liệu thời tiết không hợp lệ."

        city = observation.get("city", intent.get("weather_city", "địa điểm đã hỏi"))
        temperature = observation.get("temperature_c")
        condition = observation.get("condition")
        humidity = observation.get("humidity_pct")
        recommendation = observation.get("recommendation")
        details = [f"Thời tiết tại {city}"]
        if temperature is not None:
            details.append(f"{temperature}°C")
        if condition:
            details.append(str(condition))
        if humidity is not None:
            details.append(f"độ ẩm {humidity}%")
        answer = ": " + ", ".join(details[1:]) + "." if len(details) > 1 else "."
        if recommendation:
            answer += f" Gợi ý trang phục: {recommendation}"
        return details[0] + answer

    @staticmethod
    def _describe_error(observation: Dict[str, Any]) -> str:
        return str(observation.get("detail") or observation.get("error") or "lỗi không xác định")

    @staticmethod
    def _format_vnd(value: Union[int, float]) -> str:
        return f"{int(value):,} VND".replace(",", ".")

    def _result(self, status: str, answer: str, iterations: int) -> Dict[str, Any]:
        return {
            "status": status,
            "answer": answer,
            "iterations": iterations,
            "trace": copy.deepcopy(self.trace),
        }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Demo offline: Chatbot Baseline vs ReAct Agent")
    parser.add_argument(
        "--query",
        default="Tìm cho tôi chuyến bay từ HAN đi SGN dưới 2 triệu, rồi cho biết thời tiết SGN nên mặc gì?",
        help="Câu hỏi cần chạy qua baseline và agent.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Số vòng ReAct tối đa (mặc định: 5).",
    )
    parser.add_argument(
        "--show-trace",
        action="store_true",
        help="In trace Thought-Action-Observation.",
    )
    args = parser.parse_args(argv)

    print("Dữ liệu mô phỏng cục bộ (không phải tra cứu thời gian thực).")
    print(f"Câu hỏi: {args.query}")

    baseline_result = ChatbotBaseline().query(args.query)
    print("\n=== CHATBOT BASELINE ===")
    print(baseline_result["answer"])

    result = ReActAgent(max_iterations=args.max_iterations).run(args.query)
    print("\n=== REACT AGENT ===")
    print(result["answer"])
    print(f"Status: {result['status']} | Iterations: {result['iterations']}")
    if args.show_trace:
        print("\n=== TRACE ===")
        print(json.dumps(result["trace"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
