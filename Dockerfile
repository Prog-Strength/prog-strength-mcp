# Python 3.12 slim base + uv from the official upstream image. uv handles
# the venv and lockfile; we never call pip directly. Builds in two stages
# of `uv sync` so the dependency layer caches independently of source.

FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Run as a non-root user. The MCP server doesn't need root, and the
# attack surface of this container is "anything that can reach :8000",
# so dropping privileges is worth the few extra lines.
RUN useradd --create-home --shell /bin/bash app
WORKDIR /app
RUN chown app:app /app
USER app

# Layer 1: dependencies only. `--no-install-project` skips installing our
# own package so this layer invalidates only when pyproject.toml or
# uv.lock change. README.md is included because pyproject.toml declares
# `readme = "README.md"`, and hatchling validates that field at the
# second `uv sync` step below — without README.md in the image, the
# build fails before our source is even installed.
COPY --chown=app:app pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2: project source.
COPY --chown=app:app src/ ./src/
RUN uv sync --frozen --no-dev

EXPOSE 8000

# `uv run` activates the project venv and execs the console script
# declared in pyproject.toml. PEP 668 doesn't apply because uv manages
# the venv outside the system Python.
CMD ["uv", "run", "--no-dev", "prog-strength-mcp"]
