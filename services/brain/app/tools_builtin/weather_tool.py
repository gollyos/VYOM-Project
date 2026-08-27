from __future__ import annotations

from typing import Any

import httpx

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo WMO weather codes -> plain-English condition text, so VYOM can
# speak a natural sentence instead of reciting a numeric code.
WMO_CONDITIONS: dict[int, str] = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snow fall", 73: "moderate snow fall", 75: "heavy snow fall",
    77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}


def _condition_for(code: Any) -> str:
    try:
        return WMO_CONDITIONS.get(int(code), "unknown conditions")
    except (TypeError, ValueError):
        return "unknown conditions"


class WeatherTool(BaseTool):
    """Free, no-API-key weather lookups via Open-Meteo (geocoding + forecast).
    Read-only informational query, so every action is L0."""

    metadata = ToolMetadata(
        name="weather",
        description=(
            "Look up current weather or a multi-day forecast for a city (or lat/lon) "
            "using the free, keyless Open-Meteo API. Actions: current, forecast."
        ),
        category="research",
        required_permissions=[PermissionLevel.L0],
        risk_level="low",
    )

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L0

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            if self._client is not None:
                response = await self._client.get(url, params=params)
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ToolValidationError(f"Weather lookup failed: could not reach Open-Meteo ({exc})") from exc
        if response.status_code >= 400:
            raise ToolValidationError(f"Weather lookup failed: Open-Meteo returned {response.status_code}")
        return response.json()

    async def _resolve_location(self, inputs: dict[str, Any]) -> tuple[float, float, str]:
        lat = inputs.get("lat")
        lon = inputs.get("lon")
        if lat is not None and lon is not None:
            return float(lat), float(lon), str(inputs.get("location") or f"{lat},{lon}")
        city = str(inputs.get("location") or inputs.get("city") or "").strip()
        if not city:
            raise ToolValidationError("A city name (location) or lat/lon is required")
        geo = await self._get_json(GEOCODE_URL, {"name": city, "count": 1, "language": "en", "format": "json"})
        results = geo.get("results") or []
        if not results:
            raise ToolValidationError(f"Could not find a location matching '{city}'")
        place = results[0]
        label_bits = [place.get("name"), place.get("admin1"), place.get("country")]
        label = ", ".join(bit for bit in label_bits if bit)
        return float(place["latitude"]), float(place["longitude"]), label or city

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", "current"))
        lat, lon, label = await self._resolve_location(inputs)

        if action == "current":
            data = await self._get_json(FORECAST_URL, {
                "latitude": lat, "longitude": lon,
                "current_weather": "true",
                "hourly": "relative_humidity_2m",
                "timezone": "auto",
            })
            current = data.get("current_weather") or {}
            temp = current.get("temperature")
            wind = current.get("windspeed")
            condition = _condition_for(current.get("weathercode"))
            humidity = None
            hourly = data.get("hourly") or {}
            times = hourly.get("time") or []
            humidities = hourly.get("relative_humidity_2m") or []
            current_time = current.get("time")
            if current_time in times:
                humidity = humidities[times.index(current_time)]
            output = {
                "location": label, "latitude": lat, "longitude": lon,
                "temperature_c": temp, "condition": condition,
                "wind_speed_kmh": wind, "humidity_percent": humidity,
                "observed_at": current_time,
            }
            humidity_bit = f", humidity {humidity}%" if humidity is not None else ""
            summary = (
                f"{label}: {temp}\u00b0C, {condition}, wind {wind} km/h{humidity_bit}"
            )
        elif action == "forecast":
            days = int(inputs.get("days", 3))
            days = max(1, min(days, 16))
            data = await self._get_json(FORECAST_URL, {
                "latitude": lat, "longitude": lon,
                "daily": "weathercode,temperature_2m_max,temperature_2m_min,windspeed_10m_max",
                "timezone": "auto",
                "forecast_days": days,
            })
            daily = data.get("daily") or {}
            dates = daily.get("time") or []
            codes = daily.get("weathercode") or []
            highs = daily.get("temperature_2m_max") or []
            lows = daily.get("temperature_2m_min") or []
            winds = daily.get("windspeed_10m_max") or []
            days_out = []
            for i, date in enumerate(dates):
                days_out.append({
                    "date": date,
                    "condition": _condition_for(codes[i] if i < len(codes) else None),
                    "high_c": highs[i] if i < len(highs) else None,
                    "low_c": lows[i] if i < len(lows) else None,
                    "max_wind_kmh": winds[i] if i < len(winds) else None,
                })
            output = {"location": label, "latitude": lat, "longitude": lon, "days": days_out}
            if days_out:
                first = days_out[0]
                summary = (
                    f"{label} forecast: today {first['condition']}, "
                    f"high {first['high_c']}\u00b0C / low {first['low_c']}\u00b0C"
                    + (f", plus {len(days_out) - 1} more day(s)" if len(days_out) > 1 else "")
                )
            else:
                summary = f"{label}: no forecast data available"
        else:
            raise ToolValidationError("Unsupported weather action (use 'current' or 'forecast')")

        evidence = EvidenceItem(type="tool_result", summary=f"Weather {action} for {label}", data=output)
        return ToolResult.completed(summary, output=output, evidence=[evidence])