import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    api_base_url: str
    host: str
    port: int

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_base_url=os.environ.get("PROG_STRENGTH_API_BASE_URL", "http://localhost:8080"),
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8000")),
        )
