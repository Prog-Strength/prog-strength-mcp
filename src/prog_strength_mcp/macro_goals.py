"""Daily macro-goals domain: MCP tools for reading and writing the
user's per-day protein / carbs / fat / calorie targets.

Wraps the API's /me/macro-goals surface. The agent composes
get_macro_goals with get_daily_macros to answer "how am I doing on
protein today?" in prose — there is intentionally no precomputed
"compare today to goals" tool, since the agent's reasoning is what
turns the two reads into a useful answer (see
prog-strength-docs/sows/daily-macro-goals.md §MCP tools).
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
    """Register macro-goals tools on `mcp`, backed by `api`."""

    @mcp.tool
    async def get_macro_goals() -> dict[str, Any]:
        """Read the user's daily macro targets (protein, carbs, fat,
        calories).

        The API always returns 200. When the user has never set goals
        the response has all four numbers at 0 and null created_at /
        updated_at — that's the "not set yet" signal. The agent should
        read those nulls as "the user hasn't picked targets" and say
        so in conversation rather than answering with zeros.

        Pair with `get_daily_macros` for "how am I doing today?"
        prompts: read both, do the comparison in prose. There is no
        precomputed comparison tool by design.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.get_macro_goals(auth)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e

    @mcp.tool
    async def set_macro_goals(
        protein_g: Annotated[
            int,
            Field(
                ge=0,
                le=10_000,
                description=(
                    "Daily protein target in grams. The API rejects "
                    "values above 10,000 (typo guard — no realistic "
                    "intake reaches it)."
                ),
            ),
        ],
        carbs_g: Annotated[
            int,
            Field(
                ge=0,
                le=10_000,
                description="Daily carbohydrate target in grams. Same bounds as protein.",
            ),
        ],
        fat_g: Annotated[
            int,
            Field(
                ge=0,
                le=10_000,
                description="Daily fat target in grams. Same bounds as protein.",
            ),
        ],
        calories: Annotated[
            int,
            Field(
                ge=0,
                le=100_000,
                description=(
                    "Daily calorie target. Bounded separately from the "
                    "macros because calories sum across them — the cap is 100,000."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """Replace the user's daily macro targets with the supplied
        four numbers. Set-replacement semantics: pass ALL four values
        every call, even when the user only asked to change one.

        Workflow for "bump my protein to 200":

        1. Call `get_macro_goals` to read the current values.
        2. Apply the user's diff to the relevant field.
        3. Call this tool with all four numbers, the unchanged three
           taken verbatim from step 1.

        The API does not enforce calorie consistency with the macro
        breakdown — the user is allowed to set
        protein=180/carbs=300/fat=70/calories=2400 even though those
        macros sum to 2,550 kcal. Mention the mismatch in your reply
        if the user might benefit from knowing, but do not refuse the
        write.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.put_macro_goals(
                auth,
                protein_g=protein_g,
                carbs_g=carbs_g,
                fat_g=fat_g,
                calories=calories,
            )
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
