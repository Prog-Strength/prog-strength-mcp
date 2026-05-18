"""Workout domain: input models and MCP tools for logging/listing workouts.

Mirrors the API's `internal/workout/` package boundary. Each domain module
exposes a `register(mcp, api)` that hangs its tools off the passed-in
FastMCP instance — the Python parallel of the API handlers' Mount(r).

Authorization is sourced from the inbound MCP request's `Authorization`
header (the agent sets it to `Bearer <user-jwt>` when opening the MCP
session). FastMCP exposes that header via `get_http_headers` — by
default it strips `authorization` for security, so we have to opt in
with `include={"authorization"}`.
"""

from typing import Annotated, Any, Literal

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


class WorkoutSetInput(BaseModel):
    """One set of an exercise — reps × weight in a chosen unit.

    Mirrors the API's `workout.Set`. Bodyweight is `weight=0`. The unit is
    stored per set (not converted) so plate math survives round-tripping.
    """

    reps: Annotated[int, Field(gt=0, description="Repetitions performed; must be > 0.")]
    weight: Annotated[
        float,
        Field(ge=0, description="Weight per rep in the chosen unit. Use 0 for bodyweight."),
    ]
    unit: Annotated[
        Literal["lb", "kg"],
        Field(description="Weight unit for this set: 'lb' or 'kg'."),
    ]


class WorkoutExerciseInput(BaseModel):
    """One exercise within a workout, with its sets.

    `exercise_id` must be a slug from the shared catalog (see the
    list_exercises tool) — e.g. 'barbell-high-bar-back-squat'. Free-text
    names will be rejected by the API.
    """

    exercise_id: Annotated[
        str,
        Field(description="Slug ID from list_exercises, e.g. 'barbell-bench-press'."),
    ]
    sets: Annotated[
        list[WorkoutSetInput],
        Field(min_length=1, description="At least one set is required."),
    ]
    superset_group: Annotated[
        int | None,
        Field(
            default=None,
            description=(
                "Optional. Exercises sharing the same integer were performed as a "
                "superset. Leave null for standalone exercises."
            ),
        ),
    ] = None
    notes: Annotated[
        str | None,
        Field(default=None, description="Optional free-text notes for this exercise."),
    ] = None


def register(mcp: FastMCP, api: APIClient) -> None:
    """Register workout tools on `mcp`, backed by `api`.

    Tools defined inside this function close over `api` — keeping the
    dependency explicit at the registration boundary rather than as a
    module-level global.
    """

    @mcp.tool
    async def list_workouts() -> list[dict[str, Any]]:
        """List the calling user's logged workouts, most recent first.

        Identity is sourced from the inbound MCP session's Authorization
        header (the user's JWT); the API decodes the `sub` claim and
        scopes the results. There is no user_id parameter — Claude
        cannot fetch another user's data.

        Returns the first page of results (the API's default limit, ~50
        workouts). Pagination parameters are not exposed to the agent
        yet — if you need older workouts beyond the first page, that's
        a future feature on this tool.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.list_workouts(auth)
        except APIError as e:
            # Re-raise as a plain RuntimeError so FastMCP serializes a clean
            # tool error to the model (instead of leaking the internal class).
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def create_workout(
        exercises: list[WorkoutExerciseInput],
        name: str | None = None,
        performed_at: str | None = None,
        ended_at: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Log a new workout for the calling user.

        Identity is sourced from the inbound MCP session's Authorization
        header. Translate the user's natural-language description into
        structured sets first: resolve each exercise to a slug via
        list_exercises, then fill in reps, weight, and unit for every
        set. Bodyweight moves use weight=0. If the user didn't specify
        a time, omit performed_at and the API will stamp it as "now".

        Args:
            exercises: Ordered list of exercises performed; their position
                in this list becomes the workout's exercise order (0-indexed).
            name: Optional session name. Defaults server-side to
                "Workout - <date>" when omitted.
            performed_at: Optional RFC3339 start time, e.g.
                '2026-05-16T18:30:00Z'. Defaults to now when omitted.
            ended_at: Optional RFC3339 end time. Must be >= performed_at.
            notes: Optional free-text notes for the whole session.
        """
        if not exercises:
            raise ValueError("exercises must contain at least one entry")

        auth = _auth_header_or_raise()
        try:
            return await api.create_workout(
                auth,
                exercises=[ex.model_dump(exclude_none=True) for ex in exercises],
                name=name,
                performed_at=performed_at,
                ended_at=ended_at,
                notes=notes,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
