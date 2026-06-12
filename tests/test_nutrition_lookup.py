"""Tests for the nutrition lookup stack (FatSecret + USDA providers,
service merge/cache/scaling, plausibility math).

All HTTP is respx-mocked. The contract pinned here:

* FatSecret: OAuth client-credentials token is fetched once and cached;
  search parses macros out of `food_description`; the single-hit
  dict-instead-of-list JSON quirk is handled; unparseable descriptions
  are skipped, not guessed.
* USDA: branded rows scale per-100g nutrients to the label serving;
  generic rows stay per-100g; rows missing P/F/C are dropped.
* Service: FatSecret-first merge, USDA fallback, 24h query cache,
  quantity scaling in code, structured errors (never raises).
"""

import httpx
import pytest
import respx

from prog_strength_mcp.nutrition_lookup import NutritionLookupService
from prog_strength_mcp.nutrition_lookup.fatsecret import (
    API_URL as FS_API_URL,
)
from prog_strength_mcp.nutrition_lookup.fatsecret import (
    OAUTH_TOKEN_URL,
    FatSecretProvider,
)
from prog_strength_mcp.nutrition_lookup.models import plausibility_warning
from prog_strength_mcp.nutrition_lookup.usda import SEARCH_URL as USDA_URL
from prog_strength_mcp.nutrition_lookup.usda import USDAProvider

TOKEN_JSON = {"access_token": "tok-1", "token_type": "Bearer", "expires_in": 86400}


def _fs_food(
    food_id: str = "12345",
    name: str = "Chick-n-Minis (4 Count)",
    brand: str = "Chick-fil-A",
    description: str = (
        "Per 4 minis - Calories: 360kcal | Fat: 13.00g | "
        "Carbs: 41.00g | Protein: 19.00g"
    ),
) -> dict:
    return {
        "food_id": food_id,
        "food_name": name,
        "food_type": "Brand",
        "brand_name": brand,
        "food_description": description,
    }


def _usda_food(
    fdc_id: int = 9999,
    description: str = "Egg, whole, cooked, scrambled",
    data_type: str = "Survey (FNDDS)",
    **extra,
) -> dict:
    return {
        "fdcId": fdc_id,
        "description": description,
        "dataType": data_type,
        "foodNutrients": [
            {"nutrientId": 1008, "nutrientName": "Energy", "unitName": "KCAL", "value": 212.0},
            {"nutrientId": 1003, "nutrientName": "Protein", "unitName": "G", "value": 13.8},
            {
                "nutrientId": 1004,
                "nutrientName": "Total lipid (fat)",
                "unitName": "G",
                "value": 16.2,
            },
            {
                "nutrientId": 1005,
                "nutrientName": "Carbohydrate, by difference",
                "unitName": "G",
                "value": 2.1,
            },
        ],
        **extra,
    }


# --- FatSecret provider -------------------------------------------------


@respx.mock
async def test_fatsecret_search_parses_description_and_sends_bearer():
    respx.post(OAUTH_TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_JSON))
    search = respx.get(FS_API_URL).mock(
        return_value=httpx.Response(200, json={"foods": {"food": [_fs_food()]}})
    )
    async with httpx.AsyncClient() as http:
        provider = FatSecretProvider(http, client_id="id", client_secret="secret")
        hits = await provider.search("chick fil a chicken minis", 5)

    assert search.calls.last.request.headers["Authorization"] == "Bearer tok-1"
    assert len(hits) == 1
    hit = hits[0]
    assert hit["name"] == "Chick-n-Minis (4 Count)"
    assert hit["brand"] == "Chick-fil-A"
    assert hit["serving_description"] == "4 minis"
    assert hit["per_serving"] == {
        "calories": 360.0,
        "protein_g": 19.0,
        "fat_g": 13.0,
        "carbs_g": 41.0,
    }
    assert hit["source"] == "fatsecret"
    assert hit["source_id"] == "12345"


@respx.mock
async def test_fatsecret_token_cached_across_searches():
    token_route = respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json=TOKEN_JSON)
    )
    respx.get(FS_API_URL).mock(
        return_value=httpx.Response(200, json={"foods": {"food": [_fs_food()]}})
    )
    async with httpx.AsyncClient() as http:
        provider = FatSecretProvider(http, client_id="id", client_secret="secret")
        await provider.search("big mac", 5)
        await provider.search("whopper", 5)

    assert token_route.call_count == 1


