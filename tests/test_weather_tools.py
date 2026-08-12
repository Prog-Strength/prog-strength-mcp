"""Tests for the weather forecast forwarder.

The OpenWeather provider, the durable daily call budget, the
coordinate-keyed cache and the saved-location lookup all live in
prog-strength-api — this layer is a transparent forwarder, so the
contract pinned here is plumbing only:

* APIClient.get_weather_forecast builds the exact query params
  (including `source=agent`) and Authorization header for GET /weather,
  unwraps `data`, and carries the envelope's machine-readable `code`
  onto APIError so the tool layer can branch on it.
"""

import httpx
import pytest
import respx

from prog_strength_mcp.api_client import APIClient, APIError

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"

FORECAST_PAYLOAD = {
    "status": "ok",
    "location": {"id": "", "label": "Boulder", "state": "CO", "country": "US"},
    "fetched_at": "2026-08-12T13:02:11Z",
    "units": {"temp": "F", "wind": "mph"},
    "current": {
        "temp": 71,
        "feels_like": 69,
        "humidity": 32,
        "wind_speed": 8,
        "condition": "Clear",
        "icon": "01d",
    },
    "today": {
        "high": 94,
        "low": 61,
        "sunrise": "2026-08-12T12:12:00Z",
        "sunset": "2026-08-13T02:04:00Z",
    },
    "hourly": [{"at": "2026-08-12T14:00:00Z", "temp": 74, "icon": "01d"}],
    "daily": [
        {
            "at": "2026-08-12T06:00:00Z",
            "high": 94,
            "low": 61,
            "condition": "Clear",
            "icon": "01d",
            "precip_chance": 10,
            "wind_speed": 9,
            "humidity": 28,
            "sunrise": "2026-08-12T12:12:00Z",
            "sunset": "2026-08-13T02:04:00Z",
        }
    ],
}


# --- API client --------------------------------------------------------


@respx.mock
async def test_forecast_forwards_params_and_auth():
    route = respx.get(f"{BASE_URL}/weather").mock(
        return_value=httpx.Response(
            200,
            json={"data": FORECAST_PAYLOAD},
            headers={"X-Request-ID": "req-weather-1"},
        )
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_weather_forecast(AUTH, timezone="America/Denver", place="Boulder")

    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    params = dict(httpx.URL(str(req.url)).params)
    # source=agent splits the shared budget's Grafana attribution between
    # the dashboard tile and chat; it is always sent from this client.
    assert params == {
        "timezone": "America/Denver",
        "source": "agent",
        "place": "Boulder",
    }
    # The API's correlation id rides along for CloudWatch tracing.
    assert result == {**FORECAST_PAYLOAD, "request_id": "req-weather-1"}


@respx.mock
async def test_forecast_omits_place_when_not_given():
    """An omitted place must be absent from the query string, not sent
    empty — the API reads a present-but-blank `place` as a selector."""
    route = respx.get(f"{BASE_URL}/weather").mock(
        return_value=httpx.Response(200, json={"data": FORECAST_PAYLOAD})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.get_weather_forecast(AUTH, timezone="America/Denver")

    params = dict(httpx.URL(str(route.calls.last.request.url)).params)
    assert params == {"timezone": "America/Denver", "source": "agent"}


@respx.mock
async def test_forecast_raises_apierror_with_envelope_code_and_request_id():
    respx.get(f"{BASE_URL}/weather").mock(
        return_value=httpx.Response(
            404,
            json={"error": "no saved locations", "code": "no_locations"},
            headers={"X-Request-ID": "req-2"},
        )
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as exc:
            await api.get_weather_forecast(AUTH, timezone="America/Denver")

    assert exc.value.status_code == 404
    # The human message is not a contract; the code is what the tool branches on.
    assert exc.value.code == "no_locations"
    # Failures are traceable too.
    assert exc.value.request_id == "req-2"


@respx.mock
async def test_forecast_survives_unparseable_error_body():
    """A gateway error arrives as plain text, not the API envelope — the
    client must surface it rather than blow up parsing JSON."""
    respx.get(f"{BASE_URL}/weather").mock(
        return_value=httpx.Response(502, text="upstream connect error")
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as exc:
            await api.get_weather_forecast(AUTH, timezone="America/Denver")

    assert exc.value.status_code == 502
    assert exc.value.code == ""
    assert exc.value.message == "upstream connect error"
