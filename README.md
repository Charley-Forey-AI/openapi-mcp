# openapi-mcp-builder

An MCP server that turns any OpenAPI (or Swagger) spec URL into a hosted MCP
server on the **Trimble Agentic AI Platform**, and hands the caller back the
ready-to-use MCP gateway URL.

Under the hood it drives the platform's experimental `/v1/openapi-servers/*`
endpoints:

| Tool                                    | Endpoint                                          |
| --------------------------------------- | ------------------------------------------------- |
| `create_mcp_from_openapi_url`           | `POST /v1/openapi-servers` + SAS PUT + poll       |
| `list_openapi_mcp_servers`              | `GET  /v1/openapi-servers`                        |
| `get_openapi_mcp_server`                | `GET  /v1/openapi-servers/{id}`                   |
| `update_openapi_mcp_server`             | `PATCH /v1/openapi-servers/{id}`                  |
| `delete_openapi_mcp_server`             | `DELETE /v1/openapi-servers/{id}`                 |
| `refresh_openapi_mcp_server`            | `POST /v1/openapi-servers/{id}/refresh`           |
| `list_openapi_mcp_server_tools`         | `GET  /v1/openapi-servers/{id}/tools`             |
| `reupload_openapi_spec_from_url`        | `PATCH ?reupload=true` + SAS PUT + poll           |

## How the spec-URL workflow works

```
user -> MCP client (e.g. Trimble Agent Studio)
              |   tool call: create_mcp_from_openapi_url(spec_url, name, ...)
              v
   openapi-mcp-builder
     1. GET  spec_url                         # validate JSON / YAML
     2. POST /v1/openapi-servers              # metadata only -> spec_upload_url
     3. PUT  <spec_upload_url>                # Azure Blob SAS, x-ms-blob-type: BlockBlob
     4. GET  /v1/openapi-servers/{id}  (poll) # until parse_status terminal
     5. return { gateway_url, tool_count, parse_status, ... }
```

The `gateway_url` in the final response is the MCP URL the agent connects to.

## Authentication (Trimble ID OBO)

When deployed inside **Trimble Agent Studio**, every tool call carries the
signed-in user's on-behalf-of TID token as `Authorization: Bearer <token>`.
`openapi-mcp-builder` extracts that header and forwards it to the Agentic AI
Platform, so every action (create, list, patch, delete) runs as the end user —
no static service credentials required.

Three modes are supported, evaluated per request:

1. **OBO passthrough** — use the caller's `Authorization` header (production).
2. **Static token** — `TRIMBLE_ACCESS_TOKEN` env var (local dev / stdio).
3. **Client credentials** — `TRIMBLE_CLIENT_ID` + `TRIMBLE_CLIENT_SECRET`
   mint a token against `TRIMBLE_TOKEN_URL` (service-to-service).

The generated OpenAPI MCP server itself defaults to `auth_config.provider =
"passthrough"`, so the upstream REST API receives the same end-user token at
tool-invocation time unless you override it.

## Install

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env   # then edit
```

Requires Python 3.10+.

## Run

### Stdio (Claude Desktop, local MCP clients)

```bash
MCP_TRANSPORT=stdio openapi-mcp-builder
# or
MCP_TRANSPORT=stdio python -m openapi_mcp_builder
```

Example Claude Desktop / Cursor MCP config:

```json
{
  "mcpServers": {
    "openapi-mcp-builder": {
      "command": "openapi-mcp-builder",
      "env": {
        "MCP_TRANSPORT": "stdio",
        "TRIMBLE_ENV": "dev",
        "TRIMBLE_ACCESS_TOKEN": "eyJhbGciOi..."
      }
    }
  }
}
```

### HTTP (Trimble Agent Studio, remote MCP hosts) — default

```bash
openapi-mcp-builder   # listens on 0.0.0.0:8754 with MCP_TRANSPORT=http
```

Agent Studio should be configured to send `Authorization: Bearer <OBO-token>`
on every MCP request. Leave `TRIMBLE_ACCESS_TOKEN` empty so the server
requires the OBO header.

### Environment selector

`TRIMBLE_ENV` picks the Tools API base URL:

| `TRIMBLE_ENV` | Base URL                              |
| ------------- | ------------------------------------- |
| `dev` (default) | `https://tools.dev.trimble-ai.com`  |
| `stage`       | `https://tools.stage.trimble-ai.com`  |
| `prod`        | `https://tools.ai.trimble.com`        |

Set `TRIMBLE_TOOLS_API_BASE_URL` to override explicitly.

## Example call

```jsonc
// tool: create_mcp_from_openapi_url
{
  "spec_url": "https://api.redocly.com/registry/bundle/hcss-64o/identity/v1/openapi.yaml?branch=main",
  "name": "hcss-identity",
  "description": "HCSS Identity API (get bearer tokens)",
  "tags": ["hcss", "identity"],
  "auth_provider": "passthrough"
}
```

Response:

```jsonc
{
  "ok": true,
  "id": "srv_01HQZ...",
  "name": "hcss-identity",
  "parse_status": "success",
  "tool_count": 3,
  "gateway_url": "https://tools.dev.trimble-ai.com/openapi/hcss-identity",
  "mcp_server_url": "https://tools.dev.trimble-ai.com/openapi/hcss-identity",
  "path": "/openapi/hcss-identity",
  "spec_bytes": 48321,
  "spec_content_type": "application/yaml",
  "waited_seconds": 4.12
}
```

Point your agent at `mcp_server_url` and you're done.

## Project layout

```
openapi-mcp/
├── pyproject.toml
├── README.md
├── .env.example
├── src/openapi_mcp_builder/
│   ├── __init__.py
│   ├── __main__.py        # CLI entrypoint / transport selection
│   ├── server.py          # FastMCP tools
│   ├── workflow.py        # download -> register -> upload -> poll
│   ├── client.py          # Async HTTP client for the Tools API
│   ├── auth.py            # OBO passthrough + fallbacks
│   ├── config.py          # Pydantic Settings
│   └── models.py          # Request / response schemas
└── tests/
    ├── conftest.py
    ├── test_auth.py
    └── test_workflow.py   # respx-mocked end-to-end flow
```

## Tests

```bash
pytest
```

## License

MIT
