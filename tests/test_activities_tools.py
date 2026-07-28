"""Tests for the canonical unified-activity MCP tools (log_activity,
list_activities).

Covers the tool boundary the way test_running_tools.py does:

* the auth guard fires (RuntimeError mentioning Authorization) before any
  HTTP forwarding when the inbound request carries no Authorization header;
* param forwarding — log_activity builds the unified body (defaulting
  start_time to now when omitted) and list_activities forwards its type /
  range / limit filters;
* an APIError (e.g. a 422 unknown type) surfaces as a plain RuntimeError
  carrying the status.
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
async def test_list_activities_forwards_range(monkeypatch):
    route = respx.get(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(200, json={"data": {"activities": [], "next_before": None}})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("list_activities")
        await tool.fn(since="2026-05-01T00:00:00Z", until="2026-05-31T23:59:59Z")

    params = route.calls.last.request.url.params
    assert params["since"] == "2026-05-01T00:00:00Z"
    assert params["until"] == "2026-05-31T23:59:59Z"


@respx.mock
async def test_list_activities_forwards_limit_only_when_no_range(monkeypatch):
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


async def test_list_activities_maps_api_error(monkeypatch):
    class _FailingAPI:
        async def list_activities(self, *a, **k):
            raise APIError(400, "since/until cannot be combined with limit/before")

    mcp = _register(monkeypatch, _FailingAPI())
    tool = await mcp.get_tool("list_activities")
    with pytest.raises(RuntimeError, match="400"):
        await tool.fn(since="2026-05-01T00:00:00Z", limit=5)
