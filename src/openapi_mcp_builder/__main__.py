"""Entrypoint: `python -m openapi_mcp_builder` or `openapi-mcp-builder`."""

from __future__ import annotations

import logging
import sys

from openapi_mcp_builder.config import get_settings
from openapi_mcp_builder.server import mcp


def main() -> None:
    """Run the MCP server using the transport from env config."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    settings = get_settings()
    transport = settings.mcp_transport.strip().lower()

    log = logging.getLogger("openapi_mcp_builder")
    base = settings.trimble_tools_api_base_url or ""
    log.info(
        "Starting openapi-mcp-builder on transport=%s TRIMBLE_ENV=%s base=%s",
        transport,
        settings.trimble_env,
        base,
    )
    if "tools.ai.trimble.com" in base:
        log.warning(
            "Tools API base URL is tools.ai.trimble.com; the preview OpenAPI "
            "routes /v1/openapi-servers* are not deployed there (HTTP 404). "
            "Unset TRIMBLE_TOOLS_API_BASE_URL and use TRIMBLE_ENV=stage, or set "
            "TRIMBLE_TOOLS_API_BASE_URL=https://tools.stage.trimble-ai.com"
        )

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport in {"http", "streamable-http", "sse"}:
        normalized = "http" if transport in {"http", "streamable-http"} else "sse"
        log.info(
            "Serving %s on %s:%d path=%s",
            normalized,
            settings.mcp_host,
            settings.mcp_port,
            settings.mcp_path,
        )
        mcp.run(
            transport=normalized,  # type: ignore[arg-type]
            host=settings.mcp_host,
            port=settings.mcp_port,
            path=settings.mcp_path,
        )
    else:
        raise SystemExit(
            f"Unknown MCP_TRANSPORT={settings.mcp_transport!r}. "
            "Expected one of: stdio, http, sse."
        )


if __name__ == "__main__":
    main()
