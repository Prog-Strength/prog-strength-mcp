"""Tests for the training-snapshot MCP surface.

The API client (`get_training_snapshot`) GETs `/training-snapshot`: HTTP
is mocked with respx and we assert the path/method/query/headers and that
the snapshot payload under `data` is forwarded verbatim.

(The MCP tool boundary tests, and the `from prog_strength_mcp import
training_snapshot` import they require, are added in Task B2 alongside the
tool module itself.)
"""

import httpx
import pytest
import respx

from prog_strength_mcp import training_snapshot
from prog_strength_mcp.api_client import APIClient, APIError

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"

_SAMPLE = {
    "period": {
        "start_date": "2026-06-15",
        "end_date": "2026-06-21",
        "timezone": "America/Denver",
        "days": 7,
    },
    "strength": {
        "session_count": 3,
        "total_volume": 48250,
        "unit": "lb",
        "by_muscle_group": [],
        "sessions": [],
        "headline_prs": [],
    },
    "running": None,
    "steps": {"days_logged": 6, "avg": 9120, "total": 54720, "goal": 10000, "by_day": []},
    "bodyweight": None,
    "nutrition": None,
    "consistency": {"active_days": 5, "window_days": 7},
}


@respx.mock
async def test_get_training_snapshot_forwards_params_and_unwraps():
    route = respx.get(f"{BASE_URL}/training-snapshot").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_training_snapshot(
            AUTH, timezone="America/Denver", start_date="2026-06-15", end_date="2026-06-21"
        )
    assert result == _SAMPLE
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    assert req.url.params["timezone"] == "America/Denver"
    assert req.url.params["start_date"] == "2026-06-15"
    assert req.url.params["end_date"] == "2026-06-21"


@respx.mock
async def test_get_training_snapshot_non_dict_data_yields_empty():
    respx.get(f"{BASE_URL}/training-snapshot").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_training_snapshot(AUTH, timezone="UTC")
    assert result == {}


@respx.mock
async def test_get_training_snapshot_surfaces_api_error():
    respx.get(f"{BASE_URL}/training-snapshot").mock(
        return_value=httpx.Response(500, json={"error": "db exploded"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.get_training_snapshot(AUTH, timezone="UTC")
    assert excinfo.value.status_code == 500


# --- Tool boundary -----------------------------------------------------


async def test_tool_requires_auth(monkeypatch):
    from fastmcp import FastMCP

    monkeypatch.setattr(training_snapshot, "get_http_headers", lambda **_: {})

    class _ExplodingAPI:
        async def get_training_snapshot(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

    mcp = FastMCP("test")
    training_snapshot.register(mcp, _ExplodingAPI())
    tool = await mcp.get_tool("get_training_snapshot")
    with pytest.raises(RuntimeError, match="Authorization"):
        await tool.fn(timezone="UTC")


async def test_tool_maps_api_error(monkeypatch):
    from fastmcp import FastMCP

    monkeypatch.setattr(training_snapshot, "get_http_headers", lambda **_: {"authorization": AUTH})

    class _FailingAPI:
        async def get_training_snapshot(self, *a, **k):
            raise APIError(500, "db exploded")

    mcp = FastMCP("test")
    training_snapshot.register(mcp, _FailingAPI())
    tool = await mcp.get_tool("get_training_snapshot")
    with pytest.raises(RuntimeError, match="500"):
        await tool.fn(timezone="UTC")


async def test_tool_forwards_all_params(monkeypatch):
    from fastmcp import FastMCP

    monkeypatch.setattr(training_snapshot, "get_http_headers", lambda **_: {"authorization": AUTH})
    captured = {}

    class _CaptureAPI:
        async def get_training_snapshot(
            self, auth, *, timezone, date=None, start_date=None, end_date=None
        ):
            captured.update(
                auth=auth,
                timezone=timezone,
                date=date,
                start_date=start_date,
                end_date=end_date,
            )
            return _SAMPLE

    mcp = FastMCP("test")
    training_snapshot.register(mcp, _CaptureAPI())
    tool = await mcp.get_tool("get_training_snapshot")
    result = await tool.fn(
        timezone="America/Denver", start_date="2026-06-15", end_date="2026-06-21"
    )
    assert result == _SAMPLE
    assert captured["auth"] == AUTH
    assert captured["timezone"] == "America/Denver"
    assert captured["start_date"] == "2026-06-15"