@respx.mock
async def test_fatsecret_single_result_dict_and_unparseable_skipped():
    respx.post(OAUTH_TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_JSON))
    # Single hit: FatSecret returns a bare dict, not a one-element list.
    respx.get(FS_API_URL).mock(
        return_value=httpx.Response(200, json={"foods": {"food": _fs_food()}})
    )
    async with httpx.AsyncClient() as http:
        provider = FatSecretProvider(http, client_id="id", client_secret="secret")
        hits = await provider.search("chicken minis", 5)
    assert len(hits) == 1

    respx.get(FS_API_URL).mock(
        return_value=httpx.Response(
            200,
            json={"foods": {"food": [_fs_food(description="no macros here")]}},
        )
    )
    async with httpx.AsyncClient() as http:
        provider = FatSecretProvider(http, client_id="id", client_secret="secret")
        hits = await provider.search("chicken minis", 5)
    assert hits == []


def test_fatsecret_unconfigured():
    provider = FatSecretProvider(httpx.AsyncClient(), client_id="", client_secret="")
    assert provider.configured is False


# --- USDA provider ------------------------------------------------------


@respx.mock
async def test_usda_generic_food_stays_per_100g():
    route = respx.get(USDA_URL).mock(
        return_value=httpx.Response(200, json={"foods": [_usda_food()]})
    )
    async with httpx.AsyncClient() as http:
        provider = USDAProvider(http, api_key="demo-key")
        hits = await provider.search("scrambled eggs", 5)

    params = dict(route.calls.last.request.url.params)
    assert params["api_key"] == "demo-key"
    assert params["query"] == "scrambled eggs"
    assert len(hits) == 1
    assert hits[0]["serving_description"] == "100 g"
    assert hits[0]["per_serving"]["calories"] == 212.0
    assert hits[0]["source"] == "usda"


@respx.mock
async def test_usda_branded_food_scales_to_label_serving():
    food = _usda_food(
        description="Greek Yogurt, Plain",
        data_type="Branded",
        brandOwner="Fage",
        servingSize=170.0,
        servingSizeUnit="g",
        householdServingFullText="1 container",
    )
    respx.get(USDA_URL).mock(return_value=httpx.Response(200, json={"foods": [food]}))
    async with httpx.AsyncClient() as http:
        provider = USDAProvider(http, api_key="demo-key")
        hits = await provider.search("fage greek yogurt", 5)

    hit = hits[0]
    assert hit["brand"] == "Fage"
    assert hit["serving_description"] == "1 container"
    # 212 kcal/100g * 1.7
    assert hit["per_serving"]["calories"] == pytest.approx(360.4)
    assert hit["per_serving"]["protein_g"] == pytest.approx(23.5, abs=0.1)


@respx.mock
async def test_usda_drops_rows_missing_macros():
    incomplete = {
        "fdcId": 1,
        "description": "Mystery food",
        "foodNutrients": [
            {"nutrientId": 1008, "nutrientName": "Energy", "unitName": "KCAL", "value": 100}
        ],
    }
    respx.get(USDA_URL).mock(
        return_value=httpx.Response(200, json={"foods": [incomplete, _usda_food()]})
    )
    async with httpx.AsyncClient() as http:
        provider = USDAProvider(http, api_key="demo-key")
        hits = await provider.search("eggs", 5)
    assert [h["source_id"] for h in hits] == ["9999"]


# --- Plausibility math --------------------------------------------------


def test_plausibility_ok_for_consistent_macros():
    # 360 kcal vs 4*19 + 4*41 + 9*13 = 357 — well within 25%.
    assert (
        plausibility_warning(
            {"calories": 360, "protein_g": 19, "fat_g": 13, "carbs_g": 41}
        )
        is None
    )


def test_plausibility_warns_on_divergent_macros():
    warning = plausibility_warning(
        {"calories": 900, "protein_g": 10, "fat_g": 5, "carbs_g": 20}
    )
    assert warning is not None
    assert "diverge" in warning


