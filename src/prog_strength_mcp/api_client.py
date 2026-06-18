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
from urllib.parse import quote

import httpx


class APIError(RuntimeError):
    """Raised when the API returns a non-2xx response.

    `request_id` is the API's X-Request-ID for the failed call when the
    caller captured it (currently only lookup_food_nutrition does) —
    threaded through so even failures are traceable in CloudWatch.
    """

    def __init__(self, status_code: int, message: str, request_id: str = ""):
        super().__init__(f"api returned {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.request_id = request_id


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

    # --- Planned workouts --------------------------------------------

    async def create_planned_workout(
        self,
        auth_header: str,
        *,
        scheduled_start: str,
        scheduled_end: str,
        timezone: str | None = None,
        name: str | None = None,
        notes: str | None = None,
        calendar_detail: str | None = None,
        exercises: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """POST /planned-workouts. Creates a forward-looking planned
        workout. Omitted optional fields are left out of the body so the
        API's server-side defaults apply.
        """
        body: dict[str, Any] = {
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
        }
        if timezone is not None:
            body["timezone"] = timezone
        if name is not None:
            body["name"] = name
        if notes is not None:
            body["notes"] = notes
        if calendar_detail is not None:
            body["calendar_detail"] = calendar_detail
        if exercises is not None:
            body["exercises"] = exercises
        resp = await self._client.post(
            "/planned-workouts",
            json=body,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def list_planned_workouts(
        self,
        auth_header: str,
        *,
        timezone: str,
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """GET /planned-workouts with the timezone-aware date contract: a
        required IANA `timezone` plus either `date` (a single local day) or
        `start_date`+`end_date` (an inclusive local range), all YYYY-MM-DD.
        The API resolves them to the user-local day boundaries in UTC — the
        same contract the nutrition endpoints use, so the model never builds
        UTC timestamps itself (the bug that dropped evening workouts for any
        user not on UTC).

        Returns `{"workouts": [...], "request_id": "…"}` — the plans under
        `workouts`, plus the API's X-Request-ID so a "why did this return
        the wrong plans?" report pivots straight into CloudWatch
        (`filter request_id = "…"`), the same end-to-end tracing
        lookup_food_nutrition wired. The id rides the agent's tool_result
        SSE event because the result is a JSON object; a bare list (the old
        shape) could never carry it. A failure raises APIError carrying the
        same id, so empty results are just as traceable as served ones.
        """
        params: dict[str, str] = {"timezone": timezone}
        if date:
            params["date"] = date
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        resp = await self._client.get(
            "/planned-workouts",
            params=params,
            headers={"Authorization": auth_header},
        )
        # Captured before the status check so failed lists stay traceable.
        request_id = resp.headers.get("x-request-id", "")
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error", resp.text)
            except ValueError:
                detail = resp.text
            raise APIError(resp.status_code, detail, request_id=request_id)
        data = resp.json().get("data")
        out: dict[str, Any] = {"workouts": data if isinstance(data, list) else []}
        if request_id:
            out["request_id"] = request_id
        return out

    async def update_planned_workout(
        self,
        auth_header: str,
        planned_workout_id: str,
        *,
        scheduled_start: str | None = None,
        scheduled_end: str | None = None,
        timezone: str | None = None,
        name: str | None = None,
        notes: str | None = None,
        calendar_detail: str | None = None,
        exercises: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """PUT /planned-workouts/{id}. Omitted optional fields are left
        out of the body so the API leaves them unchanged / applies
        defaults.
        """
        body: dict[str, Any] = {}
        if scheduled_start is not None:
            body["scheduled_start"] = scheduled_start
        if scheduled_end is not None:
            body["scheduled_end"] = scheduled_end
        if timezone is not None:
            body["timezone"] = timezone
        if name is not None:
            body["name"] = name
        if notes is not None:
            body["notes"] = notes
        if calendar_detail is not None:
            body["calendar_detail"] = calendar_detail
        if exercises is not None:
            body["exercises"] = exercises
        resp = await self._client.put(
            f"/planned-workouts/{planned_workout_id}",
            json=body,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def skip_planned_workout(
        self, auth_header: str, planned_workout_id: str
    ) -> dict[str, Any]:
        """POST /planned-workouts/{id}/skip. Marks the plan skipped and
        returns the updated plan.
        """
        resp = await self._client.post(
            f"/planned-workouts/{planned_workout_id}/skip",
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def schedule_workout_to_calendar(
        self,
        auth_header: str,
        planned_workout_id: str,
        *,
        detail_level: str | None = None,
    ) -> dict[str, Any]:
        """POST /planned-workouts/{id}/schedule. Pushes the plan to the
        user's connected Google Calendar (Phase 3 calendar-sync API). Sends
        `{"detail_level": ...}` when provided, else an empty body so the
        API uses the plan's stored detail.
        """
        body: dict[str, Any] = {}
        if detail_level is not None:
            body["detail_level"] = detail_level
        resp = await self._client.post(
            f"/planned-workouts/{planned_workout_id}/schedule",
            json=body,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def complete_planned_workout(
        self,
        auth_header: str,
        planned_workout_id: str,
        *,
        session_id: str,
        session_kind: str,
    ) -> dict[str, Any]:
        """POST /planned-workouts/{id}/complete. Marks the plan completed
        and links the logged session (Phase 4 completion API). `session_kind`
        is "workout" or "activity".
        """
        body = {"session_id": session_id, "session_kind": session_kind}
        resp = await self._client.post(
            f"/planned-workouts/{planned_workout_id}/complete",
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

    async def log_consumption_batch(
        self,
        auth_header: str,
        *,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """POST /nutrition-log/batch. `items` is the already-serialized
        list of discriminated-union items ({kind, ...}). Returns the
        `{results, logged, failed}` data payload — best-effort, so a 200
        can still carry per-item failures in `results`.
        """
        resp = await self._client.post(
            "/nutrition-log/batch",
            json={"items": items},
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def lookup_food_nutrition(
        self,
        auth_header: str,
        *,
        query: str,
        quantity: float = 1,
        max_results: int = 5,
    ) -> dict[str, Any]:
        """GET /nutrition/lookup. The API owns the external-provider
        integration (FatSecret, USDA FDC) and the durable cache; this
        client just forwards. Returns the `{matches, quantity}` dict
        with the API's `request_id` attached — the correlation id for
        CloudWatch `filter request_id = "…"` debugging, threaded all
        the way to the frontend via the agent's tool_result SSE event.
        A 503 (providers unconfigured or all down) raises APIError
        (carrying the same request_id) — the tool layer adapts it into
        the structured error dict the agent prompt expects.
        """
        resp = await self._client.get(
            "/nutrition/lookup",
            params={
                "query": query,
                "quantity": str(quantity),
                "max_results": str(max_results),
            },
            headers={"Authorization": auth_header},
        )
        # Captured before the status check so failed lookups are just
        # as traceable as served ones.
        request_id = resp.headers.get("x-request-id", "")
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error", resp.text)
            except ValueError:
                detail = resp.text
            raise APIError(resp.status_code, detail, request_id=request_id)
        data = resp.json().get("data")
        out = data if isinstance(data, dict) else {}
        if request_id:
            out["request_id"] = request_id
        return out

    async def list_nutrition_log(
        self,
        auth_header: str,
        *,
        timezone: str,
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /nutrition-log. `timezone` is an IANA name the date params
        are interpreted in. Pass either `date` (single day) or
        `start_date`+`end_date` (range), all YYYY-MM-DD; the API validates
        the one-of constraint.
        """
        params: dict[str, str] = {"timezone": timezone}
        if date:
            params["date"] = date
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        resp = await self._client.get(
            "/nutrition-log",
            params=params,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, list) else []

    # --- Bodyweight --------------------------------------------------

    async def log_bodyweight(
        self,
        auth_header: str,
        *,
        weight: float,
        unit: str | None = None,
        measured_at: str | None = None,
    ) -> dict[str, Any]:
        """POST /bodyweight. Unit omitted defaults to the user's
        preferred WeightUnit server-side.
        """
        body: dict[str, Any] = {"weight": weight}
        if unit is not None:
            body["unit"] = unit
        if measured_at is not None:
            body["measured_at"] = measured_at
        resp = await self._client.post(
            "/bodyweight",
            json=body,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def list_bodyweight(
        self,
        auth_header: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /bodyweight. since/until are RFC3339 bounds on measured_at."""
        params: dict[str, str] = {}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        resp = await self._client.get(
            "/bodyweight",
            params=params,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, list) else []

    # --- Steps -------------------------------------------------------

    async def log_steps(
        self,
        auth_header: str,
        *,
        date: str,
        steps: int,
    ) -> dict[str, Any]:
        """PUT /steps/{date}. Upserts the daily step total for `date`
        (YYYY-MM-DD). Returns the persisted day entry.
        """
        resp = await self._client.put(
            f"/steps/{date}",
            json={"steps": steps},
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def get_steps(
        self,
        auth_header: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """GET /steps. since/until are YYYY-MM-DD bounds (both inclusive).
        Returns the `{steps, next_before}` object under `data`.
        """
        params: dict[str, str] = {}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        resp = await self._client.get(
            "/steps",
            params=params,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def get_steps_goal(self, auth_header: str) -> dict[str, Any]:
        """GET /me/steps-goal. Returns the `{goal, created_at, updated_at}`
        dict under `data`.
        """
        resp = await self._client.get(
            "/me/steps-goal",
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def set_steps_goal(self, auth_header: str, *, goal: int) -> dict[str, Any]:
        """PUT /me/steps-goal. Returns the persisted goal under `data`."""
        resp = await self._client.put(
            "/me/steps-goal",
            json={"goal": goal},
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    # --- Recipes -----------------------------------------------------

    async def list_recipes(self, auth_header: str) -> list[dict[str, Any]]:
        """GET /recipes. Returns recipes with components + derived
        macros inlined so the agent doesn't have to N+1 lookup.
        """
        resp = await self._client.get(
            "/recipes",
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, list) else []

    async def create_recipe(
        self,
        auth_header: str,
        *,
        name: str,
        components: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """POST /recipes. `components` is a list of
        {pantry_item_id, quantity} dicts in display order.
        """
        body = {"name": name, "components": components}
        resp = await self._client.post(
            "/recipes",
            json=body,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def get_daily_macros(
        self,
        auth_header: str,
        *,
        timezone: str,
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /nutrition-log/daily. Returns per-day totals, one row per
        user-local calendar date in `timezone` (an IANA name). Pass either
        `date` (single day) or `start_date`+`end_date` (range), all
        YYYY-MM-DD; the API validates the one-of constraint.
        """
        params: dict[str, str] = {"timezone": timezone}
        if date:
            params["date"] = date
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        resp = await self._client.get(
            "/nutrition-log/daily",
            params=params,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, list) else []

    async def get_macro_goals(self, auth_header: str) -> dict[str, Any]:
        """GET /me/macro-goals. Always returns 200 — the "never set"
        state surfaces as a row of zeros with null created_at /
        updated_at, and callers (the MCP tool, the agent) treat that
        as "the user hasn't set goals yet."
        """
        resp = await self._client.get(
            "/me/macro-goals",
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def put_macro_goals(
        self,
        auth_header: str,
        *,
        protein_g: int,
        carbs_g: int,
        fat_g: int,
        calories: int,
    ) -> dict[str, Any]:
        """PUT /me/macro-goals. Set-replacement: all four numbers
        required, the API rejects partial bodies with 400. Returns the
        persisted goals row.
        """
        body = {
            "protein_g": protein_g,
            "carbs_g": carbs_g,
            "fat_g": fat_g,
            "calories": calories,
        }
        resp = await self._client.put(
            "/me/macro-goals",
            json=body,
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    # --- Running -----------------------------------------------------

    async def list_running_best_efforts(self, auth_header: str) -> dict[str, Any]:
        """GET /running/best-efforts. Returns the `{best_efforts: [...]}`
        dict under the API's `data` envelope — the calling user's current
        best time across each standard running distance.
        """
        resp = await self._client.get(
            "/running/best-efforts",
            headers={"Authorization": auth_header},
        )
        _raise_for_status(resp)
        data = resp.json().get("data")
        return data if isinstance(data, dict) else {}

    async def get_running_max_effort_estimate(
        self, auth_header: str, *, distance_key: str | None = None
    ) -> dict[str, Any]:
        """GET /running/max-effort (cross-distance summary) or
        /running/max-effort/{distance_key} (per-distance detail) when a
        distance_key is given. Returns the dict under the API's `data`
        envelope — the user's predicted max-effort time(s).
        """
        if distance_key:
            path = f"/running/max-effort/{quote(distance_key, safe='')}"
        else:
            path = "/running/max-effort"
        resp = await self._client.get(
            path,
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
