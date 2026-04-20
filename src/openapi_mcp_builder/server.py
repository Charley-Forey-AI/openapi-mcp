"""FastMCP server exposing the OpenAPI-to-MCP workflow as tools.

Transport modes:

* ``stdio`` (default): ideal for local CLI / desktop MCP clients. Auth falls
  back to ``TRIMBLE_ACCESS_TOKEN`` or client credentials.
* ``http``: for Trimble Agent Studio. Every tool call carries the user's
  ``Authorization: Bearer <TID-OBO-token>`` header, which we forward to the
  Agentic AI Platform so all actions run as the signed-in user.

Every tool returns a plain ``dict`` so MCP clients get structured JSON output
without custom content block handling.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openapi_mcp_builder.auth import AuthError, TokenProvider, extract_obo_header
from openapi_mcp_builder.client import ToolsAPIClient, TrimbleToolsAPIError
from openapi_mcp_builder.config import get_settings
from openapi_mcp_builder.models import (
    AuthConfig,
    OpenAPIServerUpdate,
)
from openapi_mcp_builder.workflow import (
    ParseTimeoutError,
    SpecDownloadError,
    create_mcp_from_spec_url,
)

mcp: FastMCP = FastMCP(
    name="openapi-mcp-builder",
    instructions=(
        "Turn any OpenAPI (Swagger) spec URL into a hosted MCP server on the "
        "Trimble Agentic AI Platform. Use `create_mcp_from_openapi_url` to do "
        "the full register -> upload -> parse flow and receive an MCP gateway "
        "URL. Use the other tools to list, inspect, update, refresh, or "
        "delete existing OpenAPI MCP servers."
    ),
)

_token_provider = TokenProvider()


async def _resolve_token() -> str:
    """Resolve the outbound bearer token, preferring the caller's OBO header."""
    try:
        return await _token_provider.get_bearer_token(extract_obo_header())
    except AuthError as exc:
        raise RuntimeError(str(exc)) from exc


def _error(exc: Exception) -> dict[str, Any]:
    """Format an exception as a structured tool error payload."""
    payload: dict[str, Any] = {
        "ok": False,
        "error": type(exc).__name__,
        "message": str(exc),
    }
    if isinstance(exc, TrimbleToolsAPIError):
        payload["status_code"] = exc.status_code
        if exc.body is not None:
            payload["details"] = exc.body
    return payload


# --------------------------------------------------------------------------- #
# Main workflow tool
# --------------------------------------------------------------------------- #

@mcp.tool(
    name="create_mcp_from_openapi_url",
    description=(
        "End-to-end flow: download an OpenAPI spec from a URL, register a new "
        "OpenAPI MCP server on the Trimble Agentic AI Platform, upload the "
        "spec to the returned SAS URL, wait for parsing to finish, and return "
        "the MCP gateway URL the agent can connect to. Defaults to "
        "passthrough auth so the upstream API receives the end user's TID "
        "on-behalf-of token at tool-invocation time."
    ),
)
async def create_mcp_from_openapi_url(
    spec_url: str,
    name: str,
    description: str = "",
    base_url: str | None = None,
    tags: list[str] | None = None,
    admins: list[str] | None = None,
    viewers: list[str] | None = None,
    required_scopes: list[str] | None = None,
    icon_url: str | None = None,
    auth_provider: str = "passthrough",
    inject_header: str = "Authorization",
    header_format: str = "Bearer {token}",
    credential_ref: str | None = None,
    static_headers: dict[str, str] | None = None,
    wait_for_parse: bool = True,
) -> dict[str, Any]:
    """Register an OpenAPI spec as an MCP server and return its gateway URL."""
    try:
        token = await _resolve_token()
        auth_cfg = AuthConfig(
            provider=auth_provider,  # type: ignore[arg-type]
            inject_header=inject_header,
            header_format=header_format,
            credential_ref=credential_ref,
            static_headers=static_headers,
        )
        result = await create_mcp_from_spec_url(
            token=token,
            spec_url=spec_url,
            name=name,
            description=description,
            base_url=base_url,
            tags=tags,
            admins=admins,
            viewers=viewers,
            required_scopes=required_scopes,
            icon_url=icon_url,
            auth_config=auth_cfg,
            wait_for_parse=wait_for_parse,
        )
    except (
        SpecDownloadError,
        ParseTimeoutError,
        TrimbleToolsAPIError,
        RuntimeError,
    ) as exc:
        return _error(exc)

    return {"ok": True, **result.as_dict()}


# --------------------------------------------------------------------------- #
# CRUD tools over existing OpenAPI MCP servers
# --------------------------------------------------------------------------- #

