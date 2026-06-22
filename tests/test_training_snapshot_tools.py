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
