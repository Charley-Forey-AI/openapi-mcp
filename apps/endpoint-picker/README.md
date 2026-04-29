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

Output in `dist/`. The build uses `base: /endpoint-picker/` so assets load when the app is served at **`https://<host>/endpoint-picker/`** (not at domain root).

## Deploy at `/endpoint-picker` on the same host (nginx)

1. Copy the built site next to your web root (example: files under `/var/www/endpoint-picker/`):

   ```bash
   sudo mkdir -p /var/www/endpoint-picker
   sudo rsync -a --delete dist/ /var/www/endpoint-picker/
   ```

2. Add **one** `location` block to the `server` that already listens on your public IP (or hostname). Use `root` + `try_files` (works reliably for SPAs; `alias` + `try_files` is easy to get wrong):

   ```nginx
   location /endpoint-picker/ {
       root /var/www;
       try_files $uri $uri/ /endpoint-picker/index.html;
   }
   ```

3. Test and reload:

   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

4. Open: `https://<your-ip-or-host>/endpoint-picker/` (trailing slash is fine).

**TLS:** if you only have HTTP on the IP, use `http://` until you add certificates. Same `location` applies inside the `server { listen 80; ... }` block.

**Rollback:** remove the `location` block, `sudo nginx -t && sudo systemctl reload nginx`, and delete `/var/www/endpoint-picker` if you want the files gone.
