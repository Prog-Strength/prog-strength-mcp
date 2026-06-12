import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    api_base_url: str
    host: str
    port: int
    # External nutrition data providers for lookup_food_nutrition. All
    # optional — with none configured the tool degrades to a structured
    # "lookup_unavailable" and the agent falls back to estimating.
    fatsecret_client_id: str
    fatsecret_client_secret: str
    usda_fdc_api_key: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_base_url=os.environ.get("PROG_STRENGTH_API_BASE_URL", "http://localhost:8080"),
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8000")),
            fatsecret_client_id=os.environ.get("FATSECRET_CLIENT_ID", ""),
            fatsecret_client_secret=os.environ.get("FATSECRET_CLIENT_SECRET", ""),
            usda_fdc_api_key=os.environ.get("USDA_FDC_API_KEY", ""),
        )
