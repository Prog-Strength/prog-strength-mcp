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

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pydantic
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


# --- API client: log_consumption_batch --------------------------------


@respx.mock
async def test_log_consumption_batch_forwards_body_and_auth():
    """A heterogeneous items list is forwarded verbatim under {"items": [...]}
    with each item's kind and fields intact and the Authorization header set;
    the returned dict is the API's `data` payload.
    """
    route = respx.post(f"{BASE_URL}/nutrition-log/batch").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"results": [], "logged": 0, "failed": 0}},
        )
    )
    items = [
        {"kind": "pantry", "pantry_item_id": "p-1", "quantity": 5, "meal": "breakfast"},
        {
            "kind": "custom",
            "name": "Chipotle chicken bowl",
            "calories": 850,
            "protein_g": 55,
            "fat_g": 30,
            "carbs_g": 75,
            "meal": "dinner",
        },
    ]
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.log_consumption_batch(AUTH, items=items)

    assert result == {"results": [], "logged": 0, "failed": 0}
    request = route.calls.last.request
    assert request.headers["Authorization"] == AUTH
    body = json.loads(request.content)
    assert body == {"items": items}


# --- Tool boundary: log_consumption_batch -----------------------------


async def _batch_tool(api):
    from fastmcp import FastMCP

    mcp = FastMCP("test")
    nutrition.register(mcp, api)
    return await mcp.get_tool("log_consumption_batch")


@respx.mock
async def test_batch_tool_forwards_heterogeneous_list(monkeypatch):
    """The registered tool forwards a mixed pantry + custom list: kinds are
    preserved and `consumed_at` is omitted from each item when it is None.
    """
    monkeypatch.setattr(
        nutrition,
        "get_http_headers",
        lambda **_: {"authorization": AUTH},
    )
    route = respx.post(f"{BASE_URL}/nutrition-log/batch").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"results": [], "logged": 2, "failed": 0}},
        )
    )
    async with APIClient(base_url=BASE_URL) as api:
        tool = await _batch_tool(api)
        await tool.run(
            {
                "items": [
                    {
                        "kind": "pantry",
                        "pantry_item_id": "p-1",
                        "quantity": 5,
                        "meal": "breakfast",
                    },
                    {
                        "kind": "custom",
                        "name": "Chipotle chicken bowl",
                        "calories": 850,
                        "protein_g": 55,
                        "fat_g": 30,
                        "carbs_g": 75,
                        "meal": "dinner",
                    },
                ]
            }
        )

    body = json.loads(route.calls.last.request.content)
    assert body == {
        "items": [
            {
                "kind": "pantry",
                "pantry_item_id": "p-1",
                "quantity": 5,
                "meal": "breakfast",
            },
            {
                "kind": "custom",
                "name": "Chipotle chicken bowl",
                "calories": 850,
                "protein_g": 55,
                "fat_g": 30,
                "carbs_g": 75,
                "meal": "dinner",
            },
        ]
    }
    # consumed_at was None on both items, so it never appears in the body.
    for item in body["items"]:
        assert "consumed_at" not in item


@respx.mock
async def test_batch_tool_surfaces_per_item_failure(monkeypatch):
    """A best-effort 200 with a failed item is returned verbatim so the
    agent can read `failed`/`results` and tell the user what didn't log.
    """
    monkeypatch.setattr(
        nutrition,
        "get_http_headers",
        lambda **_: {"authorization": AUTH},
    )
    payload = {
        "results": [{"index": 0, "ok": False, "error": "pantry item not found"}],
        "logged": 0,
        "failed": 1,
    }
    respx.post(f"{BASE_URL}/nutrition-log/batch").mock(
        return_value=httpx.Response(200, json={"data": payload})
    )
    async with APIClient(base_url=BASE_URL) as api:
        tool = await _batch_tool(api)
        result = await tool.run(
            {
                "items": [
                    {
                        "kind": "pantry",
                        "pantry_item_id": "missing",
                        "quantity": 1,
                        "meal": "lunch",
                    }
                ]
            }
        )

    assert result.structured_content == payload


# --- Tool boundary: discriminated-union validation --------------------
#
# Per-kind required fields are enforced by FastMCP's validated invocation
# path — `tool.run(args)` builds a pydantic model from the annotations and
# raises `pydantic.ValidationError` before the tool body (and any HTTP).


async def test_batch_tool_rejects_pantry_item_missing_id():
    class _ExplodingAPI:
        async def log_consumption_batch(self, *a, **k):  # pragma: no cover
            raise AssertionError("validation must reject before HTTP forwarding")

    tool = await _batch_tool(_ExplodingAPI())
    with pytest.raises(pydantic.ValidationError, match="pantry_item_id"):
        await tool.run({"items": [{"kind": "pantry", "quantity": 1, "meal": "lunch"}]})


async def test_batch_tool_rejects_custom_item_missing_calories():
    class _ExplodingAPI:
        async def log_consumption_batch(self, *a, **k):  # pragma: no cover
            raise AssertionError("validation must reject before HTTP forwarding")

    tool = await _batch_tool(_ExplodingAPI())
    with pytest.raises(pydantic.ValidationError, match="calories"):
        await tool.run(
            {
                "items": [
                    {
                        "kind": "custom",
                        "name": "mystery snack",
                        "protein_g": 10,
                        "fat_g": 5,
                        "carbs_g": 20,
                        "meal": "snack",
                    }
                ]
            }
        )


async def test_batch_tool_requires_auth(monkeypatch):
    """The auth guard fires (RuntimeError) before any HTTP forwarding when
    the inbound request carries no Authorization header. _ExplodingAPI's
    log_consumption_batch would raise AssertionError if HTTP were attempted.
    """
    monkeypatch.setattr(nutrition, "get_http_headers", lambda **_: {})

    class _ExplodingAPI:
        async def log_consumption_batch(self, *a, **k):  # pragma: no cover
            raise AssertionError("HTTP forwarding must not happen on missing auth")

    tool = await _batch_tool(_ExplodingAPI())
    with pytest.raises(RuntimeError, match="Authorization"):
        await tool.fn(
            items=[
                nutrition.PantryItem(kind="pantry", pantry_item_id="p-1", quantity=1, meal="lunch")
            ]
        )


# --- Registration: old tools removed, batch tool present --------------


async def test_single_item_tools_removed_and_batch_present():
    from fastmcp import FastMCP

    class _StubAPI:
        pass

    mcp = FastMCP("test")
    nutrition.register(mcp, _StubAPI())

    assert await mcp.get_tool("log_consumption_batch") is not None
    for gone in ("log_consumption", "log_custom_meal"):
        assert await mcp.get_tool(gone) is None
