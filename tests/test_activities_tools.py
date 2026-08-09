"""Tests for the canonical unified-activity MCP tools (log_activity,
list_activities, get_activity).

Covers the tool boundary the way test_running_tools.py does:

* the auth guard fires (RuntimeError mentioning Authorization) before any
  HTTP forwarding when the inbound request carries no Authorization header;
* param forwarding — log_activity builds the unified body (defaulting
  start_time to now when omitted) and list_activities forwards its type /
  limit filters (and exposes NO date-range params — house rule: the model
  never constructs UTC bounds for a user-local day);
* get_activity's response shaping — trackpoints and the route are dropped
  before the model sees them, the aggregate series survive, and an `ok`
  weather row comes back in both unit systems;
* an APIError (e.g. a 422 unknown type, a 404 activity) surfaces as a plain
  RuntimeError carrying the status.
"""

import json as _json

import httpx
import pytest
import respx
from fastmcp import FastMCP

from prog_strength_mcp import activities
from prog_strength_mcp.api_client import APIClient, APIError

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"

_ACTIVITY = {
    "id": "act_1",
    "activity_type": "other",
    "start_time": "2026-05-16T18:30:00Z",
    "summary": {"title": "Yoga", "subtitle": "", "metrics": []},
}

# A full outdoor-run detail read: the aggregates the agent reasons over, the
# rendering data get_activity must strip, and an `ok` weather row.
_DETAIL = {
    "id": "act_run_1",
    "activity_type": "running",
    "start_time": "2025-07-12T18:07:00Z",
    "summary": {"title": "Evening run", "subtitle": "6.2 mi", "metrics": []},
    "details": {"distance_meters": 10000, "environment": "outdoor"},
    "splits": [{"index": 1, "duration_seconds": 350}],
    "strip_summary": {"distance": "6.21 mi", "pace": "9:23 /mi"},
    "heart_rate_zones": [{"zone": 2, "seconds": 900}],
    "intervals": [{"index": 1, "duration_seconds": 300}],
    "trackpoints": [{"latitude": 40.1, "longitude": -74.2, "heart_rate": 150}],
    "route": {"type": "LineString", "coordinates": [[-74.2, 40.1], [-74.3, 40.2]]},
    "weather": {
        "status": "ok",
        "observed_at": "2025-07-12T18:00:00Z",
        "temp_c": 31.1,
        "feels_like_c": 36.4,
        "dew_point_c": 21.7,
        "humidity": 58,
        "wind_kmh": 14.5,
        "wind_deg": 210,
        "precip_mm": 0,
        "condition": "Clear",
        "icon": "01d",
    },
}


def _detail_with(**overrides):
    """A copy of _DETAIL with keys replaced, or removed when the value is
    None — so a case can say "this activity has no weather key at all".
    """
    out = {**_DETAIL, **overrides}
    return {k: v for k, v in out.items() if v is not None}


def _register(monkeypatch, api, *, auth=AUTH):
    headers = {"authorization": auth} if auth else {}
    monkeypatch.setattr(activities, "get_http_headers", lambda **_: headers)
    mcp = FastMCP("test")
    activities.register(mcp, api)
    return mcp


# --- Auth guard -------------------------------------------------------


class _ExplodingAPI:
    async def create_activity(self, *a, **k):  # pragma: no cover
        raise AssertionError("HTTP forwarding must not happen on missing auth")

    async def list_activities(self, *a, **k):  # pragma: no cover
        raise AssertionError("HTTP forwarding must not happen on missing auth")

    async def get_activity(self, *a, **k):  # pragma: no cover
        raise AssertionError("HTTP forwarding must not happen on missing auth")


async def test_log_activity_requires_auth(monkeypatch):
    mcp = _register(monkeypatch, _ExplodingAPI(), auth=None)
    tool = await mcp.get_tool("log_activity")
    with pytest.raises(RuntimeError, match="Authorization"):
        await tool.fn(activity_type="other")


async def test_list_activities_requires_auth(monkeypatch):
    mcp = _register(monkeypatch, _ExplodingAPI(), auth=None)
    tool = await mcp.get_tool("list_activities")
    with pytest.raises(RuntimeError, match="Authorization"):
        await tool.fn()


async def test_get_activity_requires_auth(monkeypatch):
    mcp = _register(monkeypatch, _ExplodingAPI(), auth=None)
    tool = await mcp.get_tool("get_activity")
    with pytest.raises(RuntimeError, match="Authorization"):
        await tool.fn(activity_id="act_run_1")


