"""Tests for the workout MCP tools (re-pointed to the unified /activities
surface in api PR #79).

The tool NAMES and argument contracts are unchanged; what changed is the
endpoint each proxies to. These tests pin two things:

* the auth guard fires (RuntimeError mentioning Authorization) before any
  HTTP forwarding when the inbound request carries no Authorization header
  — the `_ExplodingAPI` sentinel raises if forwarding is attempted;
* the happy path hits the NEW endpoints — `GET /activities?type=
  strength_training` for list_workouts and `POST /activities` with an
  `activity_type=strength_training` body for create_workout.
"""

import json as _json

import httpx
import pytest
import respx
from fastmcp import FastMCP

from prog_strength_mcp import workouts
from prog_strength_mcp.api_client import APIClient, APIError
from prog_strength_mcp.workouts import WorkoutExerciseInput, WorkoutSetInput


def _bench():
    return WorkoutExerciseInput(
        exercise_id="barbell-bench-press",
        sets=[WorkoutSetInput(reps=5, weight=185.0, unit="lb")],
    )

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"

_ACTIVITY = {
    "id": "act_1",
    "activity_type": "strength_training",
    "start_time": "2026-05-16T18:30:00Z",
    "summary": {"title": "Push day", "subtitle": "1 exercise", "metrics": ["1 exercise"]},
    "details": {"exercises": [{"exercise_id": "barbell-bench-press"}]},
}


def _register(monkeypatch, api, *, auth=AUTH):
    """Register the workout tools onto a fresh FastMCP with `api`, patching
    the inbound-header lookup to `auth` (pass auth=None for the missing-
    header case).
    """
    headers = {"authorization": auth} if auth else {}
    monkeypatch.setattr(workouts, "get_http_headers", lambda **_: headers)
    mcp = FastMCP("test")
    workouts.register(mcp, api)
    return mcp


# --- Auth guard: fires before any HTTP forwarding ---------------------


class _ExplodingAPI:
    async def list_workouts(self, *a, **k):  # pragma: no cover
        raise AssertionError("HTTP forwarding must not happen on missing auth")

    async def create_workout(self, *a, **k):  # pragma: no cover
        raise AssertionError("HTTP forwarding must not happen on missing auth")


async def test_list_workouts_requires_auth(monkeypatch):
    mcp = _register(monkeypatch, _ExplodingAPI(), auth=None)
    tool = await mcp.get_tool("list_workouts")
    with pytest.raises(RuntimeError, match="Authorization"):
        await tool.fn()


async def test_create_workout_requires_auth(monkeypatch):
    mcp = _register(monkeypatch, _ExplodingAPI(), auth=None)
    tool = await mcp.get_tool("create_workout")
    with pytest.raises(RuntimeError, match="Authorization"):
        await tool.fn(exercises=[{"exercise_id": "barbell-bench-press",
                                  "sets": [{"reps": 5, "weight": 185.0, "unit": "lb"}]}])


# --- Happy path: the NEW unified endpoints are hit --------------------


@respx.mock
async def test_list_workouts_hits_strength_filtered_activities(monkeypatch):
    route = respx.get(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(200, json={"data": {"activities": [_ACTIVITY],
                                                        "next_before": None}})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("list_workouts")
        result = await tool.fn()

    assert result == [_ACTIVITY]
    req = route.calls.last.request
    assert req.url.params["type"] == "strength_training"
    assert req.headers["Authorization"] == AUTH


@respx.mock
async def test_create_workout_posts_unified_strength_body(monkeypatch):
    route = respx.post(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(201, json={"data": _ACTIVITY})
    )
    async with APIClient(base_url=BASE_URL) as api:
        mcp = _register(monkeypatch, api)
        tool = await mcp.get_tool("create_workout")
        result = await tool.fn(
            exercises=[_bench()],
            name="Push day",
            performed_at="2026-05-16T18:30:00Z",
        )

    assert result == _ACTIVITY
    body = _json.loads(route.calls.last.request.content)
    assert body["activity_type"] == "strength_training"
    assert body["start_time"] == "2026-05-16T18:30:00Z"
    assert body["name"] == "Push day"
    assert body["details"]["exercises"][0]["exercise_id"] == "barbell-bench-press"
    assert body["details"]["exercises"][0]["sets"] == [
        {"reps": 5, "weight": 185.0, "unit": "lb"}
    ]


# --- APIError surfaces as a plain RuntimeError with the status --------


async def test_create_workout_maps_api_error(monkeypatch):
    class _FailingAPI:
        async def create_workout(self, *a, **k):
            raise APIError(422, "unknown activity type")

    mcp = _register(monkeypatch, _FailingAPI())
    tool = await mcp.get_tool("create_workout")
    with pytest.raises(RuntimeError, match="422"):
        await tool.fn(exercises=[_bench()])
