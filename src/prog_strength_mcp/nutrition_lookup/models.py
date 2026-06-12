"""Shared shapes + macro math for nutrition lookup providers.

Providers return per-serving candidates as plain dicts (FastMCP tools
serialize dicts directly); the service layer scales them to the
requested quantity and attaches plausibility warnings.
"""

from typing import Any, Protocol


class NutritionProvider(Protocol):
    """One external nutrition data source. Implementations must be
    safe to call concurrently and must raise (not swallow) on HTTP
    failures — the service layer decides how to degrade.
    """

    source: str

    @property
    def configured(self) -> bool: ...

    async def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Return up to `limit` per-serving candidates for `query`.
        Each candidate is a dict with: name, brand (may be ""),
        serving_description, per_serving {calories, protein_g, fat_g,
        carbs_g}, source, source_id.
        """
        ...


def candidate(
    *,
    name: str,
    brand: str,
    serving_description: str,
    calories: float,
    protein_g: float,
    fat_g: float,
    carbs_g: float,
    source: str,
    source_id: str,
) -> dict[str, Any]:
    """Normalize one provider hit into the shared candidate shape."""
    return {
        "name": name,
        "brand": brand,
        "serving_description": serving_description,
        # Two decimals on per-serving values: these get multiplied by
        # quantity downstream, so rounding here compounds (4.75g → 4.8g
        # is +0.5g at quantity=10). Totals round to 1 decimal at scale
        # time.
        "per_serving": {
            "calories": round(calories, 2),
            "protein_g": round(protein_g, 2),
            "fat_g": round(fat_g, 2),
            "carbs_g": round(carbs_g, 2),
        },
        "source": source,
        "source_id": source_id,
    }


def plausibility_warning(macros: dict[str, Any]) -> str | None:
    """Flag macro rows whose calories diverge from the Atwater-derived
    value (4·protein + 4·carbs + 9·fat) by more than 25%.

    Some source entries have data-entry errors; the agent is told to
    prefer candidates without a warning. This is a heuristic, not a
    validator — fiber, sugar alcohols, and alcohol (7 cal/g) all push
    legitimate foods off the 4/4/9 line, hence the wide band and the
    floor on tiny-calorie items where the ratio is meaningless.
    """
    calories = float(macros.get("calories", 0) or 0)
    if calories <= 20:
        return None
    derived = (
        4 * float(macros.get("protein_g", 0) or 0)
        + 4 * float(macros.get("carbs_g", 0) or 0)
        + 9 * float(macros.get("fat_g", 0) or 0)
    )
    if abs(derived - calories) / calories <= 0.25:
        return None
    return (
        f"stated calories ({calories:g}) diverge >25% from the "
        f"4P+4C+9F-derived value ({derived:g}) — the source entry may "
        f"contain a data error; prefer a candidate without this warning."
    )
