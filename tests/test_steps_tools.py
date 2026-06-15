"""Tests for the daily-steps MCP surface.

Two boundaries are exercised:

* The API client (`log_steps`, `get_steps`, `get_steps_goal`,
  `set_steps_goal`): HTTP is mocked with respx and we assert the
  path/method/body/headers and that the payload under `data` is
  forwarded verbatim.
* The MCP tool boundary: the registered tools raise a `RuntimeError`
  mentioning Authorization when the inbound request carries no
  Authorization header (an `_ExplodingAPI` sentinel raises if forwarding
  is attempted), and surface an `APIError` from the client as a
  `RuntimeError` carrying the status code.
"""

import httpx
import pytest
import respx

from prog_strength_mcp import steps
from prog_strength_mcp.api_client import APIClient, APIError

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"

_SAMPLE_ENTRY = {
    "id": "step_1a2",
    "date": "2026-06-14",
    "steps": 8421,
    "created_at": "2026-06-14T23:10:00Z",
    "updated_at": "2026-06-14T23:10:00Z",
}


# --- API client: log_steps --------------------------------------------


@respx.mock
async def test_log_steps_puts_body_and_forwards_auth():
    route = respx.put(f"{BASE_URL}/steps/2026-06-14").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_ENTRY})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.log_steps(AUTH, date="2026-06-14", steps=8421)

    assert result == _SAMPLE_ENTRY
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    import json

    assert json.loads(req.content) == {"steps": 8421}


@respx.mock
async def test_log_steps_non_dict_data_yields_empty():
    respx.put(f"{BASE_URL}/steps/2026-06-14").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.log_steps(AUTH, date="2026-06-14", steps=100)

    assert result == {}


@respx.mock
async def test_log_steps_surfaces_api_error():
    respx.put(f"{BASE_URL}/steps/2026-06-14").mock(
        return_value=httpx.Response(500, json={"error": "db exploded"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.log_steps(AUTH, date="2026-06-14", steps=100)

    assert excinfo.value.status_code == 500
    assert excinfo.value.message == "db exploded"


# --- API client: get_steps --------------------------------------------


@respx.mock
async def test_get_steps_forwards_range_and_unwraps_data():
    payload = {"steps": [_SAMPLE_ENTRY], "next_before": None}
    route = respx.get(f"{BASE_URL}/steps").mock(
        return_value=httpx.Response(200, json={"data": payload})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_steps(AUTH, since="2026-06-01", until="2026-06-14")

    assert result == payload
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    assert req.url.params["since"] == "2026-06-01"
    assert req.url.params["until"] == "2026-06-14"


@respx.mock
async def test_get_steps_non_dict_data_yields_empty():
    respx.get(f"{BASE_URL}/steps").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_steps(AUTH)

    assert result == {}


@respx.mock
async def test_get_steps_surfaces_api_error():
    respx.get(f"{BASE_URL}/steps").mock(
        return_value=httpx.Response(500, json={"error": "db exploded"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.get_steps(AUTH)

    assert excinfo.value.status_code == 500
    assert excinfo.value.message == "db exploded"


# --- API client: get_steps_goal / set_steps_goal ----------------------

_SAMPLE_GOAL = {
    "goal": 10000,
    "created_at": "2026-05-01T00:00:00Z",
    "updated_at": "2026-06-01T00:00:00Z",
}


@respx.mock
async def test_get_steps_goal_forwards_and_unwraps():
    route = respx.get(f"{BASE_URL}/me/steps-goal").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_GOAL})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_steps_goal(AUTH)

    assert result == _SAMPLE_GOAL
    assert route.calls.last.request.headers["Authorization"] == AUTH


@respx.mock
async def test_set_steps_goal_puts_body_and_unwraps():
    route = respx.put(f"{BASE_URL}/me/steps-goal").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_GOAL})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.set_steps_goal(AUTH, goal=10000)

    assert result == _SAMPLE_GOAL
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    import json

    assert json.loads(req.content) == {"goal": 10000}


@respx.mock
async def test_set_steps_goal_surfaces_api_error():
    respx.put(f"{BASE_URL}/me/steps-goal").mock(
        return_value=httpx.Response(500, json={"error": "db exploded"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.set_steps_goal(AUTH, goal=10000)

    assert excinfo.value.status_code == 500
    assert excinfo.value.message == "db exploded"


# --- Tool boundary: Authorization is required before any HTTP call ----


async def test_steps_tools_require_auth(monkeypatch):
    """The auth guard fires (RuntimeError) before any HTTP forwarding when
    the inbound request carries no Authorization header. _ExplodingAPI
    raises AssertionError if HTTP were attempted.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(steps, "get_http_headers", lambda **_: {})

    class _ExplodingAPI:
        async def log_steps(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

        async def get_steps(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

        async def get_steps_goal(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

        async def set_steps_goal(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

    mcp = FastMCP("test")
    steps.register(mcp, _ExplodingAPI())

    log_tool = await mcp.get_tool("log_steps")
    get_tool = await mcp.get_tool("get_steps")
    get_goal_tool = await mcp.get_tool("get_steps_goal")
    set_goal_tool = await mcp.get_tool("set_steps_goal")

    with pytest.raises(RuntimeError, match="Authorization"):
        await log_tool.fn(date="2026-06-14", steps=100)
    with pytest.raises(RuntimeError, match="Authorization"):
        await get_tool.fn()
    with pytest.raises(RuntimeError, match="Authorization"):
        await get_goal_tool.fn()
    with pytest.raises(RuntimeError, match="Authorization"):
        await set_goal_tool.fn(goal=10000)


# --- Tool boundary: APIError surfaces as RuntimeError with status ------


async def test_steps_tools_map_api_error(monkeypatch):
    """An APIError from the client surfaces to the model as a plain
    RuntimeError with the status code in the message.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(
        steps,
        "get_http_headers",
        lambda **_: {"authorization": AUTH},
    )

    class _FailingAPI:
        async def log_steps(self, *a, **k):
            raise APIError(500, "db exploded")

        async def get_steps(self, *a, **k):
            raise APIError(500, "db exploded")

        async def get_steps_goal(self, *a, **k):
            raise APIError(500, "db exploded")

        async def set_steps_goal(self, *a, **k):
            raise APIError(500, "db exploded")

    mcp = FastMCP("test")
    steps.register(mcp, _FailingAPI())

    log_tool = await mcp.get_tool("log_steps")
    get_tool = await mcp.get_tool("get_steps")
    get_goal_tool = await mcp.get_tool("get_steps_goal")
    set_goal_tool = await mcp.get_tool("set_steps_goal")

    with pytest.raises(RuntimeError, match="500"):
        await log_tool.fn(date="2026-06-14", steps=100)
    with pytest.raises(RuntimeError, match="500"):
        await get_tool.fn()
    with pytest.raises(RuntimeError, match="500"):
        await get_goal_tool.fn()
    with pytest.raises(RuntimeError, match="500"):
        await set_goal_tool.fn(goal=10000)
