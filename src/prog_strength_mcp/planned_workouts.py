"""Planned-workouts domain: input models and MCP tools for creating,
listing, editing, skipping, and (Phase 3/4) calendar-syncing and
completing forward-looking planned workouts.

Mirrors the API's `/planned-workouts` surface. A planned workout is a
FORWARD-LOOKING intention scheduled at a time — distinct from a logged
workout (see workouts.py). A plan can be a bare time block (no agenda)
or carry a full exercise/set agenda.

Authorization is sourced from the inbound MCP request's `Authorization`
header, the same pattern every other domain module uses.
"""

from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field

from prog_strength_mcp.api_client import APIClient, APIError


def _auth_header_or_raise() -> str:
    """Pull the inbound Authorization header. Tools that require auth
    call this before forwarding to the API; missing/empty header is
    surfaced to Claude as an error rather than letting the API 401.
    """
    headers = get_http_headers(include={"authorization"})
    auth = headers.get("authorization", "")
    if not auth:
        raise RuntimeError(
            "missing Authorization header on the MCP request — the agent "
            "must open the MCP session with the user's Bearer token."
        )
    return auth


class PlannedSetInput(BaseModel):
    """One planned (target) set within a planned exercise.

    All targets are optional — a planned set can be a bare placeholder.
    Mirrors the API's planned-set request shape.
    """

    target_reps: Annotated[
        int | None,
        Field(default=None, description="Target repetitions for the set."),
    ] = None
    target_weight: Annotated[
        float | None,
        Field(default=None, description="Target weight per rep in the chosen unit."),
    ] = None
    unit: Annotated[
        str | None,
        Field(default=None, description="Weight unit for this set: 'lb' or 'kg'."),
    ] = None
    target_rpe: Annotated[
        float | None,
        Field(default=None, description="Target RPE (rate of perceived exertion)."),
    ] = None


class PlannedExerciseInput(BaseModel):
    """One planned exercise within a planned workout, with its target sets.

    `exercise_id` must be a slug from the shared catalog (see the
    list_exercises tool) — e.g. 'barbell-high-bar-back-squat'.
    """

    exercise_id: Annotated[
        str,
        Field(description="Slug ID from list_exercises, e.g. 'barbell-bench-press'."),
    ]
    notes: Annotated[
        str | None,
        Field(default=None, description="Optional free-text notes for this exercise."),
    ] = None
    sets: Annotated[
        list[PlannedSetInput],
        Field(default_factory=list, description="Target sets for this exercise."),
    ]


def register(mcp: FastMCP, api: APIClient) -> None:
    """Register planned-workout tools on `mcp`, backed by `api`.

    Tools defined inside this function close over `api` — keeping the
    dependency explicit at the registration boundary.
    """

    @mcp.tool
    async def create_planned_workout(
        scheduled_start: str,
        scheduled_end: str,
        timezone: str | None = None,
        name: str | None = None,
        notes: str | None = None,
        calendar_detail: str | None = None,
        exercises: list[PlannedExerciseInput] | None = None,
    ) -> dict[str, Any]:
        """Create a FORWARD-LOOKING planned workout for the calling user.

        This schedules an intended workout at a future time — it is NOT a
        logged/completed workout (use create_workout for that). The plan
        can be a bare time block (no agenda) or carry a full
        exercise/set agenda.

        Args:
            scheduled_start: RFC3339 start time, e.g. '2026-06-16T18:00:00Z'.
            scheduled_end: RFC3339 end time; must be >= scheduled_start.
            timezone: Optional IANA timezone name (e.g. 'America/New_York')
                the plan is anchored to. Defaults server-side when omitted.
            name: Optional plan name. Defaults server-side when omitted.
            notes: Optional free-text notes for the whole plan.
            calendar_detail: Optional override for how the plan renders on a
                synced calendar — 'time_block' (just the slot) or
                'full_agenda' (exercises/sets in the event). Omit to use the
                user's default.
            exercises: Optional planned agenda. Resolve each exercise to a
                slug via list_exercises. Omit (or leave empty) for a bare
                time block.
        """
        auth = _auth_header_or_raise()
        ex_payload = (
            [e.model_dump(exclude_none=True) for e in exercises]
            if exercises is not None
            else None
        )
        try:
            return await api.create_planned_workout(
                auth,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
                timezone=timezone,
                name=name,
                notes=notes,
                calendar_detail=calendar_detail,
                exercises=ex_payload,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def list_planned_workouts(since: str, until: str) -> list[dict[str, Any]]:
        """List the calling user's planned workouts in a time range — the
        week view.

        Args:
            since: RFC3339 lower bound on scheduled_start (inclusive).
            until: RFC3339 upper bound on scheduled_start (exclusive).

        Returns the plans scheduled in [since, until).
        """
        auth = _auth_header_or_raise()
        try:
            return await api.list_planned_workouts(auth, since=since, until=until)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def update_planned_workout(
        planned_workout_id: str,
        scheduled_start: str | None = None,
        scheduled_end: str | None = None,
        timezone: str | None = None,
        name: str | None = None,
        notes: str | None = None,
        calendar_detail: str | None = None,
        exercises: list[PlannedExerciseInput] | None = None,
    ) -> dict[str, Any]:
        """Edit an existing planned workout.

        Only the fields you pass are sent — omitted fields are left
        unchanged. `scheduled_start`/`scheduled_end` are RFC3339;
        `calendar_detail` is 'time_block' or 'full_agenda'; pass
        `exercises` to replace the plan's agenda (resolve each to a slug
        via list_exercises).
        """
        auth = _auth_header_or_raise()
        ex_payload = (
            [e.model_dump(exclude_none=True) for e in exercises]
            if exercises is not None
            else None
        )
        try:
            return await api.update_planned_workout(
                auth,
                planned_workout_id,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
                timezone=timezone,
                name=name,
                notes=notes,
                calendar_detail=calendar_detail,
                exercises=ex_payload,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def skip_planned_workout(planned_workout_id: str) -> dict[str, Any]:
        """Mark a planned workout as skipped.

        Use this when the user decides not to do a planned session.
        Returns the updated plan.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.skip_planned_workout(auth, planned_workout_id)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def schedule_workout_to_calendar(
        planned_workout_id: str,
        detail_level: str | None = None,
    ) -> dict[str, Any]:
        """Push a planned workout to the user's connected Google Calendar.

        Args:
            planned_workout_id: The plan to schedule.
            detail_level: Optional override — 'time_block' (just the slot)
                or 'full_agenda' (exercises/sets in the event). Omit to use
                the plan's stored detail.

        Note: requires the calendar-sync API (Phase 3) and a connected
        Google Calendar. Until those are in place the API returns an error
        which surfaces here as a RuntimeError.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.schedule_workout_to_calendar(
                auth, planned_workout_id, detail_level=detail_level
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def complete_planned_workout(
        planned_workout_id: str,
        session_id: str,
        session_kind: str,
    ) -> dict[str, Any]:
        """Mark a planned workout completed and link the logged session.

        Args:
            planned_workout_id: The plan being completed.
            session_id: The id of the logged session that fulfilled the plan.
            session_kind: The kind of session — "workout" or "activity".

        Note: requires the completion API (Phase 4). Until then the API
        returns an error which surfaces here as a RuntimeError.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.complete_planned_workout(
                auth,
                planned_workout_id,
                session_id=session_id,
                session_kind=session_kind,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
