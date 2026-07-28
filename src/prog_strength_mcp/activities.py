"""Activities domain: the canonical, type-agnostic MCP tools over the
unified `/activities` surface (api PR #79).

`log_activity` and `list_activities` are the generic front doors for every
registered activity type — running, walking, cycling, other, and
strength_training. The strength-typed conveniences (`create_workout`,
`list_workouts`) and the running read tools stay where they are; this module
adds the type-parameterized pair the agent uses for anything else (and for
strength too, if it prefers the explicit form).

Authorization is sourced from the inbound MCP request's `Authorization`
header, the same pattern every other domain module uses.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import Field

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


def _now_rfc3339() -> str:
    """Current instant as an RFC3339 UTC string (`Z` suffix). The unified
    create surface requires start_time, so an omitted one is filled with a
    precise instant here — not a local-day window, so it's unambiguous.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def register(mcp: FastMCP, api: APIClient) -> None:
    """Register the unified-activity tools on `mcp`, backed by `api`.

    Tools defined inside this function close over `api` — keeping the
    dependency explicit at the registration boundary rather than as a
    module-level global.
    """

    @mcp.tool
    async def log_activity(
        activity_type: Annotated[
            str,
            Field(
                description=(
                    "The activity type. Currently registered: 'running', "
                    "'walking', 'cycling', 'other', 'strength_training'. The "
                    "registry may grow; an unknown type returns an error whose "
                    "message lists the valid set. For strength sessions, prefer "
                    "the create_workout tool (same result, workout-shaped args)."
                )
            ),
        ],
        start_time: str | None = None,
        duration_seconds: int | None = None,
        name: str | None = None,
        notes: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Log a new activity of any registered type for the calling user.

        Identity is sourced from the inbound MCP session's Authorization
        header (the user's JWT); there is no user_id parameter.

        The `details` payload is type-specific and forwarded to the API
        verbatim, where the type's descriptor validates it:
          - endurance types ('running', 'walking', 'cycling') expect
            `{"distance_meters": <positive number>, ...}` — distance is
            required for these; optional keys include `avg_pace_sec_per_km`,
            `elevation_gain_meters`, `environment` ('outdoor'|'indoor').
          - 'other' tolerates absent/empty details (a zero-distance entry).
          - 'strength_training' expects
            `{"exercises": [{"exercise_id": <slug>, "sets": [{"reps", "weight",
            "unit"}], "superset_group"?, "notes"?}]}` — exercise order comes
            from list position. Prefer create_workout for this shape.
        An unknown `activity_type` or invalid `details` surfaces as an error
        whose message explains what the API rejected.

        Args:
            activity_type: One of the registered types (see the field note).
            start_time: Optional RFC3339 start instant, e.g.
                '2026-05-16T18:30:00Z'. Defaults to now when omitted.
            duration_seconds: Optional session length in seconds.
            name: Optional session name.
            notes: Optional free-text notes for the session.
            details: Optional type-specific payload (see above).

        Returns:
            The created activity as a unified DTO: `id`, `activity_type`,
            `start_time`, the rendered `summary` card, and the type's
            `details`.
        """
        auth = _auth_header_or_raise()
        payload: dict[str, Any] = {
            "activity_type": activity_type,
            # The unified surface requires start_time; default it to now so an
            # omitted start behaves like the workout tool's "omit = now".
            "start_time": start_time if start_time is not None else _now_rfc3339(),
        }
        if duration_seconds is not None:
            payload["duration_seconds"] = duration_seconds
        if name is not None:
            payload["name"] = name
        if notes is not None:
            payload["notes"] = notes
        if details is not None:
            payload["details"] = details
        try:
            return await api.create_activity(auth, payload)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def list_activities(
        activity_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List the calling user's activities across every type, most recent
        first.

        Identity is sourced from the inbound MCP session's Authorization
        header. Use this for runs, walks, rides, and mixed histories; for a
        strength-only view, list_workouts is the strength-typed shortcut.

        This list is INSTANT-based, not the timezone+local-date contract the
        nutrition and planned-workout lists use: the API filters on absolute
        RFC3339 instants, so pass `since`/`until` as explicit timestamps
        (e.g. "the last 7 days" -> since = now minus 7 days). The two modes
        are mutually exclusive — a `since`/`until` range cannot be combined
        with `limit`; use one or the other.

        Args:
            activity_type: Optional filter to one registered type ('running',
                'walking', 'cycling', 'other', 'strength_training'). Omit for
                all types.
            since: Optional RFC3339 lower bound (inclusive) on start_time.
            until: Optional RFC3339 upper bound on start_time.
            limit: Optional max number of most-recent activities to return
                (the API caps the page size). Do not combine with since/until.

        Returns:
            A list of unified activity DTOs: each carries `id`,
            `activity_type`, `start_time`, and the rendered `summary` card.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.list_activities(
                auth,
                activity_type=activity_type,
                since=since,
                until=until,
                limit=limit,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
