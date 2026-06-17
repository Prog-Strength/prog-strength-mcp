"""Tests for the planned-workouts MCP surface.

Two boundaries are exercised:

* The API client (`create_planned_workout`, `list_planned_workouts`,
  `update_planned_workout`, `skip_planned_workout`,
  `schedule_workout_to_calendar`, `complete_planned_workout`): HTTP is
  mocked with respx and we assert the path/method/body/headers and that
  the payload under `data` is forwarded verbatim.
* The MCP tool boundary: the registered tools raise a `RuntimeError`
  mentioning Authorization when the inbound request carries no
  Authorization header (an `_ExplodingAPI` sentinel raises if forwarding
  is attempted), and surface an `APIError` from the client as a
  `RuntimeError` carrying the status code.
"""

import json

import httpx
import pytest
import respx

from prog_strength_mcp import planned_workouts
from prog_strength_mcp.api_client import APIClient, APIError

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"

_SAMPLE_PLAN = {
    "id": "pw_1a2",
    "name": "Squat day",
    "scheduled_start": "2026-06-16T18:00:00Z",
    "scheduled_end": "2026-06-16T19:00:00Z",
    "status": "planned",
    "calendar_detail": "time_block",
    "exercises": [],
    "created_at": "2026-06-15T10:00:00Z",
    "updated_at": "2026-06-15T10:00:00Z",
}


# --- API client: create_planned_workout -------------------------------


@respx.mock
async def test_create_planned_workout_posts_body_omitting_none():
    route = respx.post(f"{BASE_URL}/planned-workouts").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_PLAN})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.create_planned_workout(
            AUTH,
            scheduled_start="2026-06-16T18:00:00Z",
            scheduled_end="2026-06-16T19:00:00Z",
            name="Squat day",
            exercises=[
                {
                    "exercise_id": "barbell-high-bar-back-squat",
                    "sets": [{"target_reps": 5, "target_weight": 100.0, "unit": "kg"}],
                }
            ],
        )

    assert result == _SAMPLE_PLAN
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    body = json.loads(req.content)
    assert body == {
        "scheduled_start": "2026-06-16T18:00:00Z",
        "scheduled_end": "2026-06-16T19:00:00Z",
        "name": "Squat day",
        "exercises": [
            {
                "exercise_id": "barbell-high-bar-back-squat",
                "sets": [{"target_reps": 5, "target_weight": 100.0, "unit": "kg"}],
            }
        ],
    }
    # None-valued optionals are omitted so the API applies its defaults.
    assert "timezone" not in body
    assert "notes" not in body
    assert "calendar_detail" not in body


@respx.mock
async def test_create_planned_workout_non_dict_data_yields_empty():
    respx.post(f"{BASE_URL}/planned-workouts").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.create_planned_workout(
            AUTH,
            scheduled_start="2026-06-16T18:00:00Z",
            scheduled_end="2026-06-16T19:00:00Z",
        )

    assert result == {}


