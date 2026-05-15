"""REPL agent: chat with Claude wired to the local prog-strength-mcp server.

Each user line is sent to Claude (claude-opus-4-7) with the MCP server's tools
exposed. Claude can call list_workouts; the MCP server proxies the call to the
Prog Strength API; the model uses the result in its reply. Tool calls and
results are printed inline so the loop is visible.

Not using `mcp_servers` on messages.create: the Anthropic-side "MCP connector"
requires a public https:// URL reachable from Anthropic's servers (see
docs.claude.com/.../mcp-connector). For a local server we connect with the
MCP Python SDK and run a vanilla tool-use loop instead.

Prereqs:
    ANTHROPIC_API_KEY     required.
    ACTIVE_PROFILE        set below; or PROG_STRENGTH_MCP_URL to override ad-hoc.
"""

import asyncio
import json
import os
import sys

from anthropic import AsyncAnthropic
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MODEL = "claude-opus-4-7"
MAX_TOKENS = 2048
SNIPPET = 240  # chars of tool result printed inline; full text still goes to Claude

# Edit ACTIVE_PROFILE to flip between environments. PROG_STRENGTH_MCP_URL
# overrides the chosen profile's URL ad-hoc without editing the file.
PROFILES = {
    "local": "http://localhost:8000/mcp",
    "production": "https://mcp.progstrength.fitness/mcp",
}
ACTIVE_PROFILE = "local"


def _result_text(result) -> str:
    return "\n".join(
        getattr(c, "text", json.dumps(c.model_dump(mode="json"))) for c in result.content
    )


async def _chat(session, claude, tools):
    messages: list[dict] = []
    while True:
        try:
            user = (await asyncio.to_thread(input, "you> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if user in {"/quit", "/exit"}:
            return
        if not user:
            continue
        messages.append({"role": "user", "content": user})

        while True:  # tool-use loop: keep going until Claude stops asking for tools
            resp = await claude.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS, tools=tools, messages=messages
            )
            messages.append({"role": "assistant", "content": resp.content})
            for block in resp.content:
                if block.type == "text":
                    print(f"claude> {block.text}")
                elif block.type == "tool_use":
                    print(f"[tool_use {block.name}({json.dumps(block.input)})]")

            if resp.stop_reason != "tool_use":
                break

            tool_results = []
            for tu in (b for b in resp.content if b.type == "tool_use"):
                result = await session.call_tool(tu.name, tu.input or {})
                text = _result_text(result)
                preview = text if len(text) <= SNIPPET else text[:SNIPPET] + "..."
                print(f"[tool_result {tu.name} ({'error' if result.isError else 'ok'}): {preview}]")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": text,
                    "is_error": result.isError,
                })
            messages.append({"role": "user", "content": tool_results})


async def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is required")

    mcp_url = os.environ.get("PROG_STRENGTH_MCP_URL", PROFILES[ACTIVE_PROFILE])
    claude = AsyncAnthropic()
    print(f"profile: {ACTIVE_PROFILE} -> {mcp_url}")
    async with streamablehttp_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = (await session.list_tools()).tools
            tools = [
                {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
                for t in mcp_tools
            ]
            print(f"exposed tools: {', '.join(t['name'] for t in tools) or '(none)'}")
            print("type /quit to exit\n")
            await _chat(session, claude, tools)


if __name__ == "__main__":
    asyncio.run(main())
