"""Transparent forwarder to the Prog Strength API.

This server holds no signing keys. Each method takes an `auth_header`
string (the literal `Authorization` value, e.g. `Bearer eyJ…`) that the
caller — the tool handler — pulls off the inbound MCP request and
passes through. The API decodes the JWT itself and enforces ownership;
MCP is just plumbing.

Endpoints that don't require auth (e.g. `/exercises`) accept `None`
and omit the header.
"""

from typing import Any

import httpx


class APIError(RuntimeError):
    """Raised when the API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"api returned {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class APIClient:
    """Thin async wrapper around the Go Chi API.

    No signing keys, no token minting. Each call carries whichever
    Authorization header the inbound MCP request had — the agent
    sources this from the end-user's JWT, so the API sees the same
    identity it would on a direct browser call.
    """

    def __init__(self, base_url: str, *, timeout: float = 10.0):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "APIClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def list_workouts(self, auth_header: str) -> list[dict[str, Any]]:
        """GET /workouts. Returns the workouts list directly, unwrapped
        from the API's `{service, message, data}` envelope.

        The API's `data` is a pagination wrapper of the shape
        `{items, total, limit, offset, has_more}`. We surface just
        `items` to the agent because the tool currently returns a flat
        list and pagination is a future feature; older clients that
        kept consuming `data` directly as a list (no longer the case
        in this repo) would break, but the API and this client deploy
        together so that drift never lives across a deploy boundary.
        """
        resp = await self._client.get(
            "/workouts",
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data") or {}
        items = data.get("items") if isinstance(data, dict) else None
        return items if isinstance(items, list) else []

    async def list_exercises(
        self,
        *,
        muscle_group: str | None = None,
        equipment: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /exercises with optional filters. Public endpoint — no
        auth header is sent or required.
        """
        params: dict[str, str] = {}
        if muscle_group:
            params["muscle_group"] = muscle_group
        if equipment:
            params["equipment"] = equipment
        resp = await self._client.get("/exercises", params=params)
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, list) else []

    async def create_workout(
        self,
        auth_header: str,
        *,
        exercises: list[dict[str, Any]],
        name: str | None = None,
        performed_at: str | None = None,
        ended_at: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """POST /workouts. Body shape mirrors the Go handler's
        createWorkoutRequest. Omitted fields are left out so the API's
        server-side defaults (name = "Workout - <date>", performed_at = now)
        kick in.
        """
        body: dict[str, Any] = {"exercises": exercises}
        if name is not None:
            body["name"] = name
        if performed_at is not None:
            body["performed_at"] = performed_at
        if ended_at is not None:
            body["ended_at"] = ended_at
        if notes is not None:
            body["notes"] = notes

        resp = await self._client.post(
            "/workouts",
            json=body,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}


    # --- Pantry items ------------------------------------------------

    async def list_pantry_items(
        self, auth_header: str, *, query: str | None = None
    ) -> list[dict[str, Any]]:
        """GET /pantry-items. Optional substring filter on name."""
        params: dict[str, str] = {}
        if query:
            params["q"] = query
        resp = await self._client.get(
            "/pantry-items",
            params=params,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, list) else []

    async def create_pantry_item(
        self,
        auth_header: str,
        *,
        name: str,
        calories: float,
        protein_g: float,
        fat_g: float,
        carbs_g: float,
        serving_size: float,
        serving_unit: str,
    ) -> dict[str, Any]:
        """POST /pantry-items. Macros are per-serving."""
        body = {
            "name": name,
            "calories": calories,
            "protein_g": protein_g,
            "fat_g": fat_g,
            "carbs_g": carbs_g,
            "serving_size": serving_size,
            "serving_unit": serving_unit,
        }
        resp = await self._client.post(
            "/pantry-items",
            json=body,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    # --- Nutrition log -----------------------------------------------

    async def log_consumption(
        self,
        auth_header: str,
        *,
        pantry_item_id: str,
        quantity: float,
        consumed_at: str | None = None,
    ) -> dict[str, Any]:
        """POST /nutrition-log. Phase 1 supports pantry-item-backed
        entries only — recipes ship in a later phase.
        """
        body: dict[str, Any] = {
            "pantry_item_id": pantry_item_id,
            "quantity": quantity,
        }
        if consumed_at is not None:
            body["consumed_at"] = consumed_at
        resp = await self._client.post(
            "/nutrition-log",
            json=body,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def list_nutrition_log(
        self,
        auth_header: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /nutrition-log. RFC3339 since/until bound consumed_at."""
        params: dict[str, str] = {}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        resp = await self._client.get(
            "/nutrition-log",
            params=params,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, list) else []

    async def get_daily_macros(
        self,
        auth_header: str,
        *,
        since: str,
        until: str,
    ) -> list[dict[str, Any]]:
        """GET /nutrition-log/daily. Returns per-day totals for the
        [since, until) UTC range. Both bounds are required.
        """
        resp = await self._client.get(
            "/nutrition-log/daily",
            params={"since": since, "until": until},
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, list) else []


def _raise_for_status(resp: httpx.Response) -> None:
    """Convert a non-2xx API response into APIError, pulling the `error`
    field out of the standard `{service, error}` envelope when present.
    """
    if resp.status_code < 400:
        return
    try:
        detail = resp.json().get("error", resp.text)
    except ValueError:
        detail = resp.text
    raise APIError(resp.status_code, detail)
