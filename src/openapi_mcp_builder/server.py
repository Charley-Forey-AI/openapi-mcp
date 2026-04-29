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

import json
from typing import Any

import yaml
from fastmcp import FastMCP
from pydantic import ValidationError

from openapi_mcp_builder.auth import AuthError, TokenProvider, extract_obo_header
from openapi_mcp_builder.client import ToolsAPIClient, TrimbleToolsAPIError
from openapi_mcp_builder.config import get_settings
from openapi_mcp_builder.models import (
    AuthConfig,
    OpenAPIServerUpdate,
    ToolFilter,
)
from openapi_mcp_builder.spec_external_refs import summarize_external_refs
from openapi_mcp_builder.spec_inspect import (
    parse_openapi_spec_bytes,
    search_openapi_operations,
    tool_filter_from_tags,
)
from openapi_mcp_builder.spec_trim import spec_json_dumps_min, trim_openapi_document
from openapi_mcp_builder.tool_filter_validate import validate_openapi_tool_filter
from openapi_mcp_builder.workflow import (
    ParseTimeoutError,
    SpecDownloadError,
    analyze_openapi_spec_at_url,
    create_mcp_from_spec_url,
    download_spec,
)

mcp: FastMCP = FastMCP(
    name="openapi-mcp-builder",
    instructions=(
        "OpenAPI (Swagger) spec URL to a hosted MCP server on the Trimble Agentic AI Platform.\n\n"
        "Checklist (follow in order when the spec is large or unknown):\n"
        "1) Always run `analyze_openapi_spec_url` first. If `exceeds_platform_limit` is true, "
        "do **not** call `create_mcp_from_openapi_url` until you have a trim or acknowledge plan.\n"
        "2) The executor often enforces a max **operation count on the uploaded file** *before* "
        "`tool_filter` reduces tools. `tool_filter` = which operations become tools; **trim** = "
        "smaller file to pass the op cap. Use `export_trimmed_openapi_spec` and "
        "`reupload_openapi_spec_text`.\n"
        "3) Use `search_openapi_operations` to find paths/tags from a user phrase. "
        "4) Before sending `tool_filter` in create/update, run `validate_openapi_tool_filter` — "
        "use `include_paths` / `exclude_paths` as **regex** (e.g. .*foo.*), not `path_pattern` "
        "and not globs.\n"
        "5) Optional env: `CREATE_PREFLIGHT_ENFORCE=true` blocks create when over the cap with "
        "no filter/ack; set `acknowledge_openapi_operation_limit` on create to opt out.\n\n"
        "Other: `create_mcp_from_openapi_url` (register, upload, parse), "
        "list/inspect/update/delete/refresh, reupload from URL or body."
    ),
)

_token_provider = TokenProvider()


async def _resolve_token() -> str:
    """Resolve the outbound bearer token, preferring the caller's OBO header."""
    try:
        return await _token_provider.get_bearer_token(extract_obo_header())
    except AuthError as exc:
        raise RuntimeError(str(exc)) from exc


def _spec_text_to_bytes_and_content_type(spec_text: str) -> tuple[bytes, str]:
    """Return UTF-8 bytes and content type for a JSON or YAML OpenAPI document."""
    t = spec_text.strip()
    try:
        json.loads(t)
        return spec_text.encode("utf-8"), "application/json"
    except json.JSONDecodeError:
        try:
            yaml.safe_load(t)
        except yaml.YAMLError as exc:
            raise ValueError(f"Spec is not valid JSON or YAML: {exc}") from exc
        return spec_text.encode("utf-8"), "application/yaml"


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
# Spec analysis (no Tools API; uses public spec URL only)
# --------------------------------------------------------------------------- #


@mcp.tool(
    name="analyze_openapi_spec_url",
    description=(
        "Download and analyze an OpenAPI (or Swagger) spec URL. Returns per-tag "
        "operation counts, sample operation keys, top path prefixes, and whether "
        "the spec exceeds the typical platform tool limit. Use this before "
        "create to choose a tool_filter. Optionally pass include_tags_estimate "
        "to count how many operations match a tag set. Does not call the "
        "Trimble Tools API."
    ),
)
async def analyze_openapi_spec_url(
    spec_url: str,
    max_sample_ops_per_tag: int = 5,
    path_prefix_top_n: int = 30,
    include_tags_estimate: list[str] | None = None,
) -> dict[str, Any]:
    """Summarize a spec for planning include_tags / include_paths / include_operations."""
    try:
        settings = get_settings()
        return await analyze_openapi_spec_at_url(
            spec_url,
            settings=settings,
            max_sample_ops_per_tag=max_sample_ops_per_tag,
            path_prefix_top_n=path_prefix_top_n,
            include_tags_estimate=include_tags_estimate,
        )
    except SpecDownloadError as exc:
        return _error(exc)
    except ValueError as exc:
        return _error(exc)


