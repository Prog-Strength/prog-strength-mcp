# prog-strength-mcp

A Model Context Protocol (MCP) server that exposes Prog Strength data to LLMs.

Built with [FastMCP](https://github.com/jlowin/fastmcp) and served over
streamable HTTP. Every tool call proxies to the Go Chi API in
[`prog-strength-api`](https://github.com/Prog-Strength/prog-strength-api) —
this server never reads or writes the SQLite database directly.

## Architecture

```
Claude / MCP client ──HTTP──▶ prog-strength-mcp (FastMCP) ──HTTP──▶ prog-strength-api (Go Chi) ──▶ SQLite
```

**Auth model.** This server is a transparent forwarder. The MCP client
(the agent) opens each session with the end-user's JWT in the HTTP
`Authorization` header; FastMCP exposes that header to tool handlers
via `get_http_headers`, and the handlers pass it verbatim through to
the API. **MCP holds no signing key and cannot mint tokens.** The
ability to impersonate users was deliberately removed when the
production frontend went live.

Calls that arrive without an `Authorization` header are rejected by
the tool handler before they hit the API. Public endpoints (currently
just `list_exercises`) don't require auth.

## Tools

| Name             | Description                                            |
| ---------------- | ------------------------------------------------------ |
| `list_exercises` | Public catalog browse. Optional `muscle_group` and `equipment` filters. |
| `list_workouts`  | The calling user's logged workouts (capped at 50, most recent first). Identity from `Authorization` header. |
| `create_workout` | Log a new workout for the calling user. Identity from `Authorization` header. |

## Local development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
# install deps (creates .venv and uv.lock)
uv sync

# the server has no secrets to configure; defaults work for local dev.
# copy the env template only if you want to override PROG_STRENGTH_API_BASE_URL
# or the bind host/port.
cp .env.example .env

# run the server (loads .env automatically if you run via `uv run`)
uv run prog-strength-mcp
```

The server listens on `http://localhost:8000/mcp` by default. Point an MCP
client at that URL.

To run against a local API instead of prod:

```sh
# in one terminal — the Go API on :8080
cd ../prog-strength-api && go run cmd/api/main.go

# in another — the MCP server proxying to it
PROG_STRENGTH_API_BASE_URL=http://localhost:8080 uv run prog-strength-mcp
```

## Configuration

All config is via environment variables — see `.env.example` for the full list.

| Variable                     | Default                  | Purpose                                                |
| ---------------------------- | ------------------------ | ------------------------------------------------------ |
| `PROG_STRENGTH_API_BASE_URL` | `http://localhost:8080`  | Where to proxy tool calls.                             |
| `MCP_HOST`                   | `0.0.0.0`                | Bind address for the streamable-HTTP transport.        |
| `MCP_PORT`                   | `8000`                   | Bind port.                                             |

No secrets are required — the server holds none.

## Deployment

Shares the EC2 host with `prog-strength-api`. Each service has its own
docker-compose file; they join a shared external docker network called
`prog-strength` so Caddy (in the api stack) can reverse-proxy to
`mcp:8000` and this server can reach the api at `http://api:8080`.

Caddy serves `https://mcp.progstrength.fitness` and terminates TLS — the
mcp container has no public ports.

**Pipeline:** semantic-release in `.github/workflows/release.yml` tags
on `feat:`/`fix:` commits to `main`, then deploys via SSM Run Command —
no SSH, no inbound port 22. The deploy step assumes the shared OIDC role
and `aws ssm send-command` invokes
`/home/ubuntu/prog-strength-infra/deploy/mcp.sh`, which pulls the infra
checkout (the compose file lives there), writes a minimal `.env`, and
runs `docker compose pull/down/up`. No app secrets to wire in — auth
comes from the agent's per-request `Authorization` header.

**Required GitHub secrets** on this repo: none for deploys. Deploys run
via SSM Run Command using the shared OIDC role (`AWS_GHA_ROLE_ARN`, an
org/shared secret) — no host-identity or SSH secret (`EC2_HOST` /
`EC2_SSH_KEY`) is needed.

**Host prerequisites** (handled by the infra repo's bootstrap on fresh
hosts; do this once on the existing host):

```sh
docker network create prog-strength
```

The mcp repo is **not** checked out on the host — its compose file lives
in `prog-strength-infra` (`compose/mcp`), which the deploy script pulls.

## Layout

```
src/prog_strength_mcp/
├── __init__.py
├── __main__.py    # `python -m prog_strength_mcp` and console script entry
├── server.py      # FastMCP instance + register() calls + run()
├── workouts.py    # list_workouts + create_workout tools
├── exercises.py   # list_exercises tool (public)
├── api_client.py  # httpx async wrapper, header-passthrough only
└── config.py      # env var loading (no secrets)
```
