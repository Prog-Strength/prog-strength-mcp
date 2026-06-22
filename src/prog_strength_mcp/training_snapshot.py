"""Training-snapshot domain: a single MCP tool that forwards to the API's
GET /training-snapshot — a holistic, pre-aggregated view across strength,
running, steps, bodyweight, and nutrition for a date window.

Pure forwarder, following the steps.py / nutrition.py pattern: it reads
the inbound Authorization header, calls APIClient.get_training_snapshot,
unwraps the `{service, message, data}` envelope, and surfaces APIError as
RuntimeError. No aggregation happens here — the API owns it.
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
    """Register the training-snapshot tool on `mcp`, backed by `api`."""

    @mcp.tool
    async def get_training_snapshot(
        timezone: Annotated[
            str,
            Field(description="IANA timezone name, e.g. 'America/Denver'. Required."),
        ],
        date: Annotated[
            str | None,
            Field(
                default=None,
                description="Single day as YYYY-MM-DD. Mutually exclusive with the range.",
            ),
        ] = None,
        start_date: Annotated[
            str | None,
            Field(default=None, description="Range start (YYYY-MM-DD); use with end_date."),
        ] = None,
        end_date: Annotated[
            str | None,
            Field(default=None, description="Range end (YYYY-MM-DD); use with start_date."),
        ] = None,
    ) -> dict[str, Any]:
        """Holistic training snapshot for a date window — strength, running,
        steps, bodyweight, and nutrition, pre-aggregated for analysis. Supply an
        IANA `timezone` plus either a single `date` or a `start_date`/`end_date`
        range (YYYY-MM-DD); omit dates for the trailing 7 days. Use this for any
        "how did my training go" question over a period before reaching for the
        per-domain list tools.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.get_training_snapshot(
                auth, timezone=timezone, date=date, start_date=start_date, end_date=end_date
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
