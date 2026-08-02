"""Blood-pressure domain: MCP tools for logging cuff readings and
reading historical values.

Mirrors the API's /blood-pressure surface. A pure forwarder — no
classification (normal/elevated/etc.), no averaging, no validation
beyond the pydantic Field bounds. Corrections go through the UI.
"""

from typing import Annotated, Any

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
    """Register blood-pressure tools on `mcp`, backed by `api`."""

    @mcp.tool
    async def log_blood_pressure(
        systolic: Annotated[
            int,
            Field(
                ge=50,
                le=300,
                description=(
                    "Systolic pressure — the HIGHER of the two numbers, the "
                    "pressure during a heartbeat. In '122 over 78' this is 122."
                ),
            ),
        ],
        diastolic: Annotated[
            int,
            Field(
                ge=30,
                le=200,
                description=(
                    "Diastolic pressure — the LOWER of the two numbers, the "
                    "pressure between beats. In '122 over 78' this is 78."
                ),
            ),
        ],
        pulse: Annotated[
            int | None,
            Field(
                default=None,
                ge=20,
                le=250,
                description=(
                    "Heart rate in beats per minute, if the cuff reported one. "
                    "Omit when the user didn't mention it."
                ),
            ),
        ] = None,
        measured_at: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "RFC3339 UTC timestamp of when the reading was taken. Omit "
                    "to default to now. The agent resolves relative phrases like "
                    "'this morning' before calling."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Log a single blood-pressure reading (systolic/diastolic, optional pulse)."""
        auth = _auth_header_or_raise()
        try:
            return await api.log_blood_pressure(
                auth,
                systolic=systolic,
                diastolic=diastolic,
                pulse=pulse,
                measured_at=measured_at,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def list_blood_pressure(
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
        """List the user's blood-pressure entries, most recent first."""
        auth = _auth_header_or_raise()
        try:
            return await api.list_blood_pressure(auth, since=since, until=until)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
