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
        """
        resp = await self._client.get(
            "/workouts",
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, list) else []

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