@respx.mock
async def test_create_planned_workout_surfaces_api_error():
    respx.post(f"{BASE_URL}/planned-workouts").mock(
        return_value=httpx.Response(500, json={"error": "db exploded"})
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.create_planned_workout(
                AUTH,
                scheduled_start="2026-06-16T18:00:00Z",
                scheduled_end="2026-06-16T19:00:00Z",
            )

    assert excinfo.value.status_code == 500
    assert excinfo.value.message == "db exploded"


# --- API client: list_planned_workouts --------------------------------


@respx.mock
async def test_list_planned_workouts_sets_range_and_wraps_plans():
    route = respx.get(f"{BASE_URL}/planned-workouts").mock(
        return_value=httpx.Response(200, json={"data": [_SAMPLE_PLAN]})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.list_planned_workouts(
            AUTH,
            since="2026-06-15T00:00:00Z",
            until="2026-06-22T00:00:00Z",
        )

    # The plans come back under `workouts`; no X-Request-ID on the mock
    # response means the key is simply absent (tracing is a bonus, never a
    # required field).
    assert result == {"workouts": [_SAMPLE_PLAN]}
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    assert req.url.params["since"] == "2026-06-15T00:00:00Z"
    assert req.url.params["until"] == "2026-06-22T00:00:00Z"


@respx.mock
async def test_list_planned_workouts_surfaces_request_id():
    """The API's X-Request-ID rides back on the envelope so a chat report
    pivots straight into CloudWatch — the same end-to-end tracing the
    nutrition lookup wired.
    """
    respx.get(f"{BASE_URL}/planned-workouts").mock(
        return_value=httpx.Response(
            200,
            json={"data": [_SAMPLE_PLAN]},
            headers={"X-Request-ID": "req_abc123"},
        )
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.list_planned_workouts(
            AUTH, since="2026-06-15T00:00:00Z", until="2026-06-22T00:00:00Z"
        )

    assert result == {"workouts": [_SAMPLE_PLAN], "request_id": "req_abc123"}


@respx.mock
async def test_list_planned_workouts_non_list_data_yields_empty():
    respx.get(f"{BASE_URL}/planned-workouts").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.list_planned_workouts(
            AUTH, since="2026-06-15T00:00:00Z", until="2026-06-22T00:00:00Z"
        )

    assert result == {"workouts": []}


@respx.mock
async def test_list_planned_workouts_error_carries_request_id():
    """A failed list raises APIError carrying the X-Request-ID, so even the
    failure is traceable; the tool layer folds it into the RuntimeError.
    """
    respx.get(f"{BASE_URL}/planned-workouts").mock(
        return_value=httpx.Response(
            500,
            json={"error": "db exploded"},
            headers={"X-Request-ID": "req_fail9"},
        )
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as excinfo:
            await api.list_planned_workouts(
                AUTH, since="2026-06-15T00:00:00Z", until="2026-06-22T00:00:00Z"
            )

    assert excinfo.value.status_code == 500
    assert excinfo.value.message == "db exploded"
    assert excinfo.value.request_id == "req_fail9"


# --- API client: update_planned_workout -------------------------------


@respx.mock
async def test_update_planned_workout_puts_body_omitting_none():
    route = respx.put(f"{BASE_URL}/planned-workouts/pw_1a2").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_PLAN})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.update_planned_workout(
            AUTH,
            "pw_1a2",
            name="Renamed",
            notes="heavy day",
        )

    assert result == _SAMPLE_PLAN
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    body = json.loads(req.content)
    assert body == {"name": "Renamed", "notes": "heavy day"}


# --- API client: skip_planned_workout ---------------------------------


@respx.mock
async def test_skip_planned_workout_posts_and_unwraps():
    route = respx.post(f"{BASE_URL}/planned-workouts/pw_1a2/skip").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_PLAN})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.skip_planned_workout(AUTH, "pw_1a2")

    assert result == _SAMPLE_PLAN
    assert route.calls.last.request.headers["Authorization"] == AUTH


# --- API client: schedule_workout_to_calendar -------------------------


@respx.mock
async def test_schedule_workout_to_calendar_posts_detail_level():
    route = respx.post(f"{BASE_URL}/planned-workouts/pw_1a2/schedule").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_PLAN})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.schedule_workout_to_calendar(
            AUTH, "pw_1a2", detail_level="full_agenda"
        )

    assert result == _SAMPLE_PLAN
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    assert json.loads(req.content) == {"detail_level": "full_agenda"}


@respx.mock
async def test_schedule_workout_to_calendar_omits_detail_level_when_none():
    route = respx.post(f"{BASE_URL}/planned-workouts/pw_1a2/schedule").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_PLAN})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.schedule_workout_to_calendar(AUTH, "pw_1a2")

    assert json.loads(route.calls.last.request.content) == {}


# --- API client: complete_planned_workout -----------------------------


