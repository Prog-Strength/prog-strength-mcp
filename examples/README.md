# examples

Runnable examples for `prog-strength-mcp`. These are developer tools, not
part of the server install and not exercised by CI.

## Running the example

1. Install the `examples` optional dependency group (one-time):

   ```sh
   uv sync --group examples
   ```

   This adds the Anthropic SDK and the MCP Python client *only* to the dev
   venv. It does not touch the server's runtime dependencies or the Docker
   image. See `pyproject.toml`'s `[dependency-groups]`.

2. In one shell, start the MCP server (and the API it depends on). For
   local Docker:

   ```sh
   JWT_SIGNING_KEY=$(openssl rand -hex 32) docker compose up --build
   ```

   The MCP server's streamable-HTTP endpoint defaults to
   `http://localhost:8000/mcp`.

3. In another shell, set your Anthropic API key and run the script:

   ```sh
   export ANTHROPIC_API_KEY=sk-ant-...
   uv run --group examples python examples/chat_with_agent.py
   ```

   To point at the deployed environment, edit `ACTIVE_PROFILE` at the top of
   `chat_with_agent.py` (`"local"` or `"production"`). For one-off overrides,
   set `PROG_STRENGTH_MCP_URL` in env — it wins over the profile.

   Type a question that should hit the tool, e.g. `show me my last workout
   for user-123`. Tool calls and tool results are printed inline so you can
   watch the model decide to call `list_workouts`, see the proxied response,
   and use it in its reply. `/quit` or Ctrl-D to exit.

## What it demonstrates

End-to-end that the MCP layer actually works: an LLM connects to the
prog-strength MCP server, sees its tools, calls them with real arguments,
gets real data back from the API, and grounds its response in that data.
The script uses the MCP Python SDK directly (not Anthropic's inline
`mcp_servers` connector — that requires a publicly-reachable https URL,
which a local dev server isn't). That's the canonical pattern for any
client wanting to drive Claude against a local or private MCP server.
