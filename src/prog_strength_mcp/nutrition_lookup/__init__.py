"""External nutrition data lookup: FatSecret + USDA FoodData Central.

Gives the agent grounded macros for one-off custom meals ("10 chicken
minis from Chick-fil-A") instead of LLM-estimated ones. FatSecret is
the primary provider (restaurant + branded coverage); USDA FDC fills
in generic/homemade foods. Quantity math happens here in code — the
model copies totals, it never multiplies.

See prog-strength-docs/sows/custom-meal-macro-accuracy.md.
"""

from prog_strength_mcp.nutrition_lookup.service import NutritionLookupService
from prog_strength_mcp.nutrition_lookup.tools import register

__all__ = ["NutritionLookupService", "register"]