@respx.mock
async def test_complete_planned_workout_posts_session_link():
    route = respx.post(f"{BASE_URL}/planned-workouts/pw_1a2/complete").mock(
        return_value=httpx.Response(200, json={"data": _SAMPLE_PLAN})
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.complete_planned_workout(
            AUTH, "pw_1a2", session_id="wk_99", session_kind="workout"
        )

    assert result == _SAMPLE_PLAN
    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    assert json.loads(req.content) == {
        "session_id": "wk_99",
        "session_kind": "workout",
    }


# --- Tool boundary: list returns the {workouts, request_id} envelope --


async def test_list_planned_workouts_tool_returns_envelope(monkeypatch):
    """The tool forwards the client's envelope to the model verbatim, so the
    request_id reaches the agent's tool_result SSE event (the agent only
    plucks request_id off a JSON object, never a bare list).
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(
        planned_workouts,
        "get_http_headers",
        lambda **_: {"authorization": AUTH},
    )

    class _StubAPI:
        async def list_planned_workouts(self, auth_header, *, since, until):
            assert auth_header == AUTH
            return {"workouts": [_SAMPLE_PLAN], "request_id": "req_abc123"}

    mcp = FastMCP("test")
    planned_workouts.register(mcp, _StubAPI())
    list_tool = await mcp.get_tool("list_planned_workouts")

    result = await list_tool.fn(
        since="2026-06-15T00:00:00Z", until="2026-06-22T00:00:00Z"
    )
    assert result == {"workouts": [_SAMPLE_PLAN], "request_id": "req_abc123"}


# --- Tool boundary: Authorization is required before any HTTP call ----


async def test_planned_workouts_tools_require_auth(monkeypatch):
    """The auth guard fires (RuntimeError) before any HTTP forwarding when
    the inbound request carries no Authorization header. _ExplodingAPI
    raises AssertionError if HTTP were attempted.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(planned_workouts, "get_http_headers", lambda **_: {})

    class _ExplodingAPI:
        async def create_planned_workout(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

        async def list_planned_workouts(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

        async def update_planned_workout(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

        async def skip_planned_workout(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

        async def schedule_workout_to_calendar(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

        async def complete_planned_workout(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

    mcp = FastMCP("test")
    planned_workouts.register(mcp, _ExplodingAPI())

    create_tool = await mcp.get_tool("create_planned_workout")
    list_tool = await mcp.get_tool("list_planned_workouts")
    update_tool = await mcp.get_tool("update_planned_workout")
    skip_tool = await mcp.get_tool("skip_planned_workout")
    schedule_tool = await mcp.get_tool("schedule_workout_to_calendar")
    complete_tool = await mcp.get_tool("complete_planned_workout")

    with pytest.raises(RuntimeError, match="Authorization"):
        await create_tool.fn(
            scheduled_start="2026-06-16T18:00:00Z",
            scheduled_end="2026-06-16T19:00:00Z",
        )
    with pytest.raises(RuntimeError, match="Authorization"):
        await list_tool.fn(since="2026-06-15T00:00:00Z", until="2026-06-22T00:00:00Z")
    with pytest.raises(RuntimeError, match="Authorization"):
        await update_tool.fn(planned_workout_id="pw_1a2", name="x")
    with pytest.raises(RuntimeError, match="Authorization"):
        await skip_tool.fn(planned_workout_id="pw_1a2")
    with pytest.raises(RuntimeError, match="Authorization"):
        await schedule_tool.fn(planned_workout_id="pw_1a2")
    with pytest.raises(RuntimeError, match="Authorization"):
        await complete_tool.fn(
            planned_workout_id="pw_1a2", session_id="wk_99", session_kind="workout"
        )


# --- Tool boundary: APIError surfaces as RuntimeError with status ------


async def test_planned_workouts_tools_map_api_error(monkeypatch):
    """An APIError from the client surfaces to the model as a plain
    RuntimeError with the status code in the message.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(
        planned_workouts,
        "get_http_headers",
        lambda **_: {"authorization": AUTH},
    )

    class _FailingAPI:
        async def create_planned_workout(self, *a, **k):
            raise APIError(500, "db exploded")

        async def list_planned_workouts(self, *a, **k):
            raise APIError(500, "db exploded")

        async def update_planned_workout(self, *a, **k):
            raise APIError(500, "db exploded")

        async def skip_planned_workout(self, *a, **k):
            raise APIError(500, "db exploded")

        async def schedule_workout_to_calendar(self, *a, **k):
            raise APIError(500, "db exploded")

        async def complete_planned_workout(self, *a, **k):
            raise APIError(500, "db exploded")

    mcp = FastMCP("test")
    planned_workouts.register(mcp, _FailingAPI())

    create_tool = await mcp.get_tool("create_planned_workout")
    list_tool = await mcp.get_tool("list_planned_workouts")
    update_tool = await mcp.get_tool("update_planned_workout")
    skip_tool = await mcp.get_tool("skip_planned_workout")
    schedule_tool = await mcp.get_tool("schedule_workout_to_calendar")
    complete_tool = await mcp.get_tool("complete_planned_workout")

    with pytest.raises(RuntimeError, match="500"):
        await create_tool.fn(
            scheduled_start="2026-06-16T18:00:00Z",
            scheduled_end="2026-06-16T19:00:00Z",
        )
    with pytest.raises(RuntimeError, match="500"):
        await list_tool.fn(since="2026-06-15T00:00:00Z", until="2026-06-22T00:00:00Z")
    with pytest.raises(RuntimeError, match="500"):
        await update_tool.fn(planned_workout_id="pw_1a2", name="x")
    with pytest.raises(RuntimeError, match="500"):
        await skip_tool.fn(planned_workout_id="pw_1a2")
    with pytest.raises(RuntimeError, match="500"):
        await schedule_tool.fn(planned_workout_id="pw_1a2")
    with pytest.raises(RuntimeError, match="500"):
        await complete_tool.fn(
            planned_workout_id="pw_1a2", session_id="wk_99", session_kind="workout"
        )