def test_plausibility_skips_tiny_calorie_items():
    # Diet drinks etc. — ratio math is meaningless under the floor.
    assert (
        plausibility_warning({"calories": 5, "protein_g": 0, "fat_g": 0, "carbs_g": 2})
        is None
    )


# --- Service ------------------------------------------------------------


def _service(client: httpx.AsyncClient, **keys) -> NutritionLookupService:
    return NutritionLookupService.from_config(
        fatsecret_client_id=keys.get("fs_id", "id"),
        fatsecret_client_secret=keys.get("fs_secret", "secret"),
        usda_fdc_api_key=keys.get("usda", "demo-key"),
        client=client,
    )


@respx.mock
async def test_service_scales_quantity_in_code():
    respx.post(OAUTH_TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_JSON))
    per_mini = _fs_food(
        name="Chick-n-Mini",
        description=(
            "Per 1 mini - Calories: 90kcal | Fat: 3.25g | "
            "Carbs: 10.25g | Protein: 4.75g"
        ),
    )
    respx.get(FS_API_URL).mock(
        return_value=httpx.Response(200, json={"foods": {"food": [per_mini]}})
    )
    # FatSecret returns fewer than max_results, so the service also
    # consults USDA — mock it empty to pin the FatSecret-only outcome.
    respx.get(USDA_URL).mock(return_value=httpx.Response(200, json={"foods": []}))
    async with httpx.AsyncClient() as http:
        result = await _service(http).lookup("chick fil a chicken mini", 10, 5)

    match = result["matches"][0]
    assert match["per_serving"]["calories"] == 90.0
    assert match["total_for_quantity"]["calories"] == 900.0
    assert match["total_for_quantity"]["protein_g"] == pytest.approx(47.5)
    assert result["quantity"] == 10


@respx.mock
async def test_service_falls_back_to_usda_when_fatsecret_empty():
    respx.post(OAUTH_TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_JSON))
    respx.get(FS_API_URL).mock(return_value=httpx.Response(200, json={"foods": None}))
    respx.get(USDA_URL).mock(
        return_value=httpx.Response(200, json={"foods": [_usda_food()]})
    )
    async with httpx.AsyncClient() as http:
        result = await _service(http).lookup("scrambled eggs", 2, 5)

    assert [m["source"] for m in result["matches"]] == ["usda"]


@respx.mock
async def test_service_survives_provider_error_with_other_provider_up():
    respx.post(OAUTH_TOKEN_URL).mock(return_value=httpx.Response(500, json={}))
    respx.get(USDA_URL).mock(
        return_value=httpx.Response(200, json={"foods": [_usda_food()]})
    )
    async with httpx.AsyncClient() as http:
        result = await _service(http).lookup("eggs", 1, 5)

    assert "error" not in result
    assert [m["source"] for m in result["matches"]] == ["usda"]


@respx.mock
async def test_service_structured_error_when_all_providers_fail():
    respx.post(OAUTH_TOKEN_URL).mock(return_value=httpx.Response(500, json={}))
    respx.get(USDA_URL).mock(return_value=httpx.Response(500, json={}))
    async with httpx.AsyncClient() as http:
        result = await _service(http).lookup("eggs", 1, 5)

    assert result["error"] == "lookup_failed"
    assert "fatsecret" in result["detail"]
    assert "usda" in result["detail"]


async def test_service_unconfigured_returns_lookup_unavailable():
    async with httpx.AsyncClient() as http:
        service = _service(http, fs_id="", fs_secret="", usda="")
        result = await service.lookup("eggs", 1, 5)
    assert result["error"] == "lookup_unavailable"


@respx.mock
async def test_service_caches_query_across_quantities():
    respx.post(OAUTH_TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_JSON))
    search = respx.get(FS_API_URL).mock(
        return_value=httpx.Response(200, json={"foods": {"food": [_fs_food()]}})
    )
    async with httpx.AsyncClient() as http:
        service = _service(http)
        first = await service.lookup("Chicken Minis", 1, 5)
        second = await service.lookup("chicken  minis", 2, 5)  # normalizes to same key

    assert search.call_count == 1
    assert first["matches"][0]["total_for_quantity"]["calories"] == 360.0
    assert second["matches"][0]["total_for_quantity"]["calories"] == 720.0
