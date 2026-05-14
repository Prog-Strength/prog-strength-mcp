from typing import Any

from fastmcp import FastMCP

from prog_strength_mcp.api_client import APIClient, APIError
from prog_strength_mcp.config import Config

mcp: FastMCP = FastMCP("prog-strength-mcp")

# Single shared client. FastMCP's transport server is long-lived, so the
# underlying httpx.AsyncClient (with its connection pool) gets reused across
# tool calls — which is what we want.
_config = Config.from_env()
_api = APIClient(base_url=_config.api_base_url, signing_key=_config.jwt_signing_key)


@mcp.tool
async def list_workouts(user_id: str) -> list[dict[str, Any]]:
    """List a user's logged workouts, most recent first.

    The API caps results at 50 today; pagination is not yet exposed. Each
    workout includes its exercises and sets (reps, weight, unit), so a
    single call is enough to summarize recent training.

    Args:
        user_id: The user whose workouts to fetch. The MCP server mints a
            short-lived JWT for this user and forwards it to the API.
    """
    if not user_id:
        raise ValueError("user_id is required")

    try:
        return await _api.list_workouts(user_id)
    except APIError as e:
        # Re-raise as a plain RuntimeError so FastMCP serializes a clean
        # tool error to the model (instead of leaking the internal class).
        raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e


def run() -> None:
    """Start the streamable-HTTP transport on the configured host/port.

    `proxy_headers` + `forwarded_allow_ips` tell uvicorn to honor Caddy's
    `X-Forwarded-Proto: https` / `X-Forwarded-Host` headers when building
    absolute URLs — without these, redirect `Location` headers come back
    as `http://...` because uvicorn only sees the plain-HTTP hop from
    Caddy on the docker network.
    """
    mcp.run(
        transport="http",
        host=_config.host,
        port=_config.port,
        uvicorn_config={
            "proxy_headers": True,
            "forwarded_allow_ips": "*",
        },
    )
