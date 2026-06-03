"""Tests for the nutrition date contract on the MCP layer.

Two boundaries are exercised:

* The API client (`APIClient.list_nutrition_log` / `get_daily_macros`):
  HTTP is mocked with respx and we assert the exact query params built —
  `timezone` always present, `date` / `start_date` / `end_date` forwarded
  when supplied, and crucially NO legacy `since` / `until`.
* The MCP tool boundary: the registered tool functions raise a
  `RuntimeError` mentioning timezone when `timezone` is empty, before any
  HTTP call. `get_http_headers` is monkeypatched so the auth check passes.
"""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from prog_strength_mcp import nutrition
from prog_strength_mcp.api_client import APIClient

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"


def _query(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(urlsplit(str(request.url)).query)


# --- API client: list_nutrition_log -----------------------------------


@respx.mock
async def test_list_nutrition_log_single_date_params():
    route = respx.get(f"{BASE_URL}/nutrition-log").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.list_nutrition_log(AUTH, timezone="America/Denver", date="2026-06-03")

    q = _query(route.calls.last.request)
    assert q == {"timezone": ["America/Denver"], "date": ["2026-06-03"]}
    assert "since" not in q
    assert "until" not in q


@respx.mock
async def test_list_nutrition_log_range_params():
    route = respx.get(f"{BASE_URL}/nutrition-log").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.list_nutrition_log(
            AUTH,
            timezone="America/Denver",
            start_date="2026-06-01",
            end_date="2026-06-07",
        )

    q = _query(route.calls.last.request)
    assert q == {
        "timezone": ["America/Denver"],
        "start_date": ["2026-06-01"],
        "end_date": ["2026-06-07"],
    }


# --- API client: get_daily_macros --------------------------------------


@respx.mock
async def test_get_daily_macros_single_date_params():
    route = respx.get(f"{BASE_URL}/nutrition-log/daily").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.get_daily_macros(AUTH, timezone="Europe/London", date="2026-06-03")

    q = _query(route.calls.last.request)
    assert q == {"timezone": ["Europe/London"], "date": ["2026-06-03"]}
    assert "since" not in q
    assert "until" not in q


@respx.mock
async def test_get_daily_macros_range_params():
    route = respx.get(f"{BASE_URL}/nutrition-log/daily").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.get_daily_macros(
            AUTH,
            timezone="Europe/London",
            start_date="2026-06-01",
            end_date="2026-06-07",
        )

    q = _query(route.calls.last.request)
    assert q == {
        "timezone": ["Europe/London"],
        "start_date": ["2026-06-01"],
        "end_date": ["2026-06-07"],
    }


# --- API client: one-of validation is the API's job, not the client's --


@respx.mock
async def test_client_forwards_mixed_date_and_range_without_raising():
    """The client must NOT validate the one-of constraint locally — it
    forwards both `date` and `start_date` and lets the API reject. We
    assert no client-layer exception and that both params are present.
    """
    route = respx.get(f"{BASE_URL}/nutrition-log").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.list_nutrition_log(
            AUTH,
            timezone="America/Denver",
            date="2026-06-03",
            start_date="2026-06-01",
        )

    q = _query(route.calls.last.request)
    assert q["date"] == ["2026-06-03"]
    assert q["start_date"] == ["2026-06-01"]
    assert q["timezone"] == ["America/Denver"]


# --- Tool boundary: timezone is required before any HTTP call ----------


async def _tool_fn(monkeypatch, name: str):
    """Register the nutrition tools on a fresh FastMCP and return the raw
    callable for `name`. Patch `get_http_headers` so the auth check passes,
    letting us reach the timezone guard. The API client is a sentinel that
    explodes if any HTTP forwarding is attempted.
    """
    from fastmcp import FastMCP

    monkeypatch.setattr(
        nutrition,
        "get_http_headers",
        lambda **_: {"authorization": AUTH},
    )

    class _ExplodingAPI:
        async def list_nutrition_log(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing timezone")

        async def get_daily_macros(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing timezone")

    mcp = FastMCP("test")
    nutrition.register(mcp, _ExplodingAPI())

    # FunctionTool stores the raw coroutine fn on `.fn`.
    tool = await mcp.get_tool(name)
    return tool.fn


async def test_list_nutrition_log_tool_requires_timezone(monkeypatch):
    fn = await _tool_fn(monkeypatch, "list_nutrition_log")
    with pytest.raises(RuntimeError, match="timezone"):
        await fn(timezone="")


async def test_get_daily_macros_tool_requires_timezone(monkeypatch):
    fn = await _tool_fn(monkeypatch, "get_daily_macros")
    with pytest.raises(RuntimeError, match="timezone"):
        await fn(timezone="")
