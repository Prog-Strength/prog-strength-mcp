from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from prog_strength_mcp import (
    bodyweight,
    exercises,
    macro_goals,
    nutrition,
    pantry,
    recipes,
    workouts,
)
from prog_strength_mcp.api_client import APIClient
from prog_strength_mcp.config import Config
from prog_strength_mcp.version import SERVICE, VERSION

mcp: FastMCP = FastMCP("prog-strength-mcp")

# Single shared client. FastMCP's transport server is long-lived, so the
# underlying httpx.AsyncClient (with its connection pool) gets reused across
# tool calls — which is what we want.
_config = Config.from_env()
# No signing key — this server is now a transparent forwarder. Each tool
# handler reads the inbound Authorization header from request context
# and passes it through to the API. The API does the JWT validation.
api = APIClient(base_url=_config.api_base_url)

# Each domain module owns its tools and registers them onto our FastMCP
# instance — Python parallel of the API handlers' Mount(r) pattern.
workouts.register(mcp, api)
exercises.register(mcp, api)
pantry.register(mcp, api)
recipes.register(mcp, api)
nutrition.register(mcp, api)
bodyweight.register(mcp, api)
macro_goals.register(mcp, api)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    """Liveness probe with build info. Mirrors the API's /health envelope
    so the same `curl <host>/health | jq` muscle memory works for both.
    """
    return JSONResponse(
        {
            "service": SERVICE,
            "version": VERSION,
            "message": "service is healthy",
        }
    )


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
