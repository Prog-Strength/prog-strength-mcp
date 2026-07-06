"""Running domain: MCP tools for reading the user's running data.

This module mirrors the API's running surface, giving the agent read
access to the running side of training: `get_running_best_efforts`
(the fastest the user has *actually* run each standard distance) and
`get_running_max_effort_estimate` (the *predicted* time they could run
right now at max effort). Future running tools (e.g. list/get individual
activities) land here rather than in a new module per tool, matching the
per-domain grouping the other modules use.

Authorization is sourced from the inbound MCP request's `Authorization`
header, the same pattern every other domain module uses.
"""

from typing import Annotated, Any, Literal

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


def register(mcp: FastMCP, api: APIClient) -> None:
    """Register running tools on `mcp`, backed by `api`.

    Tools defined inside this function close over `api` — keeping the
    dependency explicit at the registration boundary rather than as a
    module-level global.
    """

    @mcp.tool
    async def get_running_best_efforts() -> dict[str, Any]:
        """Return the calling user's current best time across each standard
        running distance (1 mile, 2 mile, 5K, 10K, half marathon, marathon).

        A "best effort" at a given distance is the fastest window of that
        length found inside any of the user's running activities — including
        a fast segment embedded inside a longer run, not just runs that
        happen to total that distance. Distances the user has never covered
        are absent from the response.

        Use this for any "what's my fastest 5K?" / "PR" / "personal best"
        question on the running side. For lifting PRs, use the dedicated
        lifting endpoints (those live on the workout / personal_records
        surfaces, not here).

        Returns:
            A dict with key `best_efforts`, a list of entries each carrying
            the distance, duration, derived pace, and the activity that set
            the record. The list is sorted shortest distance first.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.list_running_best_efforts(auth)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def get_running_max_effort_estimate(
        distance_key: str | None = None,
    ) -> dict[str, Any]:
        """Return the user's PREDICTED max-effort time per standard running
        distance — what they could run *right now* at full effort (estimator
        v2.0.0). Estimates are floored at logged bests: they will never be
        slower than the fastest time the user has already run at that distance.
        Set birthdate and sex under Settings to sharpen demographic priors.

        This is DISTINCT from get_running_best_efforts, which reports the
        fastest the user has *actually* run; this is a forward-looking estimate
        of current fitness, not a logged result.

        Omit `distance_key` for the cross-distance summary across all six
        standard distances (1mi, 2mi, 5k, 10k, half_marathon, marathon).
        Pass one of those keys for the per-distance detail: the point
        estimate plus its confidence band, the estimate-over-time history,
        the underlying attempts, and stat tiles.

        Use this for coaching questions about current potential — e.g.
        whether the user is "on track to break 22:00 for the 5K." Each
        estimate carries a confidence band and a `basis` label describing
        what it was derived from, and may be null when there's insufficient
        data to model a distance.

        Args:
            distance_key: One of 1mi, 2mi, 5k, 10k, half_marathon, marathon
                for the per-distance detail; omit for the cross-distance
                summary.

        Returns:
            For the summary, a dict with `estimator_version` and a
            `distances` list. For a single distance, a dict with the
            distance's `estimate`, `actual_best`, `estimate_history`,
            `attempts`, and `stats`.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.get_running_max_effort_estimate(
                auth, distance_key=distance_key
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def set_run_environment(
        activity_id: Annotated[str, Field(description="The running activity ID to retag.")],
        environment: Annotated[
            Literal["outdoor", "indoor"],
            Field(description="'indoor' for treadmill runs (no GPS), 'outdoor' for GPS runs."),
        ],
    ) -> dict[str, Any]:
        """Tag a run as indoor (treadmill) or outdoor.

        Indoor/treadmill runs are recorded without GPS; their distance comes from
        the watch footpod and is user-calibrated. Tagging a run 'indoor' removes
        it from running PRs / best-efforts; 'outdoor' restores it. You must tag a
        run 'indoor' before its distance can be calibrated with
        calibrate_run_distance. Returns the updated activity.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.set_run_environment(auth, activity_id, environment=environment)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def calibrate_run_distance(
        activity_id: Annotated[
            str, Field(description="The indoor running activity ID to calibrate.")
        ],
        distance_meters: Annotated[
            float, Field(gt=0, description="The corrected total distance in meters.")
        ],
    ) -> dict[str, Any]:
        """Calibrate the distance of an indoor/treadmill run.

        Treadmill footpod distance is often wrong; set the corrected total
        distance (e.g. from the treadmill console) and the server rescales pace
        and every trackpoint by a uniform factor in one step. Only allowed on runs
        already tagged 'indoor' (use set_run_environment first if needed) — the
        API rejects calibration of an outdoor run. Returns the updated activity
        with rescaled trackpoints.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.calibrate_run_distance(
                auth, activity_id, distance_meters=distance_meters
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