@mcp.tool(
    name="list_openapi_mcp_servers",
    description=(
        "List existing OpenAPI MCP servers. Optionally filter with a FIQL "
        "query (e.g. `tags=in=(ai);status==registered`), a free-text search, "
        "or an exact path lookup."
    ),
)
async def list_openapi_mcp_servers(
    q: str | None = None,
    search: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    try:
        token = await _resolve_token()
        async with ToolsAPIClient() as client:
            result = await client.list_servers(token, q=q, search=search, path=path)
    except (TrimbleToolsAPIError, RuntimeError) as exc:
        return _error(exc)
    return {"ok": True, **result.model_dump(mode="json")}


@mcp.tool(
    name="get_openapi_mcp_server",
    description="Fetch one OpenAPI MCP server by its stable UUID.",
)
async def get_openapi_mcp_server(server_id: str) -> dict[str, Any]:
    try:
        token = await _resolve_token()
        async with ToolsAPIClient() as client:
            server = await client.get_server(token, server_id)
    except (TrimbleToolsAPIError, RuntimeError) as exc:
        return _error(exc)
    return {"ok": True, "server": server.model_dump(mode="json")}


@mcp.tool(
    name="update_openapi_mcp_server",
    description=(
        "Patch an OpenAPI MCP server. Mutating `tools`, `tool_defaults`, "
        "`tool_filter`, or `route_maps` triggers an automatic re-parse. Pass "
        "`reupload=true` to also request a fresh SAS upload URL for a new "
        "spec version (returned as `spec_upload_url` in the response)."
    ),
)
async def update_openapi_mcp_server(
    server_id: str,
    patch: dict[str, Any],
    reupload: bool = False,
    if_match: str | None = None,
) -> dict[str, Any]:
    try:
        token = await _resolve_token()
        payload = OpenAPIServerUpdate.model_validate(patch)
        async with ToolsAPIClient() as client:
            server = await client.update_server(
                token,
                server_id,
                payload,
                reupload=reupload,
                if_match=if_match,
            )
    except (TrimbleToolsAPIError, RuntimeError) as exc:
        return _error(exc)
    return {"ok": True, "server": server.model_dump(mode="json")}


@mcp.tool(
    name="delete_openapi_mcp_server",
    description=(
        "Soft-delete an OpenAPI MCP server and remove its gateway route. "
        "The spec blob is retained for audit."
    ),
)
async def delete_openapi_mcp_server(
    server_id: str,
    if_match: str | None = None,
) -> dict[str, Any]:
    try:
        token = await _resolve_token()
        async with ToolsAPIClient() as client:
            await client.delete_server(token, server_id, if_match=if_match)
    except (TrimbleToolsAPIError, RuntimeError) as exc:
        return _error(exc)
    return {"ok": True, "deleted_id": server_id}


@mcp.tool(
    name="refresh_openapi_mcp_server",
    description=(
        "Queue a re-parse of the most recently uploaded spec. Use "
        "`force=true` (admin-only) to recover a stuck parse."
    ),
)
async def refresh_openapi_mcp_server(
    server_id: str,
    force: bool = False,
) -> dict[str, Any]:
    try:
        token = await _resolve_token()
        async with ToolsAPIClient() as client:
            server = await client.refresh_server(token, server_id, force=force)
    except (TrimbleToolsAPIError, RuntimeError) as exc:
        return _error(exc)
    return {"ok": True, "server": server.model_dump(mode="json")}


@mcp.tool(
    name="list_openapi_mcp_server_tools",
    description=(
        "Return the parsed tool definitions cached for an OpenAPI MCP server. "
        "Available only when `parse_status` is `success`."
    ),
)
async def list_openapi_mcp_server_tools(server_id: str) -> dict[str, Any]:
    try:
        token = await _resolve_token()
        async with ToolsAPIClient() as client:
            result = await client.list_parsed_tools(token, server_id)
    except (TrimbleToolsAPIError, RuntimeError) as exc:
        return _error(exc)
    return {"ok": True, **result.model_dump(mode="json")}


@mcp.tool(
    name="reupload_openapi_spec_from_url",
    description=(
        "Request a new SAS upload URL for an existing server, download the "
        "spec from `spec_url`, PUT it to Azure, and wait for re-parse. Use "
        "this to push a new version of the spec without creating a fresh "
        "server."
    ),
)
async def reupload_openapi_spec_from_url(
    server_id: str,
    spec_url: str,
    if_match: str | None = None,
    wait_for_parse: bool = True,
) -> dict[str, Any]:
    try:
        token = await _resolve_token()
        settings = get_settings()
        from openapi_mcp_builder.workflow import (
            _poll_parse_status,  # reuse internal helper
            download_spec,
        )
        spec_bytes, content_type = await download_spec(spec_url, settings.max_spec_bytes)
        async with ToolsAPIClient() as client:
            server = await client.update_server(
                token,
                server_id,
                OpenAPIServerUpdate(),
                reupload=True,
                if_match=if_match,
            )
            if not server.spec_upload_url:
                raise TrimbleToolsAPIError(
                    500,
                    "Platform did not return a fresh `spec_upload_url`.",
                    body=server.model_dump(),
                )
            await client.upload_spec_to_sas_url(
                server.spec_upload_url, spec_bytes, content_type=content_type
            )
            if wait_for_parse:
                server = await _poll_parse_status(client, token, server.id, settings)
    except (
        SpecDownloadError,
        ParseTimeoutError,
        TrimbleToolsAPIError,
        RuntimeError,
    ) as exc:
        return _error(exc)
    return {
        "ok": True,
        "server": server.model_dump(mode="json"),
        "spec_bytes": len(spec_bytes),
        "spec_content_type": content_type,
    }
