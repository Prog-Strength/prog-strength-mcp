"""Tests for the Whoop recovery and sleep MCP surface.

Two boundaries are exercised:

* The API client (`get_whoop_recovery`, `get_whoop_sleep`): HTTP is
  mocked with respx and we assert the path/method/params/headers and
  that the payload under `data` is forwarded verbatim.
* The MCP tool boundary: each registered tool forwards the inbound
  Authorization header and every date argument to *its own* client
  method and hands the result back unchanged; `timezone` is required
  (and `since`/`until` optional) in the schema FastMCP generates from
  the signature; each raises a `RuntimeError` mentioning Authorization
  when the inbound request carries no Authorization header (an
  `_ExplodingAPI` sentinel raises if forwarding is attempted), and
  surfaces an `APIError` from the client as a `RuntimeError` carrying
  the status code.
"""

import httpx
import pytest
import respx

from prog_strength_mcp import whoop
from prog_strength_mcp.api_client import APIClient, APIError

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"

_SAMPLE_RECORD = {
    "date": "2026-06-14",
    "recovery_score": 72,
    "resting_heart_rate": 54,
    "hrv_rmssd_milli": 88.3,
    "cycle_id": "cyc_1a2",
    "sleep_id": "slp_3b4",
    "created_at": "2026-06-14T13:10:00Z",
    "updated_at": "2026-06-14T13:10:00Z",
}

# Durations are milliseconds, exactly as Whoop sends them — the client
# forwards the record verbatim and does no unit conversion.
_SAMPLE_SLEEP_RECORD = {
    "whoop_sleep_id": "b1c2d3e4-0000-4000-8000-000000000001",
    "date": "2026-06-14",
    "is_nap": False,
    "started_at": "2026-06-13T22:40:00Z",
    "ended_at": "2026-06-14T06:15:00Z",
    "timezone_offset": "-06:00",
    "score_state": "SCORED",
    "in_bed_milli": 27300000,
    "awake_milli": 1500000,
    "light_sleep_milli": 13800000,
    "slow_wave_sleep_milli": 5400000,
    "rem_sleep_milli": 6600000,
    "sleep_cycle_count": 5,
    "disturbance_count": 9,
    "need_baseline_milli": 28800000,
    "respiratory_rate": 14.6,
    "performance_pct": 89.0,
    "consistency_pct": 74.0,
    "efficiency_pct": 94.5,
    "created_at": "2026-06-14T13:10:00Z",
    "updated_at": "2026-06-14T13:10:00Z",
}


# --- API client: get_whoop_recovery -----------------------------------


