# OpenAPI endpoint picker (static web UI)

Local tool to **select exact operations** and copy a JSON payload for
`export_trimmed_openapi_spec` / `include_operation_keys` in
[openapi-mcp-builder](../../README.md).

**No network calls** by default: paste a spec (JSON or YAML) in the browser.

## Run

```bash
cd apps/endpoint-picker
npm install
npm run dev
```

Open the URL Vite prints (usually `http://127.0.0.1:5173`).

## Build (static files)

```bash
npm run build
```

Output in `dist/` — host on any static file server.
