"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvName = Literal["dev", "stage", "prod"]

_DEFAULT_BASE_URLS: dict[str, str] = {
    "dev": "https://tools.dev.trimble-ai.com",
    "stage": "https://tools.stage.trimble-ai.com",
    # TODO: Trimble has not published a stable prod hostname yet.
    # Fall back to stage so TRIMBLE_ENV=prod does not silently DNS-fail.
    # Override with TRIMBLE_TOOLS_API_BASE_URL=<real-prod-host> when known.
    "prod": "https://tools.stage.trimble-ai.com",
}

# Trimble Identity (TID) has a separate tenant per environment. Dev and
# staging share the pre-prod TID tenant; prod lives on the public tenant.
_DEFAULT_TOKEN_URLS: dict[str, str] = {
    "dev": "https://stage.id.trimble.com/oauth/token",
    "stage": "https://stage.id.trimble.com/oauth/token",
    "prod": "https://id.trimble.com/oauth/token",
}


class Settings(BaseSettings):
    """Environment-driven settings.

    All fields map to env vars documented in `.env.example`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Trimble Agentic AI Platform --------------------------------------- #
    trimble_env: EnvName = Field(
        default="dev",
        description="Which Agentic AI Platform environment to target.",
    )
    trimble_tools_api_dev_base_url: str = _DEFAULT_BASE_URLS["dev"]
    trimble_tools_api_stage_base_url: str = _DEFAULT_BASE_URLS["stage"]
    trimble_tools_api_prod_base_url: str = _DEFAULT_BASE_URLS["prod"]
    trimble_tools_api_base_url: str | None = Field(
        default=None,
        description="Explicit override. When set, wins over TRIMBLE_ENV.",
    )

    # --- Auth -------------------------------------------------------------- #
    trimble_access_token: str | None = Field(
        default=None,
        description="Static TID bearer token (fallback when no Authorization header is present).",
    )

    trimble_client_id: str | None = None
    trimble_client_secret: str | None = None
    trimble_token_url: str | None = Field(
        default=None,
        description=(
            "Trimble ID token endpoint. When unset, picked automatically from "
            "TRIMBLE_ENV (dev/stage -> stage.id.trimble.com, prod -> id.trimble.com)."
        ),
    )
    trimble_scopes: str | None = Field(
        default="openid tools",
        description=(
            "Space-separated OAuth scopes requested from Trimble ID. 'openid tools' "
            "is the minimum for the Agentic AI Platform Tools API. Add more scopes "
            "(e.g. agents, kb, models, kb-ingest, profile) only if the client has "
            "been granted them in the Trimble Cloud Console."
        ),
    )

    # --- MCP transport ----------------------------------------------------- #
    mcp_transport: str = Field(default="http", description="One of 'stdio', 'http', or 'sse'.")
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8754
    mcp_path: str = Field(
        default="/mcp/openapi-mcp",
        description=(
            "Public URL path where the Streamable HTTP endpoint lives. Must match "
            "the path clients hit at the nginx edge (default assumes /mcp/openapi-mcp/)."
        ),
    )

    # --- Workflow tuning --------------------------------------------------- #
    parse_poll_timeout_seconds: float = 120.0
    parse_poll_interval_seconds: float = 2.0
    max_spec_bytes: int = 1_048_576_000  # ~1000 MiB
    # Executor limit (e.g. OPENAPI_MAX_SPEC_OPERATIONS); used for spec analysis hints.
    platform_max_openapi_operations: int = 50

    @model_validator(mode="after")
    def _resolve_urls(self) -> Settings:
        if not self.trimble_tools_api_base_url:
            per_env = {
                "dev": self.trimble_tools_api_dev_base_url,
                "stage": self.trimble_tools_api_stage_base_url,
                "prod": self.trimble_tools_api_prod_base_url,
            }
            self.trimble_tools_api_base_url = per_env[self.trimble_env]
        if not self.trimble_token_url:
            self.trimble_token_url = _DEFAULT_TOKEN_URLS[self.trimble_env]
        return self

    @property
    def resolved_base_url(self) -> str:
        """Non-optional accessor for the resolved Tools API base URL."""
        assert self.trimble_tools_api_base_url, "base URL should be resolved by validator"
        return self.trimble_tools_api_base_url

    @property
    def resolved_token_url(self) -> str:
        """Non-optional accessor for the resolved Trimble ID token endpoint."""
        assert self.trimble_token_url, "token URL should be resolved by validator"
        return self.trimble_token_url

    @property
    def has_client_credentials(self) -> bool:
        return bool(self.trimble_client_id and self.trimble_client_secret)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
