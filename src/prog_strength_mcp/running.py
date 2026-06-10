"""Running domain: MCP tools for reading the user's running data.

This is the first running-domain MCP module — it mirrors the API's
running surface (`GET /running/best-efforts`), giving the agent its
first read access to the running side of training. Future running tools
(e.g. list/get individual activities) land here rather than in a new
module per tool, matching the per-domain grouping the other modules use.

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
