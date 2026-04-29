# OpenAPI endpoint picker (MCP App)

React + [`@modelcontextprotocol/ext-apps`](https://www.npmjs.com/package/@modelcontextprotocol/ext-apps) UI bundled as a **single HTML file** for the `ui://openapi-mcp-builder/endpoint-picker.html` resource consumed by **`pick_openapi_endpoints`** in `openapi-mcp-builder`.

## Build

From this directory:

```bash
npm install
npm run build
```

`vite-plugin-singlefile` emits `dist/index.html`; a Vite `closeBundle` hook copies it to:

`../../src/openapi_mcp_builder/static/endpoint_picker_mcp.html`

Commit that file when you change the UI so Python wheels ship the updated bundle.

## Dev

```bash
npm run dev
```

Note: `useApp` expects a **host iframe** (postMessage). Local Vite alone will not fully simulate MCP; use an MCP Apps–capable client against the running MCP server for end-to-end testing.
