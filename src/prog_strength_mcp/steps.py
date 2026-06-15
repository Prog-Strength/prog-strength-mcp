"""Steps domain: MCP tools for logging daily step totals, reading
recent days, and getting/setting the user's daily step goal.

Mirrors the API's /steps surface. Steps are upserted per calendar
date — one count per day — so logging a day that already has a count
replaces it rather than appending. Relative phrases like "today" /
"yesterday" are resolved to an explicit YYYY-MM-DD by the caller/agent
before reaching the tool.

Authorization is sourced from the inbound MCP request's `Authorization`
header, the same pattern every other domain module uses.
"""

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


def register(mcp: FastMCP, api: APIClient) -> None:
    """Register steps tools on `mcp`, backed by `api`."""

    @mcp.tool
    async def log_steps(
        date: Annotated[
            str,
            Field(
                description=(
                    "Calendar date the step count is for, as YYYY-MM-DD. "
                    "Resolve relative phrases (\"today\", \"yesterday\") to "
                    "an explicit date before calling — the tool does not "
                    "interpret them."
                ),
            ),
        ],
        steps: Annotated[
            int,
            Field(
                ge=0,
                le=200000,
                description="Total steps walked on that date.",
            ),
        ],
    ) -> dict[str, Any]:
        """Upsert the daily step total for `date` (YYYY-MM-DD).

        Steps are stored one count per calendar date — logging a day
        that already has a count REPLACES it rather than adding to it.
        The caller/agent must resolve relative phrases ("today",
        "yesterday") to an explicit date first; this tool takes only an
        explicit YYYY-MM-DD. Returns the persisted day entry.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.log_steps(auth, date=date, steps=steps)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def get_steps(
        since: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "YYYY-MM-DD lower bound on the date (inclusive). "
                    "Omit for no lower bound."
                ),
            ),
        ] = None,
        until: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "YYYY-MM-DD upper bound on the date (inclusive). "
                    "Omit for no upper bound."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Read the user's recent daily step counts over a date range
        for coaching context.

        Pass `since`/`until` (both YYYY-MM-DD, inclusive) to bound the
        range. Returns a dict with `steps` (a list of per-day entries,
        most recent first) and `next_before` (an opaque pagination
        cursor, or null when there are no more days).
        """
        auth = _auth_header_or_raise()
        try:
            return await api.get_steps(auth, since=since, until=until)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def get_steps_goal() -> dict[str, Any]:
        """Return the user's daily step goal.

        Returns a dict with `goal` plus `created_at` / `updated_at`.
        Use this to comment on whether logged days are hitting the
        target.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.get_steps_goal(auth)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def set_steps_goal(
        goal: Annotated[
            int,
            Field(
                gt=0,
                le=200000,
                description="The user's daily step target.",
            ),
        ],
    ) -> dict[str, Any]:
        """Set the user's daily step goal.

        Set-replacement: this overwrites any existing goal. Returns the
        persisted goal.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.set_steps_goal(auth, goal=goal)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
