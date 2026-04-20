"""Shared pytest fixtures and environment setup."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent real `.env` files from leaking into unit tests."""
    for key in list(os.environ):
        if key.startswith("TRIMBLE_") or key.startswith("MCP_") or key.startswith("PARSE_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TRIMBLE_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("TRIMBLE_TOOLS_API_BASE_URL", "https://tools.test.local")
    # Invalidate Settings cache so new env is picked up.
    from openapi_mcp_builder.config import get_settings

    get_settings.cache_clear()
