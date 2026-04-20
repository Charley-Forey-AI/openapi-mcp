"""Unit tests for the TokenProvider."""

from __future__ import annotations

import pytest

from openapi_mcp_builder.auth import AuthError, TokenProvider
from openapi_mcp_builder.config import Settings


async def test_obo_header_wins():
    provider = TokenProvider(Settings(trimble_access_token="env-token"))
    token = await provider.get_bearer_token("Bearer user-obo-token")
    assert token == "user-obo-token"


async def test_obo_without_prefix_accepted():
    provider = TokenProvider(Settings(trimble_access_token="env-token"))
    token = await provider.get_bearer_token("user-obo-token")
    assert token == "user-obo-token"


async def test_env_token_fallback():
    provider = TokenProvider(Settings(trimble_access_token="env-token"))
    token = await provider.get_bearer_token(None)
    assert token == "env-token"


async def test_no_token_raises():
    provider = TokenProvider(Settings(trimble_access_token=None))
    with pytest.raises(AuthError):
        await provider.get_bearer_token(None)


async def test_empty_bearer_header_falls_through_to_env():
    provider = TokenProvider(Settings(trimble_access_token="env-token"))
    token = await provider.get_bearer_token("Bearer ")
    assert token == "env-token"
