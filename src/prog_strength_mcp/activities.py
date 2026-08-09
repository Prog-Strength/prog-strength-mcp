"""Activities domain: the canonical, type-agnostic MCP tools over the
unified `/activities` surface (api PR #79).

`log_activity`, `list_activities`, and `get_activity` are the generic front
doors for every registered activity type — running, walking, cycling, hiking,
other, and strength_training. The strength-typed conveniences
(`create_workout`, `list_workouts`) and the running read tools stay where they
are; this module adds the type-parameterized set the agent uses for anything
else (and for strength too, if it prefers the explicit form).

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


# Detail-DTO keys dropped before the activity reaches the model.
#
# `trackpoints` is hundreds of per-second GPS/heart-rate samples and `route`
# is a serialized GeoJSON geometry. Both exist to draw a map: there is
# nothing in either one a language model can reason about, and on a long run
# they would dominate the response and crowd the actual conversation out of
# the context window. Everything derived from them that IS reasonable to
# reason about — `splits`, `strip_summary`, `heart_rate_zones`, `intervals` —
# is already an aggregate and is kept.
_RENDERING_ONLY_KEYS = frozenset({"trackpoints", "route"})


def _number(value: Any) -> float | None:
    """`value` as a float, or None when it's absent or not a number.

    Every weather reading field is optional on the wire (the API omits the
    null ones), so any single one can be missing from an otherwise-`ok` row.
    `bool` is excluded explicitly because it is an `int` in Python.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _celsius_to_fahrenheit(celsius: float) -> float:
    return round(celsius * 9 / 5 + 32, 1)


def _kmh_to_mph(kmh: float) -> float:
    return round(kmh / 1.609344, 1)  # a mile is exactly 1.609344 km


# metric key -> (imperial key, conversion). The API serves weather metric,
# following the raw-measurement convention of the rest of the activity DTO
# (`distance_meters` and friends) and leaving display units to the client.
_WEATHER_IMPERIAL_FIELDS = {
    "temp_c": ("temp_f", _celsius_to_fahrenheit),
    "feels_like_c": ("feels_like_f", _celsius_to_fahrenheit),
    "dew_point_c": ("dew_point_f", _celsius_to_fahrenheit),
    "wind_kmh": ("wind_mph", _kmh_to_mph),
}


def _dual_unit_weather(weather: dict[str, Any]) -> dict[str, Any]:
    """A copy of the weather block carrying imperial fields beside the metric
    ones the API stores.

    Two multiplications here remove an entire class of quiet arithmetic error
    from the model's answer — it never has to convert °C or km/h itself. A
    field the API omitted stays omitted rather than gaining an invented 0.0.
    """
    out = dict(weather)
    for metric_key, (imperial_key, convert) in _WEATHER_IMPERIAL_FIELDS.items():
        value = _number(weather.get(metric_key))
        if value is not None:
            out[imperial_key] = convert(value)
    return out


def _for_agent(activity: dict[str, Any]) -> dict[str, Any]:
    """The detail DTO as the model should see it: rendering data dropped,
    weather in both unit systems. Builds new dicts throughout, so the payload
    handed in is never mutated.
    """
    out = {k: v for k, v in activity.items() if k not in _RENDERING_ONLY_KEYS}
    weather = out.get("weather")
    # Absence is the answer, not an error: an activity with no stored reading
    # simply has no `weather` key, and a non-`ok` row (no GPS, or the provider
    # had nothing for that hour) carries a status and no readings to convert.
    if isinstance(weather, dict) and weather.get("status") == "ok":
        out["weather"] = _dual_unit_weather(weather)
    return out


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
                    "'walking', 'cycling', 'hiking', 'other', 'strength_training'. "
                    "The registry may grow; an unknown type returns an error whose "
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
          - endurance types ('running', 'walking', 'cycling', 'hiking') expect
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
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List the calling user's activities across every type, most recent
        first.

        Identity is sourced from the inbound MCP session's Authorization
        header. Use this for runs, walks, rides, and mixed histories; for a
        strength-only view, list_workouts is the strength-typed shortcut.

        This tool deliberately exposes NO date-range parameters: constructing
        UTC bounds for a user-local day is a known bug source, so never
        fabricate timestamps to scope this list. For date-scoped questions
        ("what did I run on Tuesday?", "activities last week") prefer
        get_training_snapshot, which takes a timezone plus local YYYY-MM-DD
        dates and resolves the day boundaries server-side. Alternatively,
        call this list with a generous `limit` and filter the returned
        `start_time` values yourself.

        Args:
            activity_type: Optional filter to one registered type ('running',
                'walking', 'cycling', 'hiking', 'other', 'strength_training').
                Omit for all types.
            limit: Optional max number of most-recent activities to return
                (the API defaults to 50 and caps the page at 100).

        Returns:
            A list of unified activity DTOs: each carries `id`,
            `activity_type`, `start_time`, and the rendered `summary` card.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.list_activities(
                auth,
                activity_type=activity_type,
                limit=limit,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def get_activity(
        activity_id: Annotated[
            str,
            Field(
                description=(
                    "The activity's ID, as returned by list_activities or "
                    "get_training_snapshot. Never guess one."
                )
            ),
        ],
    ) -> dict[str, Any]:
        """Read ONE activity in full — the detail behind a list_activities entry.

        Identity is sourced from the inbound MCP session's Authorization
        header; the API enforces ownership, so an ID that doesn't exist or
        isn't the caller's surfaces as a not-found error.

        Use this for any question about a single session that the list card
        doesn't answer: splits, heart-rate zones, intervals, elevation, plan
        linkage, notes — and, for outdoor GPS activities, the weather at the
        moment it started. Get the ID from list_activities (or
        get_training_snapshot) first.

        Two things about the shape of the response are deliberate:

        - `trackpoints` and `route` are OMITTED. They are per-second samples
          and a GeoJSON geometry — map-drawing data with nothing in it a model
          can reason about, and on a long run they would dwarf the rest of the
          response. Every aggregate derived from them is kept (`splits`,
          `strip_summary`, `heart_rate_zones`, `intervals`), so their absence
          is never evidence that the activity had no GPS.
        - `weather`, when present, is DUAL-UNIT: `temp_c` and `temp_f`,
          `feels_like_c`/`feels_like_f`, `dew_point_c`/`dew_point_f`,
          `wind_kmh`/`wind_mph`, plus `humidity` (%), `wind_deg` (the
          direction the wind came FROM), `precip_mm`, `condition`, and `icon`.
          Quote whichever unit system the user speaks in; never convert
          yourself.

        The `weather` key is simply absent when no reading was ever stored —
        indoor sessions, activities without GPS, and anything imported before
        capture existed. That means the conditions are unknown, not that
        something went wrong. A `weather.status` other than "ok" means the
        same thing and carries no readings.

        Args:
            activity_id: The activity to read.

        Returns:
            The unified activity DTO — `id`, `activity_type`, `start_time`,
            the rendered `summary` card, the type's `details`, and whichever
            of `splits`, `strip_summary`, `heart_rate_zones`, `intervals`, and
            `weather` this activity has — with `trackpoints` and `route`
            removed.
        """
        auth = _auth_header_or_raise()
        try:
            activity = await api.get_activity(auth, activity_id)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
        return _for_agent(activity)