@respx.mock
async def test_get_whoop_recovery_forwards_range_and_unwraps_data():
    payload = {"recovery": [_SAMPLE_RECORD]}
    route = respx.get(f"{BASE_URL}/whoop/recovery").mock(
        return_value=httpx.Response(200, json={"data": payload})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_whoop_recovery(
            AUTH,
            timezone="America/Denver",
            since="2026-06-01",
            until="2026-06-14",
        )

    assert result == payload
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    assert req.url.params["timezone"] == "America/Denver"
    assert req.url.params["since"] == "2026-06-01"
    assert req.url.params["until"] == "2026-06-14"


@respx.mock
async def test_get_whoop_recovery_omits_unset_bounds():
    route = respx.get(f"{BASE_URL}/whoop/recovery").mock(
        return_value=httpx.Response(200, json={"data": {"recovery": []}})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.get_whoop_recovery(AUTH, timezone="America/Denver")

    params = route.calls.last.request.url.params
    assert params["timezone"] == "America/Denver"
    assert "since" not in params
    assert "until" not in params


@respx.mock
async def test_get_whoop_recovery_non_dict_data_yields_empty():
    respx.get(f"{BASE_URL}/whoop/recovery").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_whoop_recovery(AUTH, timezone="America/Denver")

    assert result == {}


@respx.mock
async def test_get_whoop_recovery_surfaces_api_error():
    respx.get(f"{BASE_URL}/whoop/recovery").mock(
        return_value=httpx.Response(500, json={"error": "db exploded"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.get_whoop_recovery(AUTH, timezone="America/Denver")

    assert excinfo.value.status_code == 500
    assert excinfo.value.message == "db exploded"


# --- API client: get_whoop_sleep --------------------------------------


@respx.mock
async def test_get_whoop_sleep_forwards_range_and_unwraps_data():
    payload = {"sleep": [_SAMPLE_SLEEP_RECORD]}
    route = respx.get(f"{BASE_URL}/whoop/sleep").mock(
        return_value=httpx.Response(200, json={"data": payload})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_whoop_sleep(
            AUTH,
            timezone="America/Denver",
            since="2026-06-01",
            until="2026-06-14",
        )

    assert result == payload
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    assert req.url.params["timezone"] == "America/Denver"
    assert req.url.params["since"] == "2026-06-01"
    assert req.url.params["until"] == "2026-06-14"


@respx.mock
async def test_get_whoop_sleep_omits_unset_bounds():
    route = respx.get(f"{BASE_URL}/whoop/sleep").mock(
        return_value=httpx.Response(200, json={"data": {"sleep": []}})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.get_whoop_sleep(AUTH, timezone="America/Denver")

    params = route.calls.last.request.url.params
    assert params["timezone"] == "America/Denver"
    assert "since" not in params
    assert "until" not in params


@respx.mock
async def test_get_whoop_sleep_non_dict_data_yields_empty():
    respx.get(f"{BASE_URL}/whoop/sleep").mock(return_value=httpx.Response(200, json={"data": None}))
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_whoop_sleep(AUTH, timezone="America/Denver")

    assert result == {}


@respx.mock
async def test_get_whoop_sleep_surfaces_api_error():
    respx.get(f"{BASE_URL}/whoop/sleep").mock(
        return_value=httpx.Response(500, json={"error": "db exploded"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.get_whoop_sleep(AUTH, timezone="America/Denver")

    assert excinfo.value.status_code == 500
    assert excinfo.value.message == "db exploded"


# --- Tool boundary: each tool forwards to its own client method -------


async def test_get_whoop_recovery_tool_forwards_args(monkeypatch):
    """The recovery tool calls `api.get_whoop_recovery` — not the sleep
    method — passing the inbound Authorization header and every date
    argument by keyword, and returns the client's payload unchanged.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(whoop, "get_http_headers", lambda **_: {"authorization": AUTH})

    sentinel = {"recovery": [_SAMPLE_RECORD]}

    class _StubAPI:
        async def get_whoop_recovery(self, auth_header, *, timezone, since, until):
            assert auth_header == AUTH
            assert timezone == "America/Denver"
            assert since == "2026-06-01"
            assert until == "2026-06-14"
            return sentinel

        async def get_whoop_sleep(self, *a, **k):  # pragma: no cover
            raise AssertionError("the recovery tool must not call get_whoop_sleep")

    mcp = FastMCP("test")
    whoop.register(mcp, _StubAPI())
    recovery_tool = await mcp.get_tool("get_whoop_recovery")

    result = await recovery_tool.fn(
        timezone="America/Denver",
        since="2026-06-01",
        until="2026-06-14",
    )
    assert result is sentinel


async def test_get_whoop_sleep_tool_forwards_args(monkeypatch):
    """The sleep tool calls `api.get_whoop_sleep` — not the recovery
    method it was modelled on — passing the inbound Authorization header
    and every date argument by keyword, and returns the client's payload
    unchanged.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(whoop, "get_http_headers", lambda **_: {"authorization": AUTH})

    sentinel = {"sleep": [_SAMPLE_SLEEP_RECORD]}

    class _StubAPI:
        async def get_whoop_sleep(self, auth_header, *, timezone, since, until):
            assert auth_header == AUTH
            assert timezone == "America/Denver"
            assert since == "2026-06-01"
            assert until == "2026-06-14"
            return sentinel

        async def get_whoop_recovery(self, *a, **k):  # pragma: no cover
            raise AssertionError("the sleep tool must not call get_whoop_recovery")

    mcp = FastMCP("test")
    whoop.register(mcp, _StubAPI())
    sleep_tool = await mcp.get_tool("get_whoop_sleep")

    result = await sleep_tool.fn(
        timezone="America/Denver",
        since="2026-06-01",
        until="2026-06-14",
    )
    assert result is sentinel


# --- Tool boundary: the generated schema makes timezone required ------


async def test_whoop_tool_schemas_require_only_timezone():
    """`timezone` is required and `since`/`until` optional in the JSON
    schema FastMCP derives from each signature (`Tool.parameters`, sent
    to the model as the tool's `inputSchema`). The tests around this one
    invoke `.fn` directly and so never exercise that schema.
    """
    from fastmcp import FastMCP

    mcp = FastMCP("test")
    whoop.register(mcp, object())

    for name in ("get_whoop_recovery", "get_whoop_sleep"):
        schema = (await mcp.get_tool(name)).parameters
        assert schema["required"] == ["timezone"], name
        assert set(schema["properties"]) == {"timezone", "since", "until"}, name


# --- Tool boundary: Authorization is required before any HTTP call ----


async def test_whoop_tools_require_auth(monkeypatch):
    """The auth guard fires (RuntimeError) before any HTTP forwarding when
    the inbound request carries no Authorization header. _ExplodingAPI
    raises AssertionError if HTTP were attempted.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(whoop, "get_http_headers", lambda **_: {})

    class _ExplodingAPI:
        async def get_whoop_recovery(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

        async def get_whoop_sleep(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

    mcp = FastMCP("test")
    whoop.register(mcp, _ExplodingAPI())

    recovery_tool = await mcp.get_tool("get_whoop_recovery")
    sleep_tool = await mcp.get_tool("get_whoop_sleep")

    with pytest.raises(RuntimeError, match="Authorization"):
        await recovery_tool.fn(timezone="America/Denver")

    with pytest.raises(RuntimeError, match="Authorization"):
        await sleep_tool.fn(timezone="America/Denver")


# --- Tool boundary: APIError surfaces as RuntimeError with status ------


async def test_whoop_tools_map_api_error(monkeypatch):
    """An APIError from the client surfaces to the model as a plain
    RuntimeError with the status code in the message.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(
        whoop,
        "get_http_headers",
        lambda **_: {"authorization": AUTH},
    )

    class _FailingAPI:
        async def get_whoop_recovery(self, *a, **k):
            raise APIError(500, "db exploded")

        async def get_whoop_sleep(self, *a, **k):
            raise APIError(500, "db exploded")

    mcp = FastMCP("test")
    whoop.register(mcp, _FailingAPI())

    recovery_tool = await mcp.get_tool("get_whoop_recovery")
    sleep_tool = await mcp.get_tool("get_whoop_sleep")

    with pytest.raises(RuntimeError, match="500"):
        await recovery_tool.fn(timezone="America/Denver")

    with pytest.raises(RuntimeError, match="500"):
        await sleep_tool.fn(timezone="America/Denver")
