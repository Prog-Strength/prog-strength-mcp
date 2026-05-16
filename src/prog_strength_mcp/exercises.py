"""Exercise domain: MCP tools for browsing the shared exercise catalog.

Read-only; the catalog is admin-curated on the API side. No Pydantic input
models yet — the only tool has simple optional string filters.
"""

from typing import Any

from fastmcp import FastMCP

from prog_strength_mcp.api_client import APIClient, APIError


def register(mcp: FastMCP, api: APIClient) -> None:
    """Register exercise tools on `mcp`, backed by `api`."""

    @mcp.tool
    async def list_exercises(
        muscle_group: str | None = None,
        equipment: str | None = None,
    ) -> list[dict[str, Any]]:
        """List the shared, admin-curated exercise catalog.

        Call this before create_workout to discover the exact slug IDs the
        API expects — natural-language exercise names are not accepted there.
        Both filters are optional; pass them to narrow the catalog when the
        user describes a focused session (e.g., a quad day).

        Args:
            muscle_group: Optional filter, e.g. 'quads', 'hamstrings', 'chest',
                'back', 'shoulders', 'biceps', 'triceps', 'glutes', 'calves',
                'core'. Invalid values return a 400 from the API.
            equipment: Optional filter, e.g. 'barbell', 'dumbbell', 'machine',
                'cable', 'flat_bench', 'incline_bench', 'decline_bench', 'rack',
                'pullup_bar', 'none'. Invalid values return a 400 from the API.
        """
        try:
            return await api.list_exercises(muscle_group=muscle_group, equipment=equipment)
        except APIError as e:
            raise RuntimeError(f"API error ({e.status_code}): {e.message}") from e
