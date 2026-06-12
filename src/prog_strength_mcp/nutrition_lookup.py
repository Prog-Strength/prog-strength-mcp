"""Nutrition lookup domain: MCP tool for grounding custom-meal macros
in real data.

Transparent forwarder over the API's GET /nutrition/lookup — the Go
API owns the external-provider integration (FatSecret, USDA FDC) and
the durable cache; this module is plumbing, exactly like every sibling
domain. See prog-strength-docs/sows/custom-meal-macro-accuracy.md.
"""

from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import Field

from prog_strength_mcp.api_client import APIClient, APIError


def _auth_header_or_raise() -> str:
    """Pull the inbound Authorization header. The lookup endpoint is
    auth-gated (it spends shared provider quota), so the tool forwards
    the user's Bearer token like every other domain tool.
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
    """Register the lookup tool on `mcp`, backed by `api`."""

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
                    "server-side; use it as-is, never multiply macros "
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
        serving_description, and a `source` to cite. The response's
        `request_id` is operational tracing metadata — never read it
        aloud to the user. Prefer an exact
        brand/chain match without a plausibility_warning; a match with
        "stale": true came from an expired cache because the data sources
        were unreachable — usable, but say the numbers may be dated.
        Returns {"error": ...} when no provider is configured or all
        providers failed — in that case, estimate yourself and tell the
        user it's an estimate.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.lookup_food_nutrition(
                auth,
                query=query,
                quantity=quantity,
                max_results=max_results,
            )
        except APIError as e:
            # The API answers 503 with "lookup_unavailable: …" or
            # "lookup_failed: …" when providers are unconfigured or all
            # down. Adapt that into the structured dict the agent prompt
            # is written against, instead of surfacing a tool error —
            # degraded lookup is an expected state, not a failure.
            if e.status_code == 503:
                kind, _, detail = e.message.partition(":")
                out = {"error": kind.strip(), "detail": detail.strip()}
                if e.request_id:
                    out["request_id"] = e.request_id
                return out
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
