"""Whoop domain: MCP tools for reading the user's Whoop recovery data.

Mirrors the API's /whoop surface. Recovery is one record per calendar
date — recovery score, resting heart rate, and HRV — resolved to the
user's local calendar dates via a required IANA timezone. Relative
phrases like "this week" are resolved to explicit YYYY-MM-DD bounds by
the caller/agent before reaching the tool.

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
    """Register whoop tools on `mcp`, backed by `api`."""

    @mcp.tool
    async def get_whoop_recovery(
        timezone: Annotated[
            str,
            Field(
                description=(
                    'IANA timezone name (e.g. "America/Denver") used to '
                    "resolve local dates. Required."
                ),
            ),
        ],
        since: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "YYYY-MM-DD lower bound on the date (inclusive). Omit "
                    "for no lower bound. Resolve relative phrases to explicit "
                    "dates before calling."
                ),
            ),
        ] = None,
        until: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "YYYY-MM-DD upper bound on the date (inclusive). Omit "
                    "for no upper bound. Resolve relative phrases to explicit "
                    "dates before calling."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Read the user's daily Whoop recovery — recovery score (0–100),
        resting heart rate (bpm), and HRV (rmssd, ms) — over a local-date
        range for coaching context.

        `timezone` (IANA) resolves the local calendar dates; pass
        `since`/`until` (both YYYY-MM-DD, inclusive) to bound the range.
        Returns a dict with `recovery` (a list of per-day records, most
        recent first).

        An empty result for a user who mentions their Whoop most likely
        means the integration isn't connected — point them to
        **Settings → Integrations** to connect it.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.get_whoop_recovery(auth, timezone=timezone, since=since, until=until)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
