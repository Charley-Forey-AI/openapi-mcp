# Trimble Agentic AI Platform (external follow-up)

This MCP builder talks to the Agentic AI Platform **Tools API** (`/v1/openapi-servers/*`). Some behaviors are decided by the platform, not this repository.

## Operation count vs `tool_filter`

**Question for Product/Platform:** When the executor enforces a cap (e.g. `OPENAPI_MAX_SPEC_OPERATIONS` / ~50 operations), does that check use:

- the number of operations in the **uploaded** OpenAPI document, or
- the number of operations **after** `tool_filter` is applied?

If the check runs on the full document first, **trimming the spec** (fewer `paths` operations) is required to pass the cap; `tool_filter` alone may only control which operations become MCP tools after a successful parse.

This repo implements that distinction in MCP `instructions`, README, and optional local **pre-flight** (`CREATE_PREFLIGHT_ENFORCE` + `acknowledge_openapi_operation_limit` on create).

## Authoritative `tool_filter` schema

**Question for Product/Platform:** Where is the canonical JSON schema for `tool_filter` (field names, regex dialect for `include_paths` / `exclude_paths`)?

The client model in this repo uses: `include_tags`, `exclude_tags`, `include_operations`, `exclude_operations`, `include_paths`, `exclude_paths` (see `src/openapi_mcp_builder/models.py`). Unknown fields may be accepted with `extra="allow"` but not applied server-side. Use `validate_openapi_tool_filter` before PATCH to catch typos (e.g. `path_pattern` instead of `include_paths`).

## External references in the uploaded file

If the OpenAPI document uses `$ref` values that are **not** local JSON Pointers (`#/components/...`)
—for example `https://...` or `./schemas/Foo.yaml`—the **Tools API / executor** may still try to
parse the document you upload. This repo only **detects** those references (see
`external_ref_*` on analyze and optional `warnings` on `export_trimmed_openapi_spec`) and does
**not** bundle or inline external files. Resolving them is a **client-side** or **build-time**
step (e.g. `redocly bundle`).

## Related documentation

- Project README: [../README.md](../README.md) — “Large specs”, agent checklist, and tool table.
