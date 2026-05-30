"""Nutrition log domain: MCP tools for logging consumption and
reading historical macros.

Mirrors the API's `internal/nutrition/` log + daily-aggregate surface.
Phase 1 ships log_consumption (pantry-item-only), list_nutrition_log,
and get_daily_macros. Recipe-based logging and bodyweight live in
later phases. See prog-strength-docs/sows/daily-nutrition-log.md.
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
    """Register nutrition log tools on `mcp`, backed by `api`."""

    @mcp.tool
    async def log_consumption(
        pantry_item_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "ID of a saved pantry item. Get one from list_pantry_items "
                    "or from a fresh create_pantry_item call. Recipes will be "
                    "supported in a later phase; for now every log entry is "
                    "pantry-item-backed."
                ),
            ),
        ],
        quantity: Annotated[
            float,
            Field(
                gt=0,
                description=(
                    "How many servings of the pantry item the user ate. "
                    "Multiplied through the per-serving macros — '5 eggs' "
                    "with a 1-egg pantry item is quantity=5."
                ),
            ),
        ],
        consumed_at: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "RFC3339 UTC timestamp of when the user actually ate "
                    "the food. Omit to default to the current server time."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Log a single consumption event against a pantry item.

        Returns the created log entry with denormalized macros
        (quantity × the pantry item's per-serving macros) frozen at log
        time — a future edit to the pantry item will not retroactively
        change this entry's totals.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.log_consumption(
                auth,
                pantry_item_id=pantry_item_id,
                quantity=quantity,
                consumed_at=consumed_at,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def list_nutrition_log(
        since: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "RFC3339 UTC lower bound on consumed_at (inclusive). "
                    "Omit for no lower bound."
                ),
            ),
        ] = None,
        until: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "RFC3339 UTC upper bound on consumed_at (exclusive). "
                    "Omit for no upper bound."
                ),
            ),
        ] = None,
    ) -> list[dict[str, Any]]:
        """List the user's nutrition log entries, most recent first.

        Each entry carries denormalized macros and a reference to the
        source pantry item. For a per-day rollup over a range, prefer
        get_daily_macros — it does the aggregation server-side and
        skips the per-entry round trip.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.list_nutrition_log(auth, since=since, until=until)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def get_daily_macros(
        since: Annotated[
            str,
            Field(
                description=(
                    "RFC3339 UTC lower bound on the date range (inclusive)."
                ),
            ),
        ],
        until: Annotated[
            str,
            Field(
                description=(
                    "RFC3339 UTC upper bound on the date range (exclusive)."
                ),
            ),
        ],
    ) -> list[dict[str, Any]]:
        """Per-day totals over a date range — one row per UTC date.

        Use this for "how did my macros look this week?" prompts.
        Empty days do not appear in the response; fill gaps client-side
        only if you need a dense series for comparison.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.get_daily_macros(auth, since=since, until=until)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
