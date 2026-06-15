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

from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

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
        distance — what they could run *right now* at full effort, modeled
        from recent training. This is DISTINCT from get_running_best_efforts,
        which reports the fastest the user has *actually* run; this is a
        forward-looking estimate of current fitness, not a logged result.

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
