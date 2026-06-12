"""Provider orchestration for nutrition lookup.

FatSecret first (restaurant + branded coverage), USDA appended when
FatSecret comes up short. Per-serving candidates are cached for 24h
keyed on the normalized query — quantity scaling happens after the
cache so "2 big macs" and "3 big macs" share one upstream hit, and
repeat lookups across a day stay off FatSecret's 5k/day quota.
"""

import logging
import time
from typing import Any

import httpx

from prog_strength_mcp.nutrition_lookup.fatsecret import FatSecretProvider
from prog_strength_mcp.nutrition_lookup.models import (
    NutritionProvider,
    plausibility_warning,
)
from prog_strength_mcp.nutrition_lookup.usda import USDAProvider

log = logging.getLogger(__name__)

_CACHE_TTL_S = 24 * 60 * 60
_CACHE_MAX_KEYS = 512


class NutritionLookupService:
    def __init__(self, providers: list[NutritionProvider]):
        self._providers = providers
        # normalized query -> (expires_at_monotonic, candidates)
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    @classmethod
    def from_config(
        cls,
        *,
        fatsecret_client_id: str,
        fatsecret_client_secret: str,
        usda_fdc_api_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> "NutritionLookupService":
        # One pooled client across both providers; external APIs get a
        # tighter timeout than the intra-VPC APIClient default because
        # a slow third party shouldn't stall the agent's tool loop.
        http = client or httpx.AsyncClient(timeout=8.0)
        return cls(
            providers=[
                FatSecretProvider(
                    http,
                    client_id=fatsecret_client_id,
                    client_secret=fatsecret_client_secret,
                ),
                USDAProvider(http, api_key=usda_fdc_api_key),
            ]
        )

    @property
    def configured(self) -> bool:
        return any(p.configured for p in self._providers)

    async def lookup(
        self, query: str, quantity: float, max_results: int
    ) -> dict[str, Any]:
        """Return {"matches": [...]} or {"error": ...}. Never raises —
        the agent prompt handles both shapes, and a flaky third-party
        API must degrade to "estimate it yourself," not kill the turn.
        """
        if not self.configured:
            return {
                "error": "lookup_unavailable",
                "detail": (
                    "no nutrition data providers are configured on this "
                    "server — estimate the macros yourself and say so."
                ),
            }

        candidates, errors = await self._candidates(query, max_results)
        if not candidates and errors:
            return {
                "error": "lookup_failed",
                "detail": "; ".join(errors),
            }

        matches = [_scale(c, quantity) for c in candidates]
        return {"matches": matches, "quantity": quantity}

    async def _candidates(
        self, query: str, max_results: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        key = " ".join(query.lower().split())
        cached = self._cache.get(key)
        if cached and time.monotonic() < cached[0]:
            return cached[1][:max_results], []

        merged: list[dict[str, Any]] = []
        errors: list[str] = []
        for provider in self._providers:
            if not provider.configured:
                continue
            if len(merged) >= max_results:
                break
            try:
                hits = await provider.search(query, max_results - len(merged))
            except Exception as exc:
                log.warning("nutrition lookup via %s failed: %s", provider.source, exc)
                errors.append(f"{provider.source}: {exc}")
                continue
            merged.extend(hits)

        # Only cache real results — a transient provider failure
        # shouldn't pin an empty answer for 24h.
        if merged:
            if len(self._cache) >= _CACHE_MAX_KEYS:
                self._cache.pop(min(self._cache, key=lambda k: self._cache[k][0]))
            self._cache[key] = (time.monotonic() + _CACHE_TTL_S, merged)
        return merged[:max_results], errors


def _scale(per_serving_candidate: dict[str, Any], quantity: float) -> dict[str, Any]:
    out = dict(per_serving_candidate)
    per = out["per_serving"]
    out["total_for_quantity"] = {
        macro: round(value * quantity, 1) for macro, value in per.items()
    }
    warning = plausibility_warning(per)
    if warning:
        out["plausibility_warning"] = warning
    return out
