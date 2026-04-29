"""End-to-end workflow: OpenAPI spec URL -> hosted MCP gateway URL.

Steps:

1. Download the spec bytes from the user-supplied URL (JSON or YAML).
2. Register a new OpenAPI server (metadata only). The platform returns a
   time-limited SAS PUT URL in ``spec_upload_url``.
3. PUT the raw spec bytes to that SAS URL.
4. Poll ``GET /v1/openapi-servers/{id}`` until ``parse_status`` leaves the
   ``pending|queued|parsing`` set or we hit the timeout.
5. Return the final server record including ``gateway_url`` (the MCP URL
   to hand back to the caller).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
import yaml

from openapi_mcp_builder.client import ToolsAPIClient, TrimbleToolsAPIError
from openapi_mcp_builder.config import Settings, get_settings
from openapi_mcp_builder.models import (
    AuthConfig,
    OpenAPIServer,
    OpenAPIServerCreate,
    ToolFilter,
)
from openapi_mcp_builder.operation_key import normalize_operation_key_input
from openapi_mcp_builder.spec_inspect import (
    build_summary,
    count_operations_matching_any_tag,
    enumerate_operations,
    parse_openapi_spec_bytes,
)
from openapi_mcp_builder.spec_trim import spec_json_dumps_min, trim_openapi_document

_TERMINAL_PARSE_STATES = {"success", "failed", "error"}
_PENDING_PARSE_STATES = {"pending", "queued", "parsing"}


class SpecDownloadError(RuntimeError):
    """Raised when we cannot fetch the OpenAPI spec from the provided URL."""


class ParseTimeoutError(RuntimeError):
    """Raised when the platform does not finish parsing the spec in time."""


@dataclass
class CreateResult:
    """Result of the create-from-URL workflow."""

    server: OpenAPIServer
    parse_status: str
    gateway_url: str | None
    mcp_server_url: str | None
    tool_count: int
    waited_seconds: float
    spec_bytes: int
    spec_content_type: str
    client_spec_trimmed: bool = False
    original_operation_count: int | None = None
    trimmed_operation_count: int | None = None
    client_trim_note: str | None = None

    def as_dict(self) -> dict:
        d: dict[str, Any] = {
            "id": self.server.id,
            "name": self.server.name,
            "parse_status": self.parse_status,
            "parse_error": self.server.parse_error,
            "gateway_url": self.gateway_url,
            "mcp_server_url": self.mcp_server_url,
            "tool_count": self.tool_count,
            "path": self.server.path,
            "namespace": self.server.namespace,
            "status": self.server.status,
            "routing_status": self.server.routing_status,
            "spec_bytes": self.spec_bytes,
            "spec_content_type": self.spec_content_type,
            "waited_seconds": round(self.waited_seconds, 2),
        }
        if self.client_spec_trimmed:
            d["client_spec_trimmed"] = True
            d["original_operation_count"] = self.original_operation_count
            d["trimmed_operation_count"] = self.trimmed_operation_count
            if self.client_trim_note:
                d["client_trim_note"] = self.client_trim_note
        return d


async def download_spec(url: str, max_bytes: int) -> tuple[bytes, str]:
    """Download an OpenAPI spec over HTTPS.

    Returns the raw bytes and the ``Content-Type`` we'll send to Azure.
    Validates that the payload parses as either JSON or YAML so we catch
    mistakes before burning a SAS URL.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise SpecDownloadError(f"Failed to fetch spec from {url}: {exc}") from exc

    if resp.status_code >= 400:
        raise SpecDownloadError(
            f"Spec URL returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    body = resp.content
    if len(body) > max_bytes:
        raise SpecDownloadError(
            f"Spec is {len(body)} bytes, exceeds max of {max_bytes}."
        )
    if not body:
        raise SpecDownloadError("Spec URL returned an empty body.")

    content_type = _classify_spec(body, url, resp.headers.get("content-type", ""))
    return body, content_type


def _classify_spec(body: bytes, url: str, header_ct: str) -> str:
    """Validate and classify the spec as JSON or YAML, returning a content type."""
    text = body.decode("utf-8", errors="replace").lstrip()

    # Try JSON first (cheapest unambiguous format).
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return "application/json"
    except json.JSONDecodeError:
        pass

    # Fall back to YAML.
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecDownloadError(f"Spec is neither valid JSON nor YAML: {exc}") from exc

    if not isinstance(parsed, dict):
        raise SpecDownloadError("Parsed spec is not a mapping/object.")
    if "openapi" not in parsed and "swagger" not in parsed:
        raise SpecDownloadError(
            "Document is missing `openapi` or `swagger` top-level field."
        )

    lower_url = url.lower()
    if lower_url.endswith((".yaml", ".yml")) or "yaml" in header_ct.lower():
        return "application/yaml"
    return "application/yaml"


async def analyze_openapi_spec_at_url(
    spec_url: str,
    *,
    settings: Settings | None = None,
    max_sample_ops_per_tag: int = 5,
    path_prefix_top_n: int = 30,
    include_tags_estimate: list[str] | None = None,
) -> dict[str, Any]:
    """Download a spec, parse it, and return tag/path summaries for tool_filter planning."""
    settings = settings or get_settings()
    spec_bytes, _ = await download_spec(spec_url, settings.max_spec_bytes)
    spec = parse_openapi_spec_bytes(spec_bytes)
    ops = enumerate_operations(spec)
    lim = settings.platform_max_openapi_operations
    summary = build_summary(
        spec,
        operations=ops,
        platform_max_operations=lim,
        max_sample_ops_per_tag=max(0, max_sample_ops_per_tag),
        path_prefix_top_n=max(0, path_prefix_top_n),
    )
    out: dict[str, Any] = {**summary, "spec_url": spec_url, "spec_bytes": len(spec_bytes)}
    if include_tags_estimate is not None and len(include_tags_estimate) > 0:
        n = count_operations_matching_any_tag(ops, include_tags_estimate)
        out["include_tags_estimate"] = {
            "tags": include_tags_estimate,
            "matching_operation_count": n,
            "fits_platform_limit": n <= lim,
        }
    return out


def _nonempty_str_list(v: list[str] | None) -> list[str]:
    if not v:
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def _operation_ids_to_keys(
    spec: dict[str, Any], identifiers: list[str]
) -> list[str]:
    """Map tool_filter ``include_operations`` entries to ``GET /path`` keys."""
    by_id: dict[str, str] = {}
    for op in enumerate_operations(spec):
        oid = op.get("operation_id")
        if isinstance(oid, str) and oid.strip():
            by_id[oid.strip()] = str(op["operation_key"])
    out: list[str] = []
    seen: set[str] = set()
    for raw in identifiers:
        s = str(raw).strip()
        if not s:
            continue
        k = normalize_operation_key_input(s)
        if k:
            if k not in seen:
                seen.add(k)
                out.append(k)
        elif s in by_id:
            k2 = by_id[s]
            if k2 not in seen:
                seen.add(k2)
                out.append(k2)
    return out


def _client_trim_bytes_for_create(
    spec: dict[str, Any],
    tool_filter: ToolFilter,
) -> tuple[dict[str, Any], int, int]:
    """Return trimmed spec and before/after operation counts, or raise SpecDownloadError."""
    tags = _nonempty_str_list(tool_filter.include_tags)
    paths = _nonempty_str_list(tool_filter.include_paths)
    op_ids = _nonempty_str_list(tool_filter.include_operations)
    n_modes = sum(1 for x in (tags, paths, op_ids) if x)
    if n_modes == 0:
        raise SpecDownloadError(
            "The OpenAPI file has more operations than the platform parser allows, and "
            "`tool_filter` did not include any of include_tags, include_paths, or "
            "include_operations, so the spec could not be trimmed before upload. "
            "Use export_trimmed_openapi_spec + reupload_openapi_spec_text, or add "
            "inclusion filters to tool_filter."
        )
    if op_ids and (tags or paths):
        raise SpecDownloadError(
            "Client-side trim on create does not support mixing include_operations with "
            "include_tags or include_paths. Use export_trimmed_openapi_spec + "
            "reupload_openapi_spec_text, or use only one inclusion style in tool_filter."
        )
    if op_ids:
        keys = _operation_ids_to_keys(spec, op_ids)
        if not keys:
            raise SpecDownloadError(
                "include_operations could not be resolved to method+path keys or "
                "operationId values in the spec."
            )
        trimmed, before, after = trim_openapi_document(
            spec, include_operation_keys=keys
        )
        return trimmed, before, after
    trimmed, before, after = trim_openapi_document(
        spec,
        include_tags=tags or None,
        path_substrings=paths or None,
    )
    return trimmed, before, after


def _maybe_client_trim_spec_for_upload(
    spec_bytes: bytes,
    content_type: str,
    tool_filter: ToolFilter | None,
    *,
    platform_max: int,
    auto_trim: bool,
) -> tuple[bytes, str, int, int, bool, str | None]:
    """If needed, return JSON bytes of a tag/path/op-list-trimmed spec for SAS upload.

    The executor enforces operation counts on the **uploaded** document, often before
    applying tool_filter, so we must send a smaller file when over the cap.
    """
    spec = parse_openapi_spec_bytes(spec_bytes)
    n = len(enumerate_operations(spec))
    if n <= platform_max or not auto_trim or tool_filter is None:
        return spec_bytes, content_type, n, n, False, None
    try:
        trimmed, before, after = _client_trim_bytes_for_create(spec, tool_filter)
    except (ValueError, SpecDownloadError) as exc:
        if isinstance(exc, ValueError):
            # trim_openapi_document validation
            raise SpecDownloadError(
                f"Could not apply client-side trim from tool_filter: {exc}"
            ) from exc
        raise
    if after == 0:
        raise SpecDownloadError(
            "After applying tool_filter, no operations remain in the spec. "
            "Widen include_tags, include_paths, or include_operations."
        )
    if after > platform_max:
        raise SpecDownloadError(
            f"After applying tool_filter, the spec still has {after} operations "
            f"(limit {platform_max}). Use export_trimmed_openapi_spec to narrow further "
            f"(e.g. include_operation_keys) or reupload_openapi_spec_text with a smaller file."
        )
    out = spec_json_dumps_min(trimmed).encode("utf-8")
    note = (
        "Client-trimmed the spec before upload so the parser sees "
        f"{after} operation(s) (raw file had {before}). tool_filter is still sent to the API."
    )
    return out, "application/json", before, after, True, note


async def create_mcp_from_spec_url(
    *,
    token: str,
    spec_url: str,
    name: str,
    description: str = "",
    base_url: str | None = None,
    tags: list[str] | None = None,
    admins: list[str] | None = None,
    viewers: list[str] | None = None,
    required_scopes: list[str] | None = None,
    icon_url: str | None = None,
    auth_config: AuthConfig | None = None,
    tool_filter: ToolFilter | None = None,
    wait_for_parse: bool = True,
    acknowledge_openapi_operation_limit: bool = False,
    settings: Settings | None = None,
    client: ToolsAPIClient | None = None,
) -> CreateResult:
    """Register a new OpenAPI MCP server from a spec URL.

    If ``base_url`` is omitted, we derive it from the first ``servers[0].url``
    entry of the downloaded spec.

    Pass ``tool_filter`` to limit which operations become MCP tools (e.g. stay
    under the platform operation cap) when the Tools API accepts it on create.

    When ``Settings.create_preflight_enforce`` is true and the spec has more
    operations than ``Settings.platform_max_openapi_operations`` and
    ``tool_filter`` is not set, this function raises :class:`SpecDownloadError`
    unless ``acknowledge_openapi_operation_limit`` is true (avoids a doomed
    register/upload/parse that may fail on the executor cap).

    When ``Settings.create_auto_trim_on_tool_filter`` is true (default) and
    ``tool_filter`` includes at least one of ``include_tags``, ``include_paths``,
    or ``include_operations``, the document is **trimmed locally** before the
    SAS upload whenever the raw operation count exceeds the cap (the platform
    parser typically counts the uploaded file before applying tool_filter).
    """
    settings = settings or get_settings()

    spec_bytes, content_type = await download_spec(spec_url, settings.max_spec_bytes)

    if (
        settings.create_preflight_enforce
        and not acknowledge_openapi_operation_limit
        and tool_filter is None
    ):
        n = len(enumerate_operations(parse_openapi_spec_bytes(spec_bytes)))
        if n > settings.platform_max_openapi_operations:
            raise SpecDownloadError(
                f"Pre-flight: the spec has {n} operations, which exceeds the typical "
                f"executor cap ({settings.platform_max_openapi_operations}). The platform "
                "may count all operations in the upload before `tool_filter` is applied, so "
                "a smaller document is often required. Run `analyze_openapi_spec_url` and "
                "`search_openapi_operations`, then `export_trimmed_openapi_spec` and "
                "`reupload_openapi_spec_text` (or re-create after trimming). To skip this "
                "local check, pass acknowledge_openapi_operation_limit=true, or set "
                "a tool_filter with include_tags/include_paths/include_operations "
                "(client-side trim on create), or set CREATE_PREFLIGHT_ENFORCE=false."
            )

    client_spec_trimmed = False
    original_operation_count: int | None = None
    trimmed_operation_count: int | None = None
    client_trim_note: str | None = None
    if tool_filter is not None and settings.create_auto_trim_on_tool_filter:
        spec_bytes, content_type, b0, b1, client_spec_trimmed, client_trim_note = (
            _maybe_client_trim_spec_for_upload(
                spec_bytes,
                content_type,
                tool_filter,
                platform_max=settings.platform_max_openapi_operations,
                auto_trim=True,
            )
        )
        if client_spec_trimmed:
            original_operation_count = b0
            trimmed_operation_count = b1

    if base_url is None:
        base_url = _infer_base_url(spec_bytes) or ""
    if not base_url:
        raise SpecDownloadError(
            "Could not determine `base_url` from spec; please pass it explicitly."
        )

    if auth_config is None:
        auth_config = AuthConfig(provider="passthrough")

    payload = OpenAPIServerCreate(
        name=name,
        description=description,
        base_url=base_url,
        tags=tags or [],
        admins=admins or [],
        viewers=viewers or [],
        required_scopes=required_scopes or [],
        icon_url=icon_url,
        auth_config=auth_config,
        tool_filter=tool_filter,
    )

    owns_client = client is None
    client = client or ToolsAPIClient(settings=settings)
    start = time.monotonic()
    try:
        server = await client.create_server(token, payload)

        if not server.spec_upload_url:
            raise TrimbleToolsAPIError(
                500,
                "Platform did not return a `spec_upload_url` on create.",
                body=server.model_dump(),
            )

        await client.upload_spec_to_sas_url(
            server.spec_upload_url, spec_bytes, content_type=content_type
        )

        if wait_for_parse:
            server = await _poll_parse_status(client, token, server.id, settings)
    finally:
        if owns_client:
            await client.aclose()

    waited = time.monotonic() - start
    gateway_url = server.gateway_url or _compose_gateway_url(settings, server)
    return CreateResult(
        server=server,
        parse_status=server.parse_status or "unknown",
        gateway_url=gateway_url,
        mcp_server_url=gateway_url,
        tool_count=server.tool_count or len(server.parsed_tools),
        waited_seconds=waited,
        spec_bytes=len(spec_bytes),
        spec_content_type=content_type,
        client_spec_trimmed=client_spec_trimmed,
        original_operation_count=original_operation_count,
        trimmed_operation_count=trimmed_operation_count,
        client_trim_note=client_trim_note,
    )


async def _poll_parse_status(
    client: ToolsAPIClient,
    token: str,
    server_id: str,
    settings: Settings,
) -> OpenAPIServer:
    deadline = time.monotonic() + settings.parse_poll_timeout_seconds
    interval = max(0.25, settings.parse_poll_interval_seconds)
    last: OpenAPIServer | None = None

    while time.monotonic() < deadline:
        last = await client.get_server(token, server_id)
        status = (last.parse_status or "").lower()
        if status in _TERMINAL_PARSE_STATES:
            return last
        if status and status not in _PENDING_PARSE_STATES:
            # Unknown but non-pending status: assume terminal to avoid infinite waits.
            return last
        await asyncio.sleep(interval)

    raise ParseTimeoutError(
        f"Parse did not complete within {settings.parse_poll_timeout_seconds}s; "
        f"last status = {last.parse_status if last else 'unknown'}"
    )


def _infer_base_url(spec_bytes: bytes) -> str | None:
    """Pull the first ``servers[0].url`` out of a spec document."""
    text = spec_bytes.decode("utf-8", errors="replace")
    parsed: object
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError:
            return None
    if not isinstance(parsed, dict):
        return None
    servers = parsed.get("servers")
    if isinstance(servers, list) and servers:
        first = servers[0]
        if isinstance(first, dict) and isinstance(first.get("url"), str):
            return first["url"].strip() or None
    host = parsed.get("host")
    if isinstance(host, str) and host:
        scheme_list = parsed.get("schemes")
        scheme = "https"
        if isinstance(scheme_list, list) and scheme_list:
            scheme = str(scheme_list[0])
        base_path = parsed.get("basePath") or ""
        return f"{scheme}://{host}{base_path}".rstrip("/")
    return None


def _compose_gateway_url(settings: Settings, server: OpenAPIServer) -> str | None:
    """Fallback gateway URL built from base + namespace/path when the API omits it."""
    if not server.path:
        return None
    base = settings.trimble_tools_api_base_url.rstrip("/")
    path = server.path if server.path.startswith("/") else f"/{server.path}"
    return f"{base}{path}"
