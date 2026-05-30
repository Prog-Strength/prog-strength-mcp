"""Recipe domain: MCP tools for listing and creating user recipes.

Mirrors the API's /recipes surface. Phase 2 of the daily-nutrition-log
SOW. Agent gets create + read only — update / delete intentionally
stay UI-only so the agent can't silently rewrite a saved recipe.
"""

from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field

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


class RecipeComponentInput(BaseModel):
    """One component in a recipe: a pantry item + quantity (servings)."""

    pantry_item_id: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "ID of a saved pantry item. Get one from list_pantry_items "
                "or create one inline with create_pantry_item before adding "
                "it to a recipe."
            ),
        ),
    ]
    quantity: Annotated[
        float,
        Field(
            gt=0,
            description=(
                "Number of servings of the pantry item in one batch of the "
                "recipe. '5 eggs' against a 1-egg pantry item is quantity=5."
            ),
        ),
    ]


def register(mcp: FastMCP, api: APIClient) -> None:
    """Register recipe tools on `mcp`, backed by `api`."""

    @mcp.tool
    async def list_recipes() -> list[dict[str, Any]]:
        """List the user's saved recipes.

        Each recipe carries its components (pantry item IDs +
        quantities) and the derived macros for one batch — calories,
        protein, fat, carbs already summed across components, so you
        can comment on a recipe's macros without further math.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.list_recipes(auth)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def create_recipe(
        name: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Display name, e.g. 'Standard Breakfast' or 'Post-workout shake'."
                ),
            ),
        ],
        components: Annotated[
            list[RecipeComponentInput],
            Field(
                min_length=1,
                max_length=20,
                description=(
                    "Ordered list of pantry item + quantity pairs that make "
                    "up one batch of the recipe. At least one; at most 20."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """Save a new recipe so the user can quick-log it later.

        Use this when the user describes a repeated meal — "every day
        I have five eggs, two strips of bacon, and a bagel." Returns
        the created recipe with its derived macros, which the user
        will see in the UI's recipes tab.
        """
        auth = _auth_header_or_raise()
        comps_payload = [c.model_dump() for c in components]
        try:
            return await api.create_recipe(auth, name=name, components=comps_payload)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
