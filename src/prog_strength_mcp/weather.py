"""Weather domain: one MCP tool exposing the shipped GET /weather forecast
to the agent.

Transparent forwarder in the mold of nutrition_lookup — the Go API owns the
OpenWeather provider, the durable daily call budget, and the coordinate-keyed
cache; this module is plumbing. It deliberately holds no opinion about what
weather makes a good training session: this server is shared by every client,
and training judgment lives in the agent's prompt.

See prog-strength-docs/sows/weather-agent-tool.md.
"""

from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import Field

from prog_strength_mcp.api_client import APIClient, APIError


def _auth_header_or_raise() -> str:
    """Pull the inbound Authorization header. The endpoint is auth-gated
    (it reads the user's saved locations and spends shared provider
    quota), so the tool forwards the user's Bearer token like every
    other domain tool.
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
    """Register the forecast tool on `mcp`, backed by `api`."""

    @mcp.tool
    async def get_weather_forecast(
        timezone: Annotated[
            str,
            Field(
                min_length=1,
                max_length=64,
                description=(
                    "IANA timezone name, e.g. 'America/Denver'. Required — never guess one."
                ),
            ),
        ],
        place: Annotated[
            str | None,
            Field(
                default=None,
                max_length=200,
                description=(
                    "Optional free-text place the user named — 'Boulder', "
                    "'Moab, UT'. Omit it for the user's own location, which "
                    "is what they mean unless they say otherwise."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Get the weather forecast for the user's saved location, or for a
        place they name.

        `current` holds conditions now and `today` the high/low and sun
        times; `hourly` covers roughly the next 20 hours and `daily` about 8
        days. There is no hour-level data past the end of `hourly`.

        Field semantics: `units` states which temperature and wind units every
        number in the payload is already in — nothing here needs converting.
        `precip_chance` is a percentage, not a probability. `sunrise` and
        `sunset` are RFC3339 UTC instants. `request_id` is operational tracing
        metadata — never read it aloud.

        `status` is always present. `"ok"` means fresh. `"stale"` means the
        numbers came from an expired cache and may be dated — say so.
        `"disabled"`, `"budget_exhausted"` and `"unavailable"` all mean no
        usable forecast right now — the forecast fields are absent or thin.

        Returns `{"error": "no_saved_locations"}` when the user has saved no
        location and named no place — they can add one on their dashboard, or
        just say which city they are in. Returns
        `{"error": "place_not_found", "place": …}` when the named place cannot
        be resolved.
        """
        auth = _auth_header_or_raise()
        try:
            return await api.get_weather_forecast(auth, timezone=timezone, place=place)
        except APIError as e:
            # Both 404s are ordinary states, not faults. A user who has saved
            # no location is in a perfectly normal place, and a name the
            # geocoder does not know is something to say back — the model can
            # only do either if it receives a fact instead of a tool error.
            # This mirrors how nutrition_lookup adapts the API's 503.
            if e.status_code == 404 and e.code in ("no_locations", "place_not_found"):
                # `place` is the tool's own argument — the API's 404 body
                # carries no place to echo back.
                out: dict[str, Any] = (
                    {"error": "no_saved_locations"}
                    if e.code == "no_locations"
                    else {"error": "place_not_found", "place": place}
                )
                if e.request_id:
                    out["request_id"] = e.request_id
                return out
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
