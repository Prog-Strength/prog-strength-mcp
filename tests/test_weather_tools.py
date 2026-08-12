"""Tests for the weather forecast forwarder.

The OpenWeather provider, the durable daily call budget, the
coordinate-keyed cache and the saved-location lookup all live in
prog-strength-api — this layer is a transparent forwarder, so the
contract pinned here is plumbing only:

* APIClient.get_weather_forecast builds the exact query params
  (including `source=agent`) and Authorization header for GET /weather,
  unwraps `data`, and carries the envelope's machine-readable `code`
  onto APIError so the tool layer can branch on it.
* The tool adapts the API's two 404s (no_locations, place_not_found)
  into the structured dicts the agent prompt is written against, passes
  every degraded `status` through untouched, re-raises other API errors,
  and refuses to run without an Authorization header.
"""

import httpx
import pytest
import respx
from fastmcp import FastMCP

from prog_strength_mcp import weather
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


# --- tool boundary -----------------------------------------------------


class _FakeAPI:
    """Stands in for APIClient at the tool boundary: records the call
    and returns/raises a programmed response. `timezone`/`place` are
    keyword-only so a positional forward is a TypeError here rather than
    a silent pass."""

    def __init__(self, result=None, error: APIError | None = None):
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    async def get_weather_forecast(self, auth_header, *, timezone, place=None):
        self.calls.append({"auth": auth_header, "timezone": timezone, "place": place})
        if self.error is not None:
            raise self.error
        return self.result


async def _tool_fn(monkeypatch, api: _FakeAPI, *, auth: str = AUTH):
    """Register the forecast tool on a fresh FastMCP and return the raw
    callable. Patch `get_http_headers` to supply (or omit) the auth
    header — same pattern as the nutrition-lookup tests."""
    monkeypatch.setattr(
        weather,
        "get_http_headers",
        lambda **_: {"authorization": auth} if auth else {},
    )
    mcp = FastMCP("test")
    weather.register(mcp, api)
    tool = await mcp.get_tool("get_weather_forecast")
    return tool.fn


async def test_tool_forwards_and_returns_forecast(monkeypatch):
    api = _FakeAPI(result=FORECAST_PAYLOAD)
    fn = await _tool_fn(monkeypatch, api)

    result = await fn(timezone="America/Denver", place="Boulder")

    assert result == FORECAST_PAYLOAD
    assert api.calls == [{"auth": AUTH, "timezone": "America/Denver", "place": "Boulder"}]


async def test_tool_forwards_no_place_when_omitted(monkeypatch):
    """Omitting `place` means "the user's own location" — the tool must
    forward None rather than inventing a place name."""
    api = _FakeAPI(result=FORECAST_PAYLOAD)
    fn = await _tool_fn(monkeypatch, api)

    await fn(timezone="America/Denver")

    assert api.calls == [{"auth": AUTH, "timezone": "America/Denver", "place": None}]


async def test_tool_adapts_no_locations_404(monkeypatch):
    api = _FakeAPI(error=APIError(404, "no saved locations", request_id="r-1", code="no_locations"))
    fn = await _tool_fn(monkeypatch, api)

    result = await fn(timezone="America/Denver")

    assert result == {"error": "no_saved_locations", "request_id": "r-1"}


async def test_tool_adapts_place_not_found_404(monkeypatch):
    """The unresolvable name is echoed back so the model can say which
    place it failed on; no request_id key when the error carried none."""
    api = _FakeAPI(error=APIError(404, "place not found", code="place_not_found"))
    fn = await _tool_fn(monkeypatch, api)

    result = await fn(timezone="America/Denver", place="Xyzzyville")

    assert result == {"error": "place_not_found", "place": "Xyzzyville"}


@pytest.mark.parametrize("status", ["disabled", "budget_exhausted", "stale", "unavailable"])
async def test_tool_passes_degraded_status_through(monkeypatch, status):
    """A degraded status is a 200 the API already labelled. The tool must
    not reinterpret it — the model speaks to the status itself."""
    payload = {"status": status}
    api = _FakeAPI(result=payload)
    fn = await _tool_fn(monkeypatch, api)

    result = await fn(timezone="America/Denver")

    assert result == payload


async def test_tool_reraises_non_404_api_errors(monkeypatch):
    api = _FakeAPI(error=APIError(500, "boom"))
    fn = await _tool_fn(monkeypatch, api)

    with pytest.raises(RuntimeError, match=r"API error \(500\)"):
        await fn(timezone="America/Denver")


async def test_tool_reraises_404_with_unrecognized_code(monkeypatch):
    """Only the two documented codes are ordinary states. A 404 the tool
    cannot even provoke (it sends no location_id) is a genuine fault and
    must not be swallowed into a plausible-looking payload."""
    api = _FakeAPI(error=APIError(404, "location not found", code="location_not_found"))
    fn = await _tool_fn(monkeypatch, api)

    with pytest.raises(RuntimeError, match=r"API error \(404\)"):
        await fn(timezone="America/Denver")


async def test_tool_requires_auth_header(monkeypatch):
    api = _FakeAPI(result=FORECAST_PAYLOAD)
    fn = await _tool_fn(monkeypatch, api, auth="")

    with pytest.raises(RuntimeError, match="Authorization"):
        await fn(timezone="America/Denver")
    assert api.calls == []  # no HTTP forwarding without auth


async def test_tool_schema_requires_only_timezone():
    """`timezone` is required and `place` optional in the JSON schema
    FastMCP derives from the signature (`Tool.parameters`, sent to the
    model as the tool's `inputSchema`). The tests around this one invoke
    `.fn` directly and so never exercise that schema. `location_id` is
    deliberately absent — the model has never seen an id."""
    mcp = FastMCP("test")
    weather.register(mcp, _FakeAPI())

    schema = (await mcp.get_tool("get_weather_forecast")).parameters
    assert schema["required"] == ["timezone"]
    assert set(schema["properties"]) == {"timezone", "place"}
