import os

# Released semver (e.g. "v0.1.0"), injected at deploy time via APP_VERSION
# in .env (see .github/workflows/release.yml). Falls back to "dev" for
# local `docker compose up` and uvicorn runs outside the release pipeline.
VERSION: str = os.environ.get("APP_VERSION", "dev")

SERVICE: str = "Prog Strength MCP"
