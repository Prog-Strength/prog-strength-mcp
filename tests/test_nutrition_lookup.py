"""Tests for the nutrition lookup forwarder.

The provider integration (FatSecret, USDA) and the durable cache live
in prog-strength-api — this layer is a transparent forwarder, so the
contract pinned here is plumbing only:

* APIClient.lookup_food_nutrition builds the exact query params and
  Authorization header for GET /nutrition/lookup and unwraps `data`.
* The tool adapts the API's 503 lookup_unavailable / lookup_failed
  responses into the structured {"error", "detail"} dict the agent
  prompt is written against, re-raises other API errors, and refuses
  to run without an Authorization header.
"""

import httpx
import pytest
import respx
from fastmcp import FastMCP

from prog_strength_mcp import nutrition_lookup
from prog_strength_mcp.api_client import APIClient, APIError

BASE_URL = "http://api.test"
AUTH = "Bearer test-token"

MATCHES_PAYLOAD = {
    "matches": [
        {
            "name": "Chick-n-Mini",
            "brand": "Chick-fil-A",
            "serving_description": "1 mini",
            "per_serving": {"calories": 90, "protein_g": 4.75, "fat_g": 3.25, "carbs_g": 10.25},
            "total_for_quantity": {
                "calories": 900,
                "protein_g": 47.5,
                "fat_g": 32.5,
                "carbs_g": 102.5,
            },
            "source": "fatsecret",
            "source_id": "12345",
        }
    ],
    "quantity": 10,
}


# --- API client --------------------------------------------------------


@respx.mock
async def test_lookup_forwards_params_and_auth():
    route = respx.get(f"{BASE_URL}/nutrition/lookup").mock(
        return_value=httpx.Response(
            200,
            json={"data": MATCHES_PAYLOAD},
            headers={"X-Request-ID": "req-lookup-1"},
        )
    )
    async with APIClient(base_url=BASE_URL) as api:
        result = await api.lookup_food_nutrition(
            AUTH, query="chick fil a chicken minis", quantity=10, max_results=3
        )

    req = route.calls.last.request
    assert req.headers["Authorization"] == AUTH
    params = dict(httpx.URL(str(req.url)).params)
    assert params == {
        "query": "chick fil a chicken minis",
        "quantity": "10",
        "max_results": "3",
    }
    # The API's correlation id rides along for CloudWatch tracing.
    assert result == {**MATCHES_PAYLOAD, "request_id": "req-lookup-1"}


@respx.mock
async def test_lookup_defaults_quantity_and_max_results():
    route = respx.get(f"{BASE_URL}/nutrition/lookup").mock(
        return_value=httpx.Response(200, json={"data": {"matches": [], "quantity": 1}})
    )
    async with APIClient(base_url=BASE_URL) as api:
        await api.lookup_food_nutrition(AUTH, query="eggs")

    params = dict(httpx.URL(str(route.calls.last.request.url)).params)
    assert params["quantity"] == "1"
    assert params["max_results"] == "5"


@respx.mock
async def test_lookup_raises_apierror_with_envelope_detail_and_request_id():
    respx.get(f"{BASE_URL}/nutrition/lookup").mock(
        return_value=httpx.Response(
            503,
            json={
                "service": "api",
                "error": "lookup_unavailable: no nutrition data providers configured",
            },
            headers={"X-Request-ID": "req-failed-1"},
        )
    )
    async with APIClient(base_url=BASE_URL) as api:
        with pytest.raises(APIError) as exc:
            await api.lookup_food_nutrition(AUTH, query="eggs")
    assert exc.value.status_code == 503
    assert exc.value.message.startswith("lookup_unavailable")
    # Failures are traceable too.
    assert exc.value.request_id == "req-failed-1"


# --- tool boundary -----------------------------------------------------


class _FakeAPI:
    """Stands in for APIClient at the tool boundary: records the call
    and returns/raises a programmed response."""

    def __init__(self, result=None, error: APIError | None = None):
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    async def lookup_food_nutrition(self, auth_header, *, query, quantity, max_results):
        self.calls.append(
            {
                "auth": auth_header,
                "query": query,
                "quantity": quantity,
                "max_results": max_results,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


async def _tool_fn(monkeypatch, api: _FakeAPI, *, auth: str = AUTH):
    """Register the lookup tool on a fresh FastMCP and return the raw
    callable. Patch `get_http_headers` to supply (or omit) the auth
    header — same pattern as the nutrition-tool tests."""
    monkeypatch.setattr(
        nutrition_lookup,
        "get_http_headers",
        lambda **_: {"authorization": auth} if auth else {},
    )
    mcp = FastMCP("test")
    nutrition_lookup.register(mcp, api)
    tool = await mcp.get_tool("lookup_food_nutrition")
    return tool.fn


async def test_tool_forwards_and_returns_matches(monkeypatch):
    api = _FakeAPI(result=MATCHES_PAYLOAD)
    fn = await _tool_fn(monkeypatch, api)

    result = await fn(query="chick fil a chicken minis", quantity=10, max_results=3)

    assert result == MATCHES_PAYLOAD
    assert api.calls == [
        {
            "auth": AUTH,
            "query": "chick fil a chicken minis",
            "quantity": 10,
            "max_results": 3,
        }
    ]


async def test_tool_requires_auth_header(monkeypatch):
    api = _FakeAPI(result=MATCHES_PAYLOAD)
    fn = await _tool_fn(monkeypatch, api, auth="")

    with pytest.raises(RuntimeError, match="Authorization"):
        await fn(query="eggs")
    assert api.calls == []  # no HTTP forwarding without auth


@pytest.mark.parametrize(
    ("message", "kind", "detail"),
    [
        (
            "lookup_unavailable: no nutrition data providers configured",
            "lookup_unavailable",
            "no nutrition data providers configured",
        ),
        (
            "lookup_failed: fatsecret: status 500; usda: status 500",
            "lookup_failed",
            "fatsecret: status 500; usda: status 500",
        ),
    ],
)
async def test_tool_adapts_503_into_structured_error(monkeypatch, message, kind, detail):
    api = _FakeAPI(error=APIError(503, message, request_id="req-err-7"))
    fn = await _tool_fn(monkeypatch, api)

    result = await fn(query="eggs")

    assert result == {"error": kind, "detail": detail, "request_id": "req-err-7"}


async def test_tool_omits_request_id_when_absent_on_error(monkeypatch):
    api = _FakeAPI(error=APIError(503, "lookup_failed: boom"))
    fn = await _tool_fn(monkeypatch, api)

    result = await fn(query="eggs")

    assert result == {"error": "lookup_failed", "detail": "boom"}


async def test_tool_reraises_non_503_api_errors(monkeypatch):
    api = _FakeAPI(error=APIError(500, "boom"))
    fn = await _tool_fn(monkeypatch, api)

    with pytest.raises(RuntimeError, match=r"API error \(500\)"):
        await fn(query="eggs")
