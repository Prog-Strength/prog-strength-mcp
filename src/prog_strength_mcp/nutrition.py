"""Nutrition log domain: MCP tools for logging consumption and
reading historical macros.

Mirrors the API's `internal/nutrition/` log + daily-aggregate surface.
Phase 1 ships log_consumption (pantry-item-only), list_nutrition_log,
and get_daily_macros. Recipe-based logging and bodyweight live in
later phases. See prog-strength-docs/sows/daily-nutrition-log.md.
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
    """Register nutrition log tools on `mcp`, backed by `api`."""

    @mcp.tool
    async def log_consumption(
        quantity: Annotated[
            float,
            Field(
                gt=0,
                description=(
                    "How many servings (for a pantry item) or batches (for "
                    "a recipe) the user ate. Multiplied through the source's "
                    "per-serving macros — '5 eggs' with a 1-egg pantry item "
                    "is quantity=5; 'half a recipe' is quantity=0.5."
                ),
            ),
        ],
        meal: Annotated[
            Literal["breakfast", "lunch", "dinner", "snack"],
            Field(
                description=(
                    "Which meal bucket the entry rolls into on the user's "
                    "nutrition page. Pick from explicit cues in the user's "
                    "message ('for breakfast I had…' → breakfast), the time "
                    "of day implied by context, or default to 'snack' for "
                    "off-meal foods like coffee, fruit, or a protein bar."
                ),
            ),
        ],
        pantry_item_id: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "ID of a saved pantry item. Pass exactly one of "
                    "pantry_item_id or recipe_id."
                ),
            ),
        ] = None,
        recipe_id: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "ID of a saved recipe. Pass exactly one of pantry_item_id "
                    "or recipe_id. When the user says 'my usual breakfast' "
                    "and you've matched it to a recipe, pass that recipe's ID."
                ),
            ),
        ] = None,
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
        """Log a single consumption event against a pantry item or recipe.

        Returns the created log entry with denormalized macros frozen
        at log time — a future edit to the pantry item or recipe will
        not retroactively change this entry's totals.
        """
        if (pantry_item_id is None) == (recipe_id is None):
            raise RuntimeError(
                "log_consumption requires exactly one of pantry_item_id or recipe_id."
            )
        auth = _auth_header_or_raise()
        try:
            return await api.log_consumption(
                auth,
                pantry_item_id=pantry_item_id,
                recipe_id=recipe_id,
                quantity=quantity,
                meal=meal,
                consumed_at=consumed_at,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def log_custom_meal(
        name: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=(
                    "What the user ate. Free-form text the user types or you "
                    'extract from their message — "Chipotle chicken bowl", '
                    '"Sweetgreen Harvest Bowl", "airport protein bar". '
                    "Stored as-is on the log entry; appears in the user's "
                    "nutrition log under that exact name."
                ),
            ),
        ],
        calories: Annotated[
            float,
            Field(ge=0, le=100_000, description="Total calories for the meal as the user ate it."),
        ],
        protein_g: Annotated[float, Field(ge=0, le=10_000, description="Total protein in grams.")],
        fat_g: Annotated[float, Field(ge=0, le=10_000, description="Total fat in grams.")],
        carbs_g: Annotated[
            float, Field(ge=0, le=10_000, description="Total carbohydrates in grams.")
        ],
        meal: Annotated[
            Literal["breakfast", "lunch", "dinner", "snack"],
            Field(description="Meal bucket on the user's nutrition page."),
        ],
        consumed_at: Annotated[
            str | None,
            Field(default=None, description="RFC3339 UTC timestamp; omit for now."),
        ] = None,
    ) -> dict[str, Any]:
        """Log a one-off meal that isn't backed by a pantry item or recipe.

        Use this when the user describes eating something they don't have
        saved — restaurant meals, foods bought outside, anything one-off.
        Always check `list_pantry_items` first; if there's a match, use
        `log_consumption` against that match instead.

        Returns the created log entry with the user-typed name and macros
        frozen on the row.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.log_custom_meal(
                auth,
                name=name,
                calories=calories,
                protein_g=protein_g,
                fat_g=fat_g,
                carbs_g=carbs_g,
                meal=meal,
                consumed_at=consumed_at,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def list_nutrition_log(
        timezone: Annotated[
            str,
            Field(
                description=(
                    "IANA timezone (e.g. America/Denver) the date params "
                    "are interpreted in."
                ),
            ),
        ],
        date: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Single calendar day, YYYY-MM-DD. Mutually exclusive "
                    "with start_date/end_date."
                ),
            ),
        ] = None,
        start_date: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Inclusive start of a multi-day range, YYYY-MM-DD. "
                    "Required if end_date is supplied."
                ),
            ),
        ] = None,
        end_date: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Inclusive end of a multi-day range, YYYY-MM-DD. "
                    "Required if start_date is supplied."
                ),
            ),
        ] = None,
    ) -> list[dict[str, Any]]:
        """List the user's nutrition log entries, most recent first.

        Each entry carries denormalized macros and a reference to the
        source pantry item. Dates are interpreted in the supplied IANA
        `timezone`; pass either `date` for a single day or
        `start_date`+`end_date` for a range (the API validates that
        exactly one shape is supplied).

        For totals over a day or a range, use get_daily_macros — it
        returns sums computed by the API. Do not list entries and sum
        macros yourself; arithmetic across many items is unreliable.
        """
        auth = _auth_header_or_raise()
        if not timezone:
            raise RuntimeError(
                "list_nutrition_log requires a timezone (IANA name like America/Denver)."
            )
        try:
            return await api.list_nutrition_log(
                auth,
                timezone=timezone,
                date=date,
                start_date=start_date,
                end_date=end_date,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def get_daily_macros(
        timezone: Annotated[
            str,
            Field(
                description=(
                    "IANA timezone (e.g. America/Denver) the date params "
                    "are interpreted in."
                ),
            ),
        ],
        date: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Single calendar day, YYYY-MM-DD. Mutually exclusive "
                    "with start_date/end_date."
                ),
            ),
        ] = None,
        start_date: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Inclusive start of a multi-day range, YYYY-MM-DD. "
                    "Required if end_date is supplied."
                ),
            ),
        ] = None,
        end_date: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Inclusive end of a multi-day range, YYYY-MM-DD. "
                    "Required if start_date is supplied."
                ),
            ),
        ] = None,
    ) -> list[dict[str, Any]]:
        """Per-day macro totals, one row per user-local calendar date in
        the supplied IANA `timezone`.

        Use this for "how did my macros look this week?" prompts. Pass
        exactly one of `date` (single day) or `start_date`+`end_date`
        (range), all YYYY-MM-DD — the API validates the one-of constraint.
        Empty days do not appear in the response; fill gaps client-side
        only if you need a dense series for comparison.
        """
        auth = _auth_header_or_raise()
        if not timezone:
            raise RuntimeError(
                "get_daily_macros requires a timezone (IANA name like America/Denver)."
            )
        try:
            return await api.get_daily_macros(
                auth,
                timezone=timezone,
                date=date,
                start_date=start_date,
                end_date=end_date,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
