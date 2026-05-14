import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    api_base_url: str
    jwt_signing_key: str
    host: str
    port: int

    @classmethod
    def from_env(cls) -> "Config":
        try:
            jwt_signing_key = os.environ["JWT_SIGNING_KEY"]
        except KeyError as e:
            raise ConfigError(
                "JWT_SIGNING_KEY is required — must match the API's signing key "
                "so minted tokens validate."
            ) from e

        return cls(
            api_base_url=os.environ.get("PROG_STRENGTH_API_BASE_URL", "http://localhost:8080"),
            jwt_signing_key=jwt_signing_key,
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8000")),
        )