@mcp.tool(
    name="search_openapi_operations",
    description=(
        "Download a spec from spec_url and return ranked path/method rows matching a free-text "
        "query (path, tag, operationId). Use to pick include_tags, path_substrings, or "
        "include_path_prefixes for export_trimmed_openapi_spec. Local only; no Tools API."
    ),
)
async def search_openapi_operations_tool(
    spec_url: str,
    query: str,
    limit: int = 50,
) -> dict[str, Any]:
    try:
        settings = get_settings()
        spec_bytes, _ = await download_spec(spec_url, settings.max_spec_bytes)
        spec = parse_openapi_spec_bytes(spec_bytes)
        rows = search_openapi_operations(spec, query, limit=limit)
        return {
            "ok": True,
            "spec_url": spec_url,
            "query": query,
            "count": len(rows),
            "matches": rows,
        }
    except (SpecDownloadError, ValueError) as exc:
        return _error(exc)


@mcp.tool(
    name="validate_openapi_tool_filter",
    description=(
        "Check a tool_filter object before create or update: list unknown key names, "
        "report invalid regex in include_paths/exclude_paths, and warn on glob-like patterns. "
        "Set strict=true to fail on unknown keys or glob-style path patterns. "
        "Does not call the Tools API."
    ),
)
async def validate_openapi_tool_filter_tool(
    tool_filter: dict[str, Any],
    strict: bool = False,
) -> dict[str, Any]:
    return validate_openapi_tool_filter(tool_filter, strict=strict)


@mcp.tool(
    name="build_tool_filter_for_tags",
    description=(
        "Build a `tool_filter` object with `include_tags` for use with "
        "`create_mcp_from_openapi_url` or `update_openapi_mcp_server`. The "
        "Agentic platform applies this on parse so only those tagged operations "
        "become MCP tools."
    ),
)
async def build_tool_filter_for_tags(
    include_tags: list[str],
) -> dict[str, Any]:
    if not include_tags or not [t for t in include_tags if t and t.strip()]:
        return {
            "ok": False,
            "error": "ValueError",
            "message": "include_tags must contain at least one non-empty tag name.",
        }
    cleaned = [t.strip() for t in include_tags if t and t.strip()]
    return {"ok": True, "tool_filter": tool_filter_from_tags(cleaned)}


@mcp.tool(
    name="export_trimmed_openapi_spec",
    description=(
        "Download a spec from spec_url and return a NEW OpenAPI document with "
        "only operations that match include_operation_keys (exclusive: exact "
        "method+path like GET /v1/pets), and/or include_tags, path_substrings, "
        "and/or include_path_prefixes. optional include_related_path_depth expands by "
        "N path segments (heuristic, tag/path mode only). Prunes unused components/ by $ref. "
        "When tool_filter does not help the op-count check, reupload the export via "
        "`reupload_openapi_spec_text`."
    ),
)
async def export_trimmed_openapi_spec(
    spec_url: str,
    include_operation_keys: list[str] | None = None,
    include_tags: list[str] | None = None,
    path_substrings: list[str] | None = None,
    include_path_prefixes: list[str] | None = None,
    include_related_path_depth: int | None = None,
    prune_referenced_components: bool = True,
) -> dict[str, Any]:
    try:
        settings = get_settings()
        spec_bytes, _ = await download_spec(spec_url, settings.max_spec_bytes)
        spec = parse_openapi_spec_bytes(spec_bytes)
        ext_in = summarize_external_refs(spec, max_samples=20)
        trimmed, before, after = trim_openapi_document(
            spec,
            include_operation_keys=include_operation_keys,
            include_tags=include_tags,
            path_substrings=path_substrings,
            include_path_prefixes=include_path_prefixes,
            include_related_path_depth=include_related_path_depth,
            prune_referenced_components=prune_referenced_components,
        )
        ext_out = summarize_external_refs(trimmed, max_samples=20)
        merged_refs: list[str] = list(
            dict.fromkeys(
                list(ext_in.get("external_ref_samples") or [])
                + list(ext_out.get("external_ref_samples") or [])
            )
        )
        out: dict[str, Any] = {
            "ok": True,
            "spec_url": spec_url,
            "original_operation_count": before,
            "trimmed_operation_count": after,
            "under_platform_limit": after <= settings.platform_max_openapi_operations,
            "external_ref_count": ext_in["external_ref_count"],
            "external_ref_count_trimmed": ext_out["external_ref_count"],
        }
        if ext_in.get("external_refs_note"):
            out["external_refs_note"] = ext_in["external_refs_note"]
        if merged_refs:
            seen: set[str] = set()
            wlist: list[dict[str, str]] = []
            for r in merged_refs[:20]:
                if r in seen:
                    continue
                seen.add(r)
                wlist.append(
                    {
                        "code": "EXTERNAL_REF",
                        "ref": r,
                        "hint": ext_in.get("external_refs_note", ""),
                    }
                )
            out["warnings"] = wlist
        text = spec_json_dumps_min(trimmed)
        raw = text.encode("utf-8")
        if len(raw) > settings.max_trimmed_spec_export_bytes:
            out["spec_json"] = None
            out["export_omitted"] = True
            out["export_bytes"] = len(raw)
            out["max_trimmed_spec_export_bytes"] = settings.max_trimmed_spec_export_bytes
            out["note"] = (
                "Response too large: narrow include_tags/path_substrings, or "
                "increase max_trimmed_spec_export_bytes; you can still reupload "
                "a locally trimmed file with reupload_openapi_spec_text."
            )
        else:
            out["spec_json"] = text
            out["export_omitted"] = False
        return out
    except (SpecDownloadError, ValueError) as exc:
        return _error(exc)


