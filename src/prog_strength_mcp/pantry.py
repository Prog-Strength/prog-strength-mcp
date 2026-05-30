"""Pantry domain: MCP tools for reading and creating user pantry items.

Mirrors the API's `internal/nutrition/` package. Phase 1 exposes
create + list only; update / delete intentionally stay UI-only so the
agent can't silently rewrite a user's saved foods. See
prog-strength-docs/sows/daily-nutrition-log.md.
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
    """Register pantry tools on `mcp`, backed by `api`."""

    @mcp.tool
    async def list_pantry_items(
        query: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Optional case-insensitive substring filter on item "
                    "name. Useful for narrowing down a large pantry."
                ),
            ),
        ] = None,
    ) -> list[dict[str, Any]]:
        """List the user's saved pantry items, sorted alphabetically.

        Each item carries per-serving macros (calories, protein, fat,
        carbs), a serving size + unit (e.g. 1 + 'egg', 100 + 'g'), and
        an ID you'll need to call log_consumption against. Soft-deleted
        items are excluded server-side.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.list_pantry_items(auth, query=query)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def create_pantry_item(
        name: Annotated[
            str, Field(min_length=1, description="Display name, e.g. 'Eggland's Best Large Egg'.")
        ],
        calories: Annotated[
            float, Field(ge=0, description="Calories per serving. Non-negative.")
        ],
        protein_g: Annotated[
            float, Field(ge=0, description="Grams of protein per serving. Non-negative.")
        ],
        fat_g: Annotated[
            float, Field(ge=0, description="Grams of fat per serving. Non-negative.")
        ],
        carbs_g: Annotated[
            float, Field(ge=0, description="Grams of carbs per serving. Non-negative.")
        ],
        serving_size: Annotated[
            float,
            Field(
                gt=0,
                description=(
                    "Numeric size of one serving. Combine with serving_unit: "
                    "e.g. 1 + 'egg', 100 + 'g', 1 + 'cup'."
                ),
            ),
        ],
        serving_unit: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Free-text unit label. The math is based on quantity × "
                    "per-serving macros; the unit is descriptive for the "
                    "user, not normalized by the API."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """Save a new pantry item so the user can log it later.

        Use this when the user describes a food they expect to eat
        again. For a one-off restaurant meal, you can also create the
        item here and immediately call log_consumption against the
        returned ID — the pantry will accumulate, which is the
        intended UX.

        Returns the created item including its server-assigned `id`,
        which you'll pass to log_consumption.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.create_pantry_item(
                auth,
                name=name,
                calories=calories,
                protein_g=protein_g,
                fat_g=fat_g,
                carbs_g=carbs_g,
                serving_size=serving_size,
                serving_unit=serving_unit,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
