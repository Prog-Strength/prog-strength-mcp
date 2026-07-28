"""Tests for the unified /activities APIClient surface.

Client boundary only (respx-mocked HTTP), following the conventions in
test_running_tools.py:

* the new generic methods — `list_activities`, `create_activity`,
  `get_activity` — hit the unified `/activities` paths, unwrap the
  `{service, message, data}` envelope, and surface API errors as APIError.
* the re-pointed strength conveniences — `list_workouts` (now
  `GET /activities?type=strength_training`) and `create_workout` (now
  `POST /activities` with `activity_type=strength_training` and the old
  args mapped onto the unified body).
"""

import json as _json

import httpx
import pytest
import respx

from prog_strength_mcp.api_client import APIClient, APIError

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"

_SAMPLE_ACTIVITY = {
    "id": "act_1",
    "activity_type": "strength_training",
    "start_time": "2026-05-16T18:30:00Z",
    "summary": {"title": "Push day", "subtitle": "2 exercises", "metrics": ["2 exercises"]},
}

_LIST_PAYLOAD = {"activities": [_SAMPLE_ACTIVITY], "next_before": None}


# --- list_activities --------------------------------------------------


@respx.mock
async def test_list_activities_unwraps_activities_list():
    """The list surfaces the `activities` array out of the wrapper (which
    also carries `next_before`), no query params when none are given.
    """
    route = respx.get(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(200, json={"data": _LIST_PAYLOAD})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.list_activities(AUTH)

    assert result == [_SAMPLE_ACTIVITY]
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    assert "type" not in req.url.params
    assert "limit" not in req.url.params


@respx.mock
async def test_list_activities_forwards_type_limit_and_range():
    route = respx.get(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(200, json={"data": _LIST_PAYLOAD})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.list_activities(
            AUTH,
            activity_type="running",
            limit=10,
            since="2026-05-01T00:00:00Z",
            until="2026-05-31T23:59:59Z",
        )

    params = route.calls.last.request.url.params
    assert params["type"] == "running"
    assert params["limit"] == "10"
    assert params["since"] == "2026-05-01T00:00:00Z"
    assert params["until"] == "2026-05-31T23:59:59Z"


@respx.mock
async def test_list_activities_non_list_yields_empty():
    """A missing/non-list `activities` (defensive) collapses to []."""
    respx.get(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(200, json={"data": {"activities": None}})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.list_activities(AUTH)

    assert result == []


@respx.mock
async def test_list_activities_surfaces_api_error():
    respx.get(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(400, json={"error": "unknown activity type"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.list_activities(AUTH, activity_type="bogus")

    assert excinfo.value.status_code == 400
    assert excinfo.value.message == "unknown activity type"


# --- create_activity --------------------------------------------------


@respx.mock
async def test_create_activity_forwards_body_verbatim_and_unwraps():
    payload = {
        "activity_type": "other",
        "start_time": "2026-05-16T18:30:00Z",
        "duration_seconds": 1800,
        "name": "Yoga",
    }
    route = respx.post(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(201, json={"data": _SAMPLE_ACTIVITY})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.create_activity(AUTH, payload)

    assert result == _SAMPLE_ACTIVITY
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    assert _json.loads(req.content) == payload


@respx.mock
async def test_create_activity_422_unknown_type_surfaces():
    respx.post(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(
            422, json={"error": "unknown activity type \"swimming\": valid types are ..."}
        )
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.create_activity(AUTH, {"activity_type": "swimming"})

    assert excinfo.value.status_code == 422
    assert "swimming" in excinfo.value.message


@respx.mock
async def test_create_activity_400_invalid_details_surfaces():
    respx.post(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(400, json={"error": "invalid strength details"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.create_activity(AUTH, {"activity_type": "strength_training"})

    assert excinfo.value.status_code == 400
    assert excinfo.value.message == "invalid strength details"


@respx.mock
async def test_create_activity_non_dict_data_yields_empty():
    respx.post(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(201, json={"data": None})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.create_activity(AUTH, {"activity_type": "other"})

    assert result == {}


# --- get_activity -----------------------------------------------------


@respx.mock
async def test_get_activity_hits_detail_path_and_unwraps():
    route = respx.get(f"{BASE_URL}/activities/act_1").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_ACTIVITY})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_activity(AUTH, "act_1")

    assert result == _SAMPLE_ACTIVITY
    assert route.calls.last.request.headers["Authorization"] == AUTH


@respx.mock
async def test_get_activity_quotes_id_segment():
    """The id is path-quoted like running.py quotes its distance key."""
    route = respx.get(f"{BASE_URL}/activities/act%2Fweird").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_ACTIVITY})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.get_activity(AUTH, "act/weird")

    assert result == _SAMPLE_ACTIVITY
    # The route only matches because the id segment was percent-encoded;
    # raw_path preserves the encoding httpx's decoded .path hides.
    assert b"/activities/act%2Fweird" in route.calls.last.request.url.raw_path


# --- list_workouts (re-pointed to the unified surface) ----------------


@respx.mock
async def test_list_workouts_hits_activities_with_strength_filter():
    route = respx.get(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(200, json={"data": _LIST_PAYLOAD})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.list_workouts(AUTH)

    assert result == [_SAMPLE_ACTIVITY]
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    assert req.url.params["type"] == "strength_training"


# --- create_workout (re-pointed to the unified surface) ---------------

_EXERCISES = [
    {
        "exercise_id": "barbell-bench-press",
        "sets": [{"reps": 5, "weight": 185.0, "unit": "lb"}],
    }
]


@respx.mock
async def test_create_workout_maps_old_args_onto_unified_body():
    route = respx.post(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(201, json={"data": _SAMPLE_ACTIVITY})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.create_workout(
            AUTH,
            exercises=_EXERCISES,
            name="Push day",
            performed_at="2026-05-16T18:30:00Z",
            ended_at="2026-05-16T19:15:00Z",
            notes="felt strong",
        )

    assert result == _SAMPLE_ACTIVITY
    body = _json.loads(route.calls.last.request.content)
    assert body["activity_type"] == "strength_training"
    assert body["start_time"] == "2026-05-16T18:30:00Z"
    assert body["name"] == "Push day"
    assert body["notes"] == "felt strong"
    assert body["details"] == {"exercises": _EXERCISES}
    # ended_at maps to a client-computed duration_seconds (45 min).
    assert body["duration_seconds"] == 2700


@respx.mock
async def test_create_workout_defaults_start_time_and_omits_optionals():
    route = respx.post(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(201, json={"data": _SAMPLE_ACTIVITY})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.create_workout(AUTH, exercises=_EXERCISES)

    body = _json.loads(route.calls.last.request.content)
    assert body["activity_type"] == "strength_training"
    # start_time is required by the unified surface, so an omitted
    # performed_at is defaulted to "now" client-side (non-empty RFC3339).
    assert isinstance(body["start_time"], str) and body["start_time"]
    assert body["details"] == {"exercises": _EXERCISES}
    assert "name" not in body
    assert "notes" not in body
    assert "duration_seconds" not in body


@respx.mock
async def test_create_workout_surfaces_api_error():
    respx.post(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(400, json={"error": "unknown exercise slug"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.create_workout(AUTH, exercises=_EXERCISES)

    assert excinfo.value.status_code == 400
    assert excinfo.value.message == "unknown exercise slug"
