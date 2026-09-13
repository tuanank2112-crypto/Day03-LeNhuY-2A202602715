import json
import math
import os
from typing import Any, Dict, List, Optional

RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "raw-data")


def _normalize_code(value: Any) -> str:
    """Return a canonical airport/city code, or an empty string for invalid input."""
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _normalize_max_price(value: Any) -> Optional[float]:
    """Parse a non-negative VND price limit without accepting booleans or NaN."""
    if isinstance(value, bool):
        return None

    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return None

    try:
        price = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(price) or price < 0:
        return None
    return price


def get_flight_info(origin: str, destination: str, max_price: int = 5000000) -> List[Dict[str, Any]]:
    """
    Search for flights matching origin, destination, and budget constraint.
    """
    normalized_origin = _normalize_code(origin)
    normalized_destination = _normalize_code(destination)
    normalized_max_price = _normalize_max_price(max_price)
    if not normalized_origin or not normalized_destination or normalized_max_price is None:
        return []

    flight_file = os.path.join(RAW_DATA_DIR, "flight_data.json")
    if not os.path.exists(flight_file):
        return []

    try:
        with open(flight_file, "r", encoding="utf-8") as f:
            flights = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []

    if not isinstance(flights, list):
        return []

    results = []
    for flight in flights:
        if not isinstance(flight, dict):
            continue

        flight_price = _normalize_max_price(flight.get("price_vnd"))
        if (
            _normalize_code(flight.get("origin")) == normalized_origin
            and _normalize_code(flight.get("destination")) == normalized_destination
            and flight_price is not None
            and flight_price <= normalized_max_price
        ):
            results.append(flight)
    return results

def get_weather_forecast(city_code: str) -> Dict[str, Any]:
    """
    Get weather forecast and outfit recommendation for a city code (e.g. SGN, HAN, DAD).
    """
    normalized_city_code = _normalize_code(city_code)
    if not normalized_city_code:
        return {"error": "Invalid city code"}

    weather_file = os.path.join(RAW_DATA_DIR, "weather_data.json")
    if not os.path.exists(weather_file):
        return {"error": "Weather data not found"}

    try:
        with open(weather_file, "r", encoding="utf-8") as f:
            weather_data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"error": "Weather data unavailable"}

    if not isinstance(weather_data, dict):
        return {"error": "Weather data unavailable"}

    weather = weather_data.get(normalized_city_code)
    if isinstance(weather, dict):
        return weather
    return {"error": f"No data for {normalized_city_code}"}

# Tool Registry for ReAct Agent
TOOL_DEFINITIONS = [
    {
        "name": "get_flight_info",
        "description": "Tìm chuyến bay theo điểm đi, điểm đến và giá tối đa.",
        "parameters": {
            "origin": "Mã sân bay đi (VD: HAN)",
            "destination": "Mã sân bay đến (VD: SGN)",
            "max_price": "Giá vé tối đa dạng số nguyên (VND)"
        }
    },
    {
        "name": "get_weather_forecast",
        "description": "Lấy thông tin thời tiết và gợi ý trang phục theo mã sân bay/thành phố (SGN, HAN, DAD).",
        "parameters": {
            "city_code": "Mã sân bay thành phố (VD: SGN)"
        }
    }
]

TOOL_MAP = {
    "get_flight_info": get_flight_info,
    "get_weather_forecast": get_weather_forecast
}
