"""Tests for the running best-efforts MCP surface.

Two boundaries are exercised:

* The API client (`APIClient.list_running_best_efforts`): HTTP is mocked
  with respx and we assert the GET path/headers and that the
  `{best_efforts: [...]}` payload under `data` is forwarded verbatim.
* The MCP tool boundary: the registered tool raises a `RuntimeError`
  mentioning Authorization when the inbound request carries no
  Authorization header, before any HTTP forwarding. An `_ExplodingAPI`
  sentinel raises AssertionError if forwarding is attempted.
"""

import httpx
import pytest
import respx

from prog_strength_mcp import running
from prog_strength_mcp.api_client import APIClient, APIError

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"

_SAMPLE_BEST_EFFORT = {
    "distance_key": "5k",
    "distance_label": "5K",
    "distance_meters": 5000,
    "duration_seconds": 1184.7,
    "pace_sec_per_km": 236.9,
    "activity_id": "act_2c1",
    "activity_start_time": "2026-04-18T06:45:00Z",
}


# --- API client: list_running_best_efforts ----------------------------


@respx.mock
async def test_list_running_best_efforts_forwards_payload_and_auth():
    payload = {"best_efforts": [_SAMPLE_BEST_EFFORT]}
    route = respx.get(f"{BASE_URL}/running/best-efforts").mock(
        return_value=httpx.Response(200, json={"data": payload})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.list_running_best_efforts(AUTH)

    assert result == payload
    assert route.calls.last.request.headers["Authorization"] == AUTH


@respx.mock
async def test_list_running_best_efforts_non_dict_data_yields_empty():
    """A non-dict `data` (defensive) collapses to {}."""
    respx.get(f"{BASE_URL}/running/best-efforts").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.list_running_best_efforts(AUTH)

    assert result == {}


@respx.mock
async def test_list_running_best_efforts_surfaces_api_error():
    """A non-2xx response becomes an APIError carrying status + message."""
    respx.get(f"{BASE_URL}/running/best-efforts").mock(
        return_value=httpx.Response(500, json={"error": "db exploded"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.list_running_best_efforts(AUTH)

    assert excinfo.value.status_code == 500
    assert excinfo.value.message == "db exploded"


# --- Tool boundary: Authorization is required before any HTTP call ----


async def test_get_running_best_efforts_tool_requires_auth(monkeypatch):
    """The auth guard fires (RuntimeError) before any HTTP forwarding when
    the inbound request carries no Authorization header. _ExplodingAPI's
    list_running_best_efforts would raise AssertionError if HTTP were
    attempted.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(running, "get_http_headers", lambda **_: {})

    class _ExplodingAPI:
        async def list_running_best_efforts(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

    mcp = FastMCP("test")
    running.register(mcp, _ExplodingAPI())
    tool = await mcp.get_tool("get_running_best_efforts")

    with pytest.raises(RuntimeError, match="Authorization"):
        await tool.fn()


# --- Tool boundary: APIError surfaces as RuntimeError with status ------


async def test_get_running_best_efforts_tool_maps_api_error(monkeypatch):
    """An APIError from the client surfaces to the model as a plain
    RuntimeError with the status code in the message.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(
        running,
        "get_http_headers",
        lambda **_: {"authorization": AUTH},
    )

    class _FailingAPI:
        async def list_running_best_efforts(self, *a, **k):
            raise APIError(500, "db exploded")

    mcp = FastMCP("test")
    running.register(mcp, _FailingAPI())
    tool = await mcp.get_tool("get_running_best_efforts")

    with pytest.raises(RuntimeError, match="500"):
        await tool.fn()
