"""USDA FoodData Central provider.

Fallback (and the strongest source for generic/homemade foods —
"two scrambled eggs", "1 cup cooked rice"). Search-response nutrient
values are per 100 g/ml; Branded entries additionally carry a label
serving size we scale to so per_serving means an actual serving, not
an arbitrary 100 g, whenever the data allows.
"""

import logging
from typing import Any

import httpx

from prog_strength_mcp.nutrition_lookup.models import candidate

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

# Search every data type: Branded for packaged goods, Survey (FNDDS)
# for as-eaten foods ("fried chicken, fast food"), Foundation/SR Legacy
# for raw ingredients.
_DATA_TYPES = "Foundation,SR Legacy,Survey (FNDDS),Branded"

# FDC nutrient numbers → our macro keys. Energy appears under 1008
# (kcal) on most rows and under the Atwater ids on some Foundation
# rows; _extract_macros falls back by name for those.
_NUTRIENT_IDS = {
    1008: "calories",
    1003: "protein_g",
    1004: "fat_g",
    1005: "carbs_g",
}

_GRAM_UNITS = {"g", "grm", "gram", "grams"}
_ML_UNITS = {"ml", "mlt"}


class USDAProvider:
    source = "usda"

    def __init__(self, client: httpx.AsyncClient, *, api_key: str):
        self._client = client
        self._api_key = api_key

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await self._client.get(
            SEARCH_URL,
            params={
                "api_key": self._api_key,
                "query": query,
                "dataType": _DATA_TYPES,
                "pageSize": str(limit),
            },
        )
        resp.raise_for_status()
        foods = resp.json().get("foods") or []
        out: list[dict[str, Any]] = []
        for food in foods:
            if not isinstance(food, dict):
                continue
            parsed = _to_candidate(food)
            if parsed is not None:
                out.append(parsed)
            if len(out) >= limit:
                break
        return out


def _to_candidate(food: dict[str, Any]) -> dict[str, Any] | None:
    per_100 = _extract_macros(food.get("foodNutrients") or [])
    if per_100 is None:
        return None

    scale = 1.0
    serving_description = "100 g"
    serving_size = food.get("servingSize")
    serving_unit = str(food.get("servingSizeUnit") or "").lower()
    if (
        isinstance(serving_size, int | float)
        and serving_size > 0
        and serving_unit in (_GRAM_UNITS | _ML_UNITS)
    ):
        scale = serving_size / 100.0
        household = str(food.get("householdServingFullText") or "").strip()
        unit_label = "ml" if serving_unit in _ML_UNITS else "g"
        serving_description = household or f"{serving_size:g} {unit_label}"

    brand = str(food.get("brandOwner") or food.get("brandName") or "")
    return candidate(
        name=str(food.get("description") or ""),
        brand=brand,
        serving_description=serving_description,
        calories=per_100["calories"] * scale,
        protein_g=per_100["protein_g"] * scale,
        fat_g=per_100["fat_g"] * scale,
        carbs_g=per_100["carbs_g"] * scale,
        source="usda",
        source_id=str(food.get("fdcId") or ""),
    )


def _extract_macros(nutrients: list[Any]) -> dict[str, float] | None:
    """Pull the four macros (per 100 g) out of a search-response
    nutrient list. Returns None when any macro other than energy is
    missing — a candidate without protein/fat/carbs isn't loggable.
    """
    out: dict[str, float] = {}
    for n in nutrients:
        if not isinstance(n, dict):
            continue
        key = _NUTRIENT_IDS.get(n.get("nutrientId"))
        if key is None:
            # Foundation rows sometimes report energy only under the
            # Atwater-specific ids; match those by name + unit.
            name = str(n.get("nutrientName") or "").lower()
            unit = str(n.get("unitName") or "").lower()
            if name.startswith("energy") and unit == "kcal":
                key = "calories"
            else:
                continue
        value = n.get("value")
        if isinstance(value, int | float) and key not in out:
            out[key] = float(value)
    if {"protein_g", "fat_g", "carbs_g"} - out.keys():
        return None
    if "calories" not in out:
        out["calories"] = 4 * out["protein_g"] + 4 * out["carbs_g"] + 9 * out["fat_g"]
    return out
