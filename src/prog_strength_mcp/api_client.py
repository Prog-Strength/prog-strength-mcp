from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt


class APIError(RuntimeError):
    """Raised when the API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"api returned {status_code}: {message}")
        self.status_code = status_code
        self.message = message


# Match the API's JWTLifetime constant (7d) but mint short-lived tokens here —
# each tool call gets a fresh one, so there's no reason to issue long-lived
# credentials from this side. Five minutes is plenty of slack for clock skew
# and request latency.
_TOKEN_LIFETIME = timedelta(minutes=5)


def _mint_user_token(user_id: str, signing_key: str) -> str:
    """Issue an HS256 JWT with `sub=user_id`, matching the API's expected shape."""
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + _TOKEN_LIFETIME).timestamp()),
    }
    return jwt.encode(payload, signing_key, algorithm="HS256")


class APIClient:
    """Thin async wrapper around the Go Chi API.

    All calls are made on behalf of a specific user — the client mints a
    per-call JWT signed with the API's signing key. This server is
    effectively privileged: anything that can call it can read any user's
    data. Front-door auth on this server is a separate concern.
    """

    def __init__(self, base_url: str, signing_key: str, *, timeout: float = 10.0):
        self._signing_key = signing_key
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "APIClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def list_workouts(self, user_id: str) -> list[dict[str, Any]]:
        """GET /workouts as `user_id`. Returns the workouts list directly,
        unwrapped from the API's `{service, message, data}` envelope.
        """
        token = _mint_user_token(user_id, self._signing_key)
        resp = await self._client.get(
            "/workouts",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code >= 400:
            # The API returns `{service, error}` on failure — surface the
            # error string when present, fall back to the raw body otherwise.
            try:
                detail = resp.json().get("error", resp.text)
            except ValueError:
                detail = resp.text
            raise APIError(resp.status_code, detail)

        body = resp.json()
        data = body.get("data")
        return data if isinstance(data, list) else []
