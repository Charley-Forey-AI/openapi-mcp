"""Pydantic models mirroring the Agentic AI Platform OpenAPI server schemas.

We keep these permissive (`extra="allow"`) so schema additions on the server
side don't break the MCP. Only the fields we actively read or write are
explicitly declared.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: Literal["passthrough", "token-vault", "static"] = "passthrough"
    credential_ref: str | None = None
    static_headers: dict[str, str] | None = None
    inject_header: str = "Authorization"
    header_format: str = "Bearer {token}"


class ToolOverrides(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] | None = None


class ToolConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    allowed: bool = True
    overrides: ToolOverrides | None = None


class ToolDefaults(BaseModel):
    model_config = ConfigDict(extra="allow")

    allowed: bool = True


class ToolFilter(BaseModel):
    model_config = ConfigDict(extra="allow")

    include_tags: list[str] | None = None
    exclude_tags: list[str] | None = None
    include_operations: list[str] | None = None
    exclude_operations: list[str] | None = None
    include_paths: list[str] | None = None
    exclude_paths: list[str] | None = None


class RouteMapConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    methods: list[str] | None = None
    pattern: str | None = None
    tags: list[str] = Field(default_factory=list)
    mcp_type: Literal["tool", "resource", "resource_template", "exclude"] = "tool"


class OpenAPIServerCreate(BaseModel):
    """Metadata-only payload for POST /v1/openapi-servers."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(..., min_length=1, max_length=256)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    base_url: str
    auth_config: AuthConfig | None = None
    admins: list[str] = Field(default_factory=list)
    viewers: list[str] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=list)
    icon_url: str | None = None


class OpenAPIServerUpdate(BaseModel):
    """Partial update payload for PATCH /v1/openapi-servers/{id}."""

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    base_url: str | None = None
    auth_config: AuthConfig | None = None
    admins: list[str] | None = None
    viewers: list[str] | None = None
    required_scopes: list[str] | None = None
    icon_url: str | None = None
    tool_defaults: ToolDefaults | None = None
    tools: list[ToolConfig] | None = None
    tool_filter: ToolFilter | None = None
    route_maps: list[RouteMapConfig] | None = None
    enabled: bool | None = None
    status: Literal["registered", "deprecated", "deleted"] | None = None


class ParsedTool(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str = ""
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class OpenAPIServer(BaseModel):
    """Response representation of a registered OpenAPI server."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    description: str = ""
    base_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    path: str | None = None
    namespace: str | None = None
    status: str | None = None
    routing_status: str | None = None
    parse_status: str | None = None
    parse_error: str | None = None
    enabled: bool | None = None
    version: int | None = None
    tool_count: int | None = None
    spec_hash: str | None = None
    spec_version: str | None = None
    parsed_tools: list[ParsedTool] = Field(default_factory=list)
    gateway_url: str | None = None
    spec_upload_url: str | None = None


class OpenAPIServerList(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[OpenAPIServer] = Field(default_factory=list)
    count: int = 0
    total: int = 0


class ParsedToolList(BaseModel):
    model_config = ConfigDict(extra="allow")

    server_id: str
    tools: list[ParsedTool] = Field(default_factory=list)
    count: int = 0
