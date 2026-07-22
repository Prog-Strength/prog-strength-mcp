"""Tests for the Whoop recovery MCP surface.

Two boundaries are exercised:

* The API client (`get_whoop_recovery`): HTTP is mocked with respx and
  we assert the path/method/params/headers and that the payload under
  `data` is forwarded verbatim.
* The MCP tool boundary: the registered tool raises a `RuntimeError`
  mentioning Authorization when the inbound request carries no
  Authorization header (an `_ExplodingAPI` sentinel raises if forwarding
  is attempted), and surfaces an `APIError` from the client as a
  `RuntimeError` carrying the status code.
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

    mcp = FastMCP("test")
    whoop.register(mcp, _ExplodingAPI())

    recovery_tool = await mcp.get_tool("get_whoop_recovery")

    with pytest.raises(RuntimeError, match="Authorization"):
        await recovery_tool.fn(timezone="America/Denver")


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

    mcp = FastMCP("test")
    whoop.register(mcp, _FailingAPI())

    recovery_tool = await mcp.get_tool("get_whoop_recovery")

    with pytest.raises(RuntimeError, match="500"):
        await recovery_tool.fn(timezone="America/Denver")