# --------------------------------------------------------------------------- #
# Main workflow tool
# --------------------------------------------------------------------------- #

@mcp.tool(
    name="create_mcp_from_openapi_url",
    description=(
        "End-to-end flow: download an OpenAPI spec from a URL, register a new "
        "OpenAPI MCP server on the Trimble Agentic AI Platform, upload the "
        "spec to the returned SAS URL, wait for parsing to finish, and return "
        "the MCP gateway URL the agent can connect to. Optional `tool_filter` "
        "(e.g. include_tags) may limit which operations become tools; the executor "
        "often still counts operations in the full file—trim if needed. "
        "`acknowledge_openapi_operation_limit` skips the local pre-flight that runs "
        "when CREATE_PREFLIGHT_ENFORCE is true. Defaults to passthrough auth so the "
        "upstream API receives the end user's TID on-behalf-of token at tool time."
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
    tool_filter: dict[str, Any] | None = None,
    wait_for_parse: bool = True,
    acknowledge_openapi_operation_limit: bool = False,
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
        tf: ToolFilter | None = None
        if tool_filter is not None:
            tf = ToolFilter.model_validate(tool_filter)
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
            tool_filter=tf,
            wait_for_parse=wait_for_parse,
            acknowledge_openapi_operation_limit=acknowledge_openapi_operation_limit,
        )
    except (
        SpecDownloadError,
        ParseTimeoutError,
        TrimbleToolsAPIError,
        RuntimeError,
    ) as exc:
        return _error(exc)
    except (ValueError, ValidationError) as exc:
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
        "server. Optional `tool_filter` is applied on the same PATCH (e.g. "
        "after `analyze_openapi_spec_url` to limit operations)."
    ),
)
async def reupload_openapi_spec_from_url(
    server_id: str,
    spec_url: str,
    if_match: str | None = None,
    tool_filter: dict[str, Any] | None = None,
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
        patch: OpenAPIServerUpdate
        if tool_filter is not None:
            patch = OpenAPIServerUpdate(
                tool_filter=ToolFilter.model_validate(tool_filter),
            )
        else:
            patch = OpenAPIServerUpdate()
        async with ToolsAPIClient() as client:
            server = await client.update_server(
                token,
                server_id,
                patch,
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
    except (ValueError, ValidationError) as exc:
        return _error(exc)
    return {
        "ok": True,
        "server": server.model_dump(mode="json"),
        "spec_bytes": len(spec_bytes),
        "spec_content_type": content_type,
    }


@mcp.tool(
    name="reupload_openapi_spec_text",
    description=(
        "Request a reupload SAS URL, then PUT the given spec body (JSON or YAML "
        "string) without hosting a URL. Use with `export_trimmed_openapi_spec` "
        "when the full spec is too large for the executor and tool_filter does "
        "not apply before the operation count check."
    ),
)
async def reupload_openapi_spec_text(
    server_id: str,
    spec_text: str,
    if_match: str | None = None,
    tool_filter: dict[str, Any] | None = None,
    wait_for_parse: bool = True,
) -> dict[str, Any]:
    try:
        spec_bytes, content_type = _spec_text_to_bytes_and_content_type(spec_text)
        token = await _resolve_token()
        settings = get_settings()
        from openapi_mcp_builder.workflow import _poll_parse_status

        patch: OpenAPIServerUpdate
        if tool_filter is not None:
            patch = OpenAPIServerUpdate(
                tool_filter=ToolFilter.model_validate(tool_filter),
            )
        else:
            patch = OpenAPIServerUpdate()
        async with ToolsAPIClient() as client:
            server = await client.update_server(
                token,
                server_id,
                patch,
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
        ParseTimeoutError,
        TrimbleToolsAPIError,
        RuntimeError,
        ValueError,
        ValidationError,
    ) as exc:
        return _error(exc)
    return {
        "ok": True,
        "server": server.model_dump(mode="json"),
        "spec_bytes": len(spec_bytes),
        "spec_content_type": content_type,
    }
