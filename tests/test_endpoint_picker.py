"""Tests for MCP App endpoint picker tool and bundled HTML."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from openapi_mcp_builder.server import pick_openapi_endpoints
from openapi_mcp_builder.static_resources import ENDPOINT_PICKER_UI_URI, load_endpoint_picker_html

SPEC = {
    "openapi": "3.0.1",
    "info": {"title": "Demo", "version": "1.0"},
    "paths": {
        "/ping": {"get": {"tags": ["Health"], "responses": {"200": {"description": "ok"}}}},
    },
}


@pytest.mark.asyncio
async def test_pick_openapi_endpoints_returns_operations():
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.com/spec.json").mock(
            return_value=httpx.Response(
                200,
                text=json.dumps(SPEC),
                headers={"content-type": "application/json"},
            )
        )
        out = await pick_openapi_endpoints("https://example.com/spec.json")
    assert out["ok"] is True
    assert out["spec_url"] == "https://example.com/spec.json"
    assert out["operation_count"] == 1
    assert len(out["operations"]) == 1
    assert out["operations"][0]["operation_key"] == "GET /ping"
    assert out["operations"][0]["tags"] == ["Health"]
    assert "platform_max_openapi_operations" in out
    assert out["exceeds_platform_limit"] is False


@pytest.mark.asyncio
async def test_pick_openapi_endpoints_http_error():
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.com/missing.json").mock(return_value=httpx.Response(404))
        out = await pick_openapi_endpoints("https://example.com/missing.json")
    assert out["ok"] is False
    assert out["error"] == "SpecDownloadError"


def test_load_endpoint_picker_html_smoke():
    html = load_endpoint_picker_html()
    assert "OpenAPI endpoint picker" in html
    assert len(html) > 500


def test_endpoint_picker_ui_uri():
    assert ENDPOINT_PICKER_UI_URI == "ui://openapi-mcp-builder/endpoint-picker.html"
