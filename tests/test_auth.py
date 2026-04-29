"""Unit tests for the TokenProvider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openapi_mcp_builder.auth import AuthError, TokenProvider, extract_obo_header
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


def test_extract_obo_reads_raw_http_request_not_fastmcp_filtered_dict():
    """OBO must come from the Starlette request; FastMCP's get_http_headers() drops Authorization by default."""
    req = MagicMock()
    req.headers.get.return_value = "Bearer obo-from-studio"

    with patch("fastmcp.server.dependencies.get_http_request", return_value=req):
        assert extract_obo_header() == "Bearer obo-from-studio"
    req.headers.get.assert_called_once_with("authorization")


def test_extract_obo_none_when_no_http_context():
    with patch(
        "fastmcp.server.dependencies.get_http_request",
        side_effect=RuntimeError("no request context"),
    ):
        assert extract_obo_header() is None
