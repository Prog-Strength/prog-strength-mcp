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

The MCP server holds the API's `JWT_SIGNING_KEY` and mints a short-lived
(5 min) per-call JWT for whichever `user_id` the tool is invoked with.
This makes it a privileged service — anything that can reach it can read
any user's data. Front-door auth on this server is a v2 concern; for now,
keep its port closed to the public internet.

## Tools

| Name             | Description                                            |
| ---------------- | ------------------------------------------------------ |
| `list_workouts`  | Returns a user's logged workouts (capped at 50, most recent first). Includes nested exercises + sets. |

## Local development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
# install deps (creates .venv and uv.lock)
uv sync

# copy env template and fill in JWT_SIGNING_KEY (must match the API's value)
cp .env.example .env
$EDITOR .env

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
| `JWT_SIGNING_KEY`            | *required*               | HS256 secret. Must match the API.                      |
| `MCP_HOST`                   | `0.0.0.0`                | Bind address for the streamable-HTTP transport.        |
| `MCP_PORT`                   | `8000`                   | Bind port.                                             |

## Deployment

Shares the EC2 host with `prog-strength-api`. Each service has its own
docker-compose file; they join a shared external docker network called
`prog-strength` so Caddy (in the api stack) can reverse-proxy to
`mcp:8000` and this server can reach the api at `http://api:8080`.

Caddy serves `https://mcp.progstrength.fitness` and terminates TLS — the
mcp container has no public ports.

**Pipeline:** `.github/workflows/deploy.yml` triggers on every push to
`main`. It SSHes into the EC2 host, `git pull`s `/home/ubuntu/prog-strength-mcp`,
writes a fresh `.env` (only `JWT_SIGNING_KEY` — everything else is in
`docker-compose.yml`), and runs `docker compose up --build -d`. No
semantic-release for v1.

**Required GitHub secrets** on this repo:

| Secret            | Value                                        |
| ----------------- | -------------------------------------------- |
| `EC2_HOST`        | Same Elastic IP as the api repo.             |
| `EC2_SSH_KEY`     | Same private key as the api repo.            |
| `JWT_SIGNING_KEY` | Same HS256 secret the api uses.              |

**Host prerequisites** (handled by the infra repo's bootstrap on fresh
hosts; do these once on the existing host):

```sh
docker network create prog-strength
git clone https://github.com/Prog-Strength/prog-strength-mcp.git \
  /home/ubuntu/prog-strength-mcp
```

## Layout

```
src/prog_strength_mcp/
├── __init__.py
├── __main__.py    # `python -m prog_strength_mcp` and console script entry
├── server.py      # FastMCP instance + tool registrations + run()
├── api_client.py  # httpx async wrapper, JWT minting
└── config.py      # env var loading
```
