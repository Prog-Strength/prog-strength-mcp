"""FatSecret Platform API provider (Basic edition).

Primary lookup source because the Basic (free) tier includes US
restaurant and branded foods — exactly the gap USDA can't cover.
Auth is OAuth2 client-credentials; tokens are cached until shortly
before expiry so a lookup normally costs one HTTP call.

We parse macros out of `food_description` on the search response
("Per 1 sandwich - Calories: 440kcal | Fat: 19.00g | Carbs: 41.00g |
Protein: 28.00g") instead of N+1 `food.get` calls per candidate —
one round trip per lookup, and the description format is a stable,
documented part of foods.search. Candidates whose description doesn't
parse are skipped rather than guessed at.
"""

import logging
import re
import time
from typing import Any

import httpx

from prog_strength_mcp.nutrition_lookup.models import candidate

log = logging.getLogger(__name__)

OAUTH_TOKEN_URL = "https://oauth.fatsecret.com/connect/token"
API_URL = "https://platform.fatsecret.com/rest/server.api"

# "Per 1 sandwich - Calories: 440kcal | Fat: 19.00g | Carbs: 41.00g | Protein: 28.00g"
_DESCRIPTION_RE = re.compile(
    r"Per\s+(?P<serving>.+?)\s*-\s*"
    r"Calories:\s*(?P<calories>[\d.]+)\s*kcal\s*\|\s*"
    r"Fat:\s*(?P<fat>[\d.]+)\s*g\s*\|\s*"
    r"Carbs:\s*(?P<carbs>[\d.]+)\s*g\s*\|\s*"
    r"Protein:\s*(?P<protein>[\d.]+)\s*g",
    re.IGNORECASE,
)

# Refresh the cached token this many seconds before its stated expiry
# so an in-flight search never races an expiring token.
_TOKEN_REFRESH_MARGIN_S = 60


class FatSecretProvider:
    source = "fatsecret"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        client_id: str,
        client_secret: str,
    ):
        self._client = client
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        token = await self._get_token()
        resp = await self._client.get(
            API_URL,
            params={
                "method": "foods.search",
                "search_expression": query,
                "format": "json",
                "max_results": str(limit),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return _parse_search_response(resp.json(), limit)

    async def _get_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        resp = await self._client.post(
            OAUTH_TOKEN_URL,
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "client_credentials", "scope": "basic"},
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        expires_in = float(payload.get("expires_in", 0) or 0)
        self._token_expires_at = (
            time.monotonic() + max(expires_in - _TOKEN_REFRESH_MARGIN_S, 0)
        )
        return self._token


def _parse_search_response(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    foods = (payload.get("foods") or {}).get("food")
    if foods is None:
        return []
    # FatSecret's JSON is converted from XML: a single hit comes back as
    # a bare dict, multiple hits as a list.
    if isinstance(foods, dict):
        foods = [foods]
    out: list[dict[str, Any]] = []
    for food in foods:
        if not isinstance(food, dict):
            continue
        parsed = _DESCRIPTION_RE.search(food.get("food_description") or "")
        if not parsed:
            log.debug(
                "fatsecret: unparseable food_description for food_id=%s",
                food.get("food_id"),
            )
            continue
        out.append(
            candidate(
                name=food.get("food_name") or "",
                brand=food.get("brand_name") or "",
                serving_description=parsed.group("serving"),
                calories=float(parsed.group("calories")),
                protein_g=float(parsed.group("protein")),
                fat_g=float(parsed.group("fat")),
                carbs_g=float(parsed.group("carbs")),
                source="fatsecret",
                source_id=str(food.get("food_id") or ""),
            )
        )
        if len(out) >= limit:
            break
    return out
