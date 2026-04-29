"""MCP App UI: bundled single-file HTML for the inline endpoint picker."""

from __future__ import annotations

from importlib import resources

ENDPOINT_PICKER_UI_URI = "ui://openapi-mcp-builder/endpoint-picker.html"


def load_endpoint_picker_html() -> str:
    """Return the single-file MCP App HTML (built by Vite into static/)."""
    return (
        resources.files("openapi_mcp_builder")
        .joinpath("static/endpoint_picker_mcp.html")
        .read_text(encoding="utf-8")
    )
