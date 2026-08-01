"""Tests for the blood-pressure MCP surface.

Two boundaries are exercised:

* The API client (`log_blood_pressure`, `list_blood_pressure`): HTTP is
  mocked with respx and we assert the path/method/body/headers and that
  the payload under `data` is forwarded verbatim.
* The MCP tool boundary: the registered tools raise a `RuntimeError`
  mentioning Authorization when the inbound request carries no
  Authorization header (an `_ExplodingAPI` sentinel raises if forwarding
  is attempted), and surface an `APIError` from the client as a
  `RuntimeError` carrying the status code.
"""

import httpx
import pytest
import respx

from prog_strength_mcp import blood_pressure
from prog_strength_mcp.api_client import APIClient, APIError

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"

_SAMPLE_ENTRY = {
    "id": "bp_1a2",
    "systolic": 122,
    "diastolic": 78,
    "pulse": 64,
    "measured_at": "2026-06-14T07:10:00Z",
    "created_at": "2026-06-14T07:10:00Z",
}


# --- API client: log_blood_pressure -----------------------------------


@respx.mock
async def test_log_blood_pressure_posts_body_and_forwards_auth():
    route = respx.post(f"{BASE_URL}/blood-pressure").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_ENTRY})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.log_blood_pressure(AUTH, systolic=122, diastolic=78)

    assert result == _SAMPLE_ENTRY
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    import json

    assert json.loads(req.content) == {"systolic": 122, "diastolic": 78}


@respx.mock
async def test_log_blood_pressure_includes_pulse_and_measured_at_when_set():
    route = respx.post(f"{BASE_URL}/blood-pressure").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_ENTRY})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.log_blood_pressure(
            AUTH,
            systolic=122,
            diastolic=78,
            pulse=64,
            measured_at="2026-06-14T07:10:00Z",
        )

    req = route.calls.last.request
    import json

    assert json.loads(req.content) == {
        "systolic": 122,
        "diastolic": 78,
        "pulse": 64,
        "measured_at": "2026-06-14T07:10:00Z",
    }


@respx.mock
async def test_log_blood_pressure_non_dict_data_yields_empty():
    respx.post(f"{BASE_URL}/blood-pressure").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.log_blood_pressure(AUTH, systolic=122, diastolic=78)

    assert result == {}


@respx.mock
async def test_log_blood_pressure_surfaces_api_error():
    respx.post(f"{BASE_URL}/blood-pressure").mock(
        return_value=httpx.Response(500, json={"error": "db exploded"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.log_blood_pressure(AUTH, systolic=122, diastolic=78)

    assert excinfo.value.status_code == 500
    assert excinfo.value.message == "db exploded"


# --- API client: list_blood_pressure ----------------------------------


@respx.mock
async def test_list_blood_pressure_forwards_range_and_unwraps_data():
    route = respx.get(f"{BASE_URL}/blood-pressure").mock(
        return_value=httpx.Response(200, json={"data": [_SAMPLE_ENTRY]})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.list_blood_pressure(
            AUTH, since="2026-06-01T00:00:00Z", until="2026-06-14T00:00:00Z"
        )

    assert result == [_SAMPLE_ENTRY]
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    assert req.url.params["since"] == "2026-06-01T00:00:00Z"
    assert req.url.params["until"] == "2026-06-14T00:00:00Z"


@respx.mock
async def test_list_blood_pressure_non_list_data_yields_empty():
    respx.get(f"{BASE_URL}/blood-pressure").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.list_blood_pressure(AUTH)

    assert result == []


@respx.mock
async def test_list_blood_pressure_surfaces_api_error():
    respx.get(f"{BASE_URL}/blood-pressure").mock(
        return_value=httpx.Response(500, json={"error": "db exploded"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.list_blood_pressure(AUTH)

    assert excinfo.value.status_code == 500
    assert excinfo.value.message == "db exploded"


# --- Tool boundary: Authorization is required before any HTTP call ----


async def test_blood_pressure_tools_require_auth(monkeypatch):
    """The auth guard fires (RuntimeError) before any HTTP forwarding when
    the inbound request carries no Authorization header. _ExplodingAPI
    raises AssertionError if HTTP were attempted.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(blood_pressure, "get_http_headers", lambda **_: {})

    class _ExplodingAPI:
        async def log_blood_pressure(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

        async def list_blood_pressure(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

    mcp = FastMCP("test")
    blood_pressure.register(mcp, _ExplodingAPI())

    log_tool = await mcp.get_tool("log_blood_pressure")
    list_tool = await mcp.get_tool("list_blood_pressure")

    with pytest.raises(RuntimeError, match="Authorization"):
        await log_tool.fn(systolic=122, diastolic=78)
    with pytest.raises(RuntimeError, match="Authorization"):
        await list_tool.fn()


# --- Tool boundary: APIError surfaces as RuntimeError with status ------


async def test_blood_pressure_tools_map_api_error(monkeypatch):
    """An APIError from the client surfaces to the model as a plain
    RuntimeError with the status code in the message.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(
        blood_pressure,
        "get_http_headers",
        lambda **_: {"authorization": AUTH},
    )

    class _FailingAPI:
        async def log_blood_pressure(self, *a, **k):
            raise APIError(500, "db exploded")

        async def list_blood_pressure(self, *a, **k):
            raise APIError(500, "db exploded")

    mcp = FastMCP("test")
    blood_pressure.register(mcp, _FailingAPI())

    log_tool = await mcp.get_tool("log_blood_pressure")
    list_tool = await mcp.get_tool("list_blood_pressure")

    with pytest.raises(RuntimeError, match="500"):
        await log_tool.fn(systolic=122, diastolic=78)
    with pytest.raises(RuntimeError, match="500"):
        await list_tool.fn()
