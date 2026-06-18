"""Nutrition log domain: MCP tools for logging consumption and
reading historical macros.

Mirrors the API's `internal/nutrition/` log + daily-aggregate surface.
Phase 1 ships log_consumption_batch (pantry/recipe/custom items in one
call), list_nutrition_log, and get_daily_macros. Bodyweight lives in a
later phase. See prog-strength-docs/sows/daily-nutrition-log.md.
"""

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field

from prog_strength_mcp.api_client import APIClient, APIError

_MEAL = Literal["breakfast", "lunch", "dinner", "snack"]


class PantryItem(BaseModel):
    kind: Literal["pantry"]
    pantry_item_id: str
    quantity: float = Field(gt=0)
    meal: _MEAL
    consumed_at: str | None = None


class RecipeItem(BaseModel):
    kind: Literal["recipe"]
    recipe_id: str
    quantity: float = Field(gt=0)
    meal: _MEAL
    consumed_at: str | None = None


class CustomItem(BaseModel):
    kind: Literal["custom"]
    name: str = Field(min_length=1, max_length=200)
    calories: float = Field(ge=0, le=100_000)
    protein_g: float = Field(ge=0, le=10_000)
    fat_g: float = Field(ge=0, le=10_000)
    carbs_g: float = Field(ge=0, le=10_000)
    meal: _MEAL
    consumed_at: str | None = None


Item = Annotated[PantryItem | RecipeItem | CustomItem, Field(discriminator="kind")]


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
    async def log_consumption_batch(
        items: Annotated[
            list[Item],
            Field(
                min_length=1,
                description=(
                    "Every food the user mentioned in their message, as one "
                    "list. A snack of two foods is two items in one call; a "
                    "mixed meal can combine pantry-backed and custom items. "
                    "Set each item's `kind`: use 'pantry'/'recipe' when a "
                    "saved item matches (check the pantry first), otherwise "
                    "'custom' with your best-estimate macros."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """Log everything the user ate in one message as a single call.

        Collect EVERY food the user mentioned into one `items` list rather
        than calling this tool once per food. Each item carries its own
        `meal` bucket and optional `consumed_at`, so one call can span
        breakfast + a snack or backfill several entries at different times.

        For each item, check `list_pantry_items` first: if a saved pantry
        item or recipe matches, use kind "pantry"/"recipe" with its id and a
        `quantity` of servings/batches (5 eggs against a 1-egg pantry item is
        quantity=5; half a recipe is 0.5). Otherwise use kind "custom" with
        the food's name and your best-estimate total macros as the user ate
        them.

        Logging is best-effort: each item is logged independently and the
        response's `results`/`logged`/`failed` report which items (if any)
        did not log, so you can tell the user. `meal` is one of breakfast,
        lunch, dinner, snack. `consumed_at` is an RFC3339 UTC timestamp;
        omit it to default to now.
        """
        auth = _auth_header_or_raise()
        payload = [item.model_dump(exclude_none=True) for item in items]
        try:
            return await api.log_consumption_batch(auth, items=payload)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def list_nutrition_log(
        timezone: Annotated[
            str,
            Field(
                description=(
                    "IANA timezone (e.g. America/Denver) the date params are interpreted in."
                ),
            ),
        ],
        date: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Single calendar day, YYYY-MM-DD. Mutually exclusive with start_date/end_date."
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
                    "IANA timezone (e.g. America/Denver) the date params are interpreted in."
                ),
            ),
        ],
        date: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Single calendar day, YYYY-MM-DD. Mutually exclusive with start_date/end_date."
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
