"""Bodyweight domain: MCP tools for logging scale readings and
reading historical trends.

Mirrors the API's /bodyweight surface. Phase 3 of the
daily-nutrition-log SOW. Agent gets create + read only — corrections
go through the UI, which deletes + re-creates to keep the trend
chart's audit trail clean.
"""

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import Field

from prog_strength_mcp.api_client import APIClient, APIError


def _auth_header_or_raise() -> str:
    """Pull the inbound Authorization header. Tools that require auth
    call this before forwarding to the API.
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
    """Register bodyweight tools on `mcp`, backed by `api`."""

    @mcp.tool
    async def log_bodyweight(
        weight: Annotated[
            float,
            Field(
                gt=0,
                description="Scale reading. Magnitude only — unit is the next arg.",
            ),
        ],
        unit: Annotated[
            Literal["lb", "kg"] | None,
            Field(
                default=None,
                description=(
                    "Weight unit. Omit to default to the user's preferred "
                    "WeightUnit (set on their profile). Override only when "
                    "the user is explicit about the unit in chat."
                ),
            ),
        ] = None,
        measured_at: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "RFC3339 UTC timestamp of when the user actually "
                    "weighed in. Omit to default to the current server "
                    "time. Most users weigh themselves in the morning; "
                    "logging via chat later in the day is the case where "
                    "supplying an explicit morning timestamp helps."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Log a single bodyweight reading.

        Returns the created entry. There's no update tool — to fix a
        bad reading, the user deletes it in the UI and logs the right
        value. The audit trail stays clean.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.log_bodyweight(
                auth, weight=weight, unit=unit, measured_at=measured_at
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def list_bodyweight(
        since: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "RFC3339 UTC lower bound on measured_at (inclusive). "
                    "Omit for no lower bound."
                ),
            ),
        ] = None,
        until: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "RFC3339 UTC upper bound on measured_at (exclusive). "
                    "Omit for no upper bound."
                ),
            ),
        ] = None,
    ) -> list[dict[str, Any]]:
        """List the user's bodyweight entries, most recent first.

        Pair with get_daily_macros (or list_nutrition_log) to comment
        on weight trajectory against caloric intake — deficit, surplus,
        or roughly at maintenance.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.list_bodyweight(auth, since=since, until=until)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
