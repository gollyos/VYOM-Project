"""Tests for the free, keyless Open-Meteo WeatherTool: geocoding + current
weather + forecast, permission tiering, and validation errors. Uses
httpx.MockTransport against realistically-shaped Open-Meteo responses —
never a real network call.
"""
from __future__ import annotations

import httpx
import pytest

from app.schemas.approvals import PermissionLevel
from app.tools.errors import ToolValidationError
from app.tools_builtin.weather_tool import WeatherTool


def _client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _geocode_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "results": [
            {"name": "Mumbai", "admin1": "Maharashtra", "country": "India",
             "latitude": 19.076, "longitude": 72.8777},
        ],
    })


@pytest.mark.asyncio
async def test_current_weather_geocodes_city_and_returns_summary():
    def handler(request: httpx.Request) -> httpx.Response:
        if "geocoding-api" in str(request.url):
            return _geocode_response(request)
        assert "api.open-meteo.com" in str(request.url)
        return httpx.Response(200, json={
            "current_weather": {"temperature": 31.2, "windspeed": 12.5, "weathercode": 1, "time": "2026-08-27T12:00"},
            "hourly": {"time": ["2026-08-27T12:00"], "relative_humidity_2m": [64]},
        })

    tool = WeatherTool(_client_for(handler))
    result = await tool.execute({"action": "current", "location": "Mumbai"}, context=None)

    assert result.success is True
    assert result.structured_output["temperature_c"] == 31.2
    assert result.structured_output["condition"] == "mainly clear"
    assert result.structured_output["humidity_percent"] == 64
    assert "Mumbai" in result.summary
    assert "31.2" in result.summary


@pytest.mark.asyncio
async def test_forecast_returns_multi_day_structured_output():
    def handler(request: httpx.Request) -> httpx.Response:
        if "geocoding-api" in str(request.url):
            return _geocode_response(request)
        return httpx.Response(200, json={
            "daily": {
                "time": ["2026-08-27", "2026-08-28"],
                "weathercode": [2, 61],
                "temperature_2m_max": [33.0, 29.5],
                "temperature_2m_min": [26.0, 24.0],
                "windspeed_10m_max": [15.0, 20.0],
            },
        })

    tool = WeatherTool(_client_for(handler))
    result = await tool.execute({"action": "forecast", "location": "Mumbai", "days": 2}, context=None)

    assert result.success is True
    assert len(result.structured_output["days"]) == 2
    assert result.structured_output["days"][0]["condition"] == "partly cloudy"
    assert result.structured_output["days"][1]["condition"] == "slight rain"
    assert "forecast" in result.summary.lower()


@pytest.mark.asyncio
async def test_lat_lon_input_skips_geocoding():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={
            "current_weather": {"temperature": 20.0, "windspeed": 5.0, "weathercode": 0, "time": "t"},
            "hourly": {"time": [], "relative_humidity_2m": []},
        })

    tool = WeatherTool(_client_for(handler))
    result = await tool.execute({"action": "current", "lat": 19.07, "lon": 72.87}, context=None)

    assert all("geocoding-api" not in url for url in calls)
    assert result.structured_output["condition"] == "clear sky"


@pytest.mark.asyncio
async def test_missing_location_raises_validation_error():
    tool = WeatherTool()
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "current"}, context=None)


@pytest.mark.asyncio
async def test_unknown_city_raises_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    tool = WeatherTool(_client_for(handler))
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "current", "location": "Nowhereville123"}, context=None)


@pytest.mark.asyncio
async def test_network_failure_raises_clear_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    tool = WeatherTool(_client_for(handler))
    with pytest.raises(ToolValidationError, match="Weather lookup failed"):
        await tool.execute({"action": "current", "location": "Mumbai"}, context=None)


@pytest.mark.asyncio
async def test_unsupported_action_raises_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return _geocode_response(request)

    tool = WeatherTool(_client_for(handler))
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "bogus", "location": "Mumbai"}, context=None)


def test_permission_for_is_always_l0():
    tool = WeatherTool()
    assert tool.permission_for({"action": "current"}) == PermissionLevel.L0
    assert tool.permission_for({}) == PermissionLevel.L0
