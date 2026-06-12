"""MCP tool surface for nutrition lookup.

Unlike the other nutrition tools this one needs no Authorization
header — it reads public nutrition databases, never user data.
"""

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from prog_strength_mcp.nutrition_lookup.service import NutritionLookupService


def register(mcp: FastMCP, service: NutritionLookupService) -> None:
    """Register the lookup tool on `mcp`, backed by `service`."""

    @mcp.tool
    async def lookup_food_nutrition(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=(
                    "The food to look up, including the brand or chain name "
                    'when the user gave one — "Chick-fil-A chicken minis", '
                    '"Fage 2% greek yogurt", "scrambled eggs". Describe ONE '
                    "food per call; look up a burger and its fries as two "
                    "calls."
                ),
            ),
        ],
        quantity: Annotated[
            float,
            Field(
                gt=0,
                default=1,
                description=(
                    "How many of the matched serving the user ate — '10 "
                    "chicken minis' is quantity=10 against a per-mini "
                    "serving. Each match's total_for_quantity is computed "
                    "here in code; use it as-is, never multiply macros "
                    "yourself."
                ),
            ),
        ] = 1,
        max_results: Annotated[
            int,
            Field(ge=1, le=10, default=5, description="Maximum candidates to return."),
        ] = 5,
    ) -> dict[str, Any]:
        """Look up real nutrition data for a food by name from established
        databases (FatSecret for restaurant/branded foods, USDA FoodData
        Central for generic foods).

        Use this BEFORE estimating macros for any custom meal that isn't
        in the user's pantry. Returns {"matches": [...]} where each match
        has per_serving and total_for_quantity macro blocks, a
        serving_description, and a `source` to cite. Prefer an exact
        brand/chain match without a plausibility_warning. Returns
        {"error": ...} when no provider is configured or all providers
        failed — in that case, estimate yourself and tell the user it's
        an estimate.
        """
        return await service.lookup(query, quantity, max_results)