# --- log_activity: payload building -----------------------------------


@respx.mock
async def test_log_activity_builds_payload_and_defaults_start_time(monkeypatch):
    route = respx.post(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(201, json={"data": _ACTIVITY})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("log_activity")
        result = await tool.fn(
            activity_type="running",
            duration_seconds=1800,
            name="Morning run",
            details={"distance_meters": 5000},
        )

    assert result == _ACTIVITY
    body = _json.loads(route.calls.last.request.content)
    assert body["activity_type"] == "running"
    assert body["duration_seconds"] == 1800
    assert body["name"] == "Morning run"
    assert body["details"] == {"distance_meters": 5000}
    # start_time is required by the API, so it's defaulted to a non-empty
    # RFC3339 instant when omitted.
    assert isinstance(body["start_time"], str) and body["start_time"].endswith("Z")
    assert "notes" not in body


@respx.mock
async def test_log_activity_forwards_explicit_start_time(monkeypatch):
    route = respx.post(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(201, json={"data": _ACTIVITY})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("log_activity")
        await tool.fn(activity_type="other", start_time="2026-05-16T18:30:00Z")

    body = _json.loads(route.calls.last.request.content)
    assert body["start_time"] == "2026-05-16T18:30:00Z"
    assert "details" not in body


async def test_log_activity_maps_unknown_type_error(monkeypatch):
    class _FailingAPI:
        async def create_activity(self, *a, **k):
            raise APIError(422, 'unknown activity type "swimming"')

    mcp = _register(monkeypatch, _FailingAPI())
    tool = await mcp.get_tool("log_activity")
    with pytest.raises(RuntimeError, match="422"):
        await tool.fn(activity_type="swimming")


# --- list_activities: param forwarding --------------------------------


@respx.mock
async def test_list_activities_forwards_type(monkeypatch):
    route = respx.get(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(200, json={"data": {"activities": [_ACTIVITY],
                                                        "next_before": None}})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("list_activities")
        result = await tool.fn(activity_type="running")

    assert result == [_ACTIVITY]
    assert route.calls.last.request.url.params["type"] == "running"


@respx.mock
async def test_list_activities_forwards_limit(monkeypatch):
    route = respx.get(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(200, json={"data": {"activities": [], "next_before": None}})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("list_activities")
        await tool.fn(limit=5)

    params = route.calls.last.request.url.params
    assert params["limit"] == "5"
    assert "since" not in params
    assert "until" not in params


async def test_list_activities_exposes_no_date_range_params(monkeypatch):
    """The tool contract deliberately has NO since/until/before/date params —
    the model must never construct UTC bounds for a user-local day (house
    rule); date-scoped questions route through get_training_snapshot.
    """
    mcp = _register(monkeypatch, _ExplodingAPI())
    tool = await mcp.get_tool("list_activities")
    props = tool.parameters.get("properties", {})
    assert set(props) == {"activity_type", "limit"}


async def test_list_activities_maps_api_error(monkeypatch):
    class _FailingAPI:
        async def list_activities(self, *a, **k):
            raise APIError(400, "limit must be a positive integer")

    mcp = _register(monkeypatch, _FailingAPI())
    tool = await mcp.get_tool("list_activities")
    with pytest.raises(RuntimeError, match="400"):
        await tool.fn(limit=-1)


# --- get_activity: response shaping -----------------------------------


class _StubAPI:
    """Returns a fixed detail payload without HTTP, so a test can assert on
    the exact object the tool was handed (e.g. that it wasn't mutated).
    """

    def __init__(self, detail):
        self.detail = detail
        self.calls = []

    async def get_activity(self, auth_header, activity_id):
        self.calls.append((auth_header, activity_id))
        return self.detail


@respx.mock
async def test_get_activity_strips_trackpoints_and_route(monkeypatch):
    """Both are rendering data — hundreds of per-second samples and a GeoJSON
    geometry — and would dominate the response on a long run.
    """
    route = respx.get(f"{BASE_URL}/activities/act_run_1").mock(
        return_value=httpx.Response(200, json={"data": _DETAIL})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("get_activity")
        result = await tool.fn(activity_id="act_run_1")

    assert route.called
    assert route.calls.last.request.headers["authorization"] == AUTH
    assert "trackpoints" not in result
    assert "route" not in result
    # The rest of the DTO is untouched.
    assert result["id"] == "act_run_1"
    assert result["details"] == _DETAIL["details"]


@respx.mock
async def test_get_activity_keeps_aggregate_series(monkeypatch):
    """splits / strip_summary / heart_rate_zones / intervals are already
    aggregates and are exactly what the agent can reason about.
    """
    respx.get(f"{BASE_URL}/activities/act_run_1").mock(
        return_value=httpx.Response(200, json={"data": _DETAIL})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("get_activity")
        result = await tool.fn(activity_id="act_run_1")

    assert result["splits"] == _DETAIL["splits"]
    assert result["strip_summary"] == _DETAIL["strip_summary"]
    assert result["heart_rate_zones"] == _DETAIL["heart_rate_zones"]
    assert result["intervals"] == _DETAIL["intervals"]


@respx.mock
async def test_get_activity_returns_weather_in_both_unit_systems(monkeypatch):
    respx.get(f"{BASE_URL}/activities/act_run_1").mock(
        return_value=httpx.Response(200, json={"data": _DETAIL})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("get_activity")
        weather = (await tool.fn(activity_id="act_run_1"))["weather"]

    # 31.1 °C -> 87.98 °F, 36.4 -> 97.52, 21.7 -> 71.06, 14.5 km/h -> 9.0099 mph.
    assert weather["temp_f"] == pytest.approx(88.0)
    assert weather["feels_like_f"] == pytest.approx(97.5)
    assert weather["dew_point_f"] == pytest.approx(71.1)
    assert weather["wind_mph"] == pytest.approx(9.0)
    # The metric fields stay, and everything else passes through unconverted.
    assert weather["temp_c"] == pytest.approx(31.1)
    assert weather["wind_kmh"] == pytest.approx(14.5)
    assert weather["humidity"] == 58
    assert weather["wind_deg"] == 210
    assert weather["precip_mm"] == 0
    assert weather["condition"] == "Clear"
    assert weather["icon"] == "01d"
    assert weather["observed_at"] == "2025-07-12T18:00:00Z"


@respx.mock
async def test_get_activity_without_weather_has_no_weather_key(monkeypatch):
    """Absence is the answer. An activity with no stored reading — indoor, no
    GPS, or imported before capture existed — must not raise and must not
    grow an invented "no weather recorded" marker.
    """
    detail = _detail_with(weather=None)
    assert "weather" not in detail
    respx.get(f"{BASE_URL}/activities/act_run_1").mock(
        return_value=httpx.Response(200, json={"data": detail})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("get_activity")
        result = await tool.fn(activity_id="act_run_1")

    assert "weather" not in result
    assert result["id"] == "act_run_1"


@pytest.mark.parametrize("status", ["no_coordinates", "unavailable"])
@respx.mock
async def test_get_activity_passes_non_ok_weather_through(monkeypatch, status):
    """A non-`ok` row carries no readings, so there is nothing to convert —
    inventing Fahrenheit fields would be inventing a measurement.
    """
    respx.get(f"{BASE_URL}/activities/act_run_1").mock(
        return_value=httpx.Response(200, json={"data": _detail_with(weather={"status": status})})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("get_activity")
        result = await tool.fn(activity_id="act_run_1")

    assert result["weather"] == {"status": status}


async def test_get_activity_does_not_mutate_the_payload(monkeypatch):
    """The trim and the conversion build a new dict; the object the client
    handed back is left exactly as the API sent it.
    """
    source = _detail_with()
    api = _StubAPI(source)
    mcp = _register(monkeypatch, api)
    tool = await mcp.get_tool("get_activity")
    result = await tool.fn(activity_id="act_run_1")

    assert api.calls == [(AUTH, "act_run_1")]
    assert result is not source
    assert "trackpoints" in source
    assert "route" in source
    # source["weather"] IS _DETAIL["weather"] (a shallow copy), so an in-place
    # enrichment would show up here — and would leak into every other test.
    assert "temp_f" not in source["weather"]
    assert "wind_mph" not in source["weather"]


async def test_get_activity_maps_not_found_error(monkeypatch):
    class _FailingAPI:
        async def get_activity(self, *a, **k):
            raise APIError(404, "activity not found")

    mcp = _register(monkeypatch, _FailingAPI())
    tool = await mcp.get_tool("get_activity")
    with pytest.raises(RuntimeError, match=r"API error \(404\)"):
        await tool.fn(activity_id="act_missing")
