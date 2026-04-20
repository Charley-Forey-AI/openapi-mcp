"""Shared pytest fixtures and environment setup."""

from __future__ import annotations

import os

import pytest

from openapi_mcp_builder import config as config_module


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a developer's local `.env` from leaking into unit tests.

    We do two things:
      1. Strip every `TRIMBLE_*`, `MCP_*`, `PARSE_*`, and `MAX_SPEC_*` env var
         so the process environment is a clean slate.
      2. Point Settings at a non-existent env file so `.env` in the repo is
         never loaded during tests.
    """
    for key in list(os.environ):
        if key.startswith(("TRIMBLE_", "MCP_", "PARSE_", "MAX_SPEC_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TRIMBLE_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("TRIMBLE_TOOLS_API_BASE_URL", "https://tools.test.local")

    monkeypatch.setitem(
        config_module.Settings.model_config, "env_file", "tests/.env-never-exists"
    )

    config_module.get_settings.cache_clear()
