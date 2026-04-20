# Deploy to the shared `/mcp` Ubuntu host

This directory ships everything needed to add `openapi-mcp-builder` alongside
your existing MCP servers (`/mcp/accubid`, `/mcp/n8n`, ...) **without
touching any sibling service**.

Final public URL: `https://<your-host>/mcp/openapi-mcp/mcp`

Topology after install:

```
/mcp
├── accubid/           (untouched)
├── n8n/               (untouched)
└── openapi-mcp/       <-- new
    ├── .env           (secrets, chmod 600, owned by mcp:mcp)
    ├── .venv/         (python venv created by install.sh)
    └── src/...        (the repo)

systemd:
    openapi-mcp.service -> /mcp/openapi-mcp/.venv/bin/openapi-mcp-builder

nginx:
    server { ... include snippets/openapi-mcp.conf; ... }
    location /mcp/openapi-mcp/ { proxy_pass http://127.0.0.1:8754; }
```

---

## Files in this folder

| File                            | Purpose                                              |
| ------------------------------- | ---------------------------------------------------- |
| `install.sh`                    | Idempotent installer. Re-run to redeploy.            |
| `systemd/openapi-mcp.service`   | Hardened systemd unit, runs as `mcp` user.           |
| `nginx/openapi-mcp.conf`        | Single `location /mcp/openapi-mcp/` block.           |

---

## One-time bootstrap on the Ubuntu server

All commands run on the server as a user with `sudo`.

### 1. Install prerequisites

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git rsync nginx
```

### 2. Clone the repo somewhere temporary

```bash
cd ~
git clone https://github.com/Charley-Forey-AI/openapi-mcp.git
cd openapi-mcp
```

### 3. Run the installer

```bash
sudo bash deploy/install.sh
```

The installer:
- Creates a locked-down `mcp` system user and `/mcp/` if absent.
- Rsyncs the repo to `/mcp/openapi-mcp/` (excluding `.git`, `.venv`, `.env`).
- Builds `/mcp/openapi-mcp/.venv` and `pip install -e .` as the `mcp` user.
- Installs `openapi-mcp.service` and enables it.
- Drops the nginx snippet at `/etc/nginx/snippets/openapi-mcp.conf`.
- Restarts the service.
- Prints the nginx one-liner you still need to add (see step 5).

### 4. Configure `/mcp/openapi-mcp/.env`

On the first run the installer seeds `.env` from `.env.example` (mode 0600,
owned by `mcp:mcp`). Edit it:

```bash
sudo -u mcp nano /mcp/openapi-mcp/.env
```

Recommended production values:

```ini
TRIMBLE_ENV=prod
MCP_TRANSPORT=http
MCP_HOST=127.0.0.1
MCP_PORT=8754
MCP_PATH=/mcp/openapi-mcp/mcp

# Leave token blank for OBO passthrough from Trimble Agent Studio.
TRIMBLE_ACCESS_TOKEN=
```

Then restart:

```bash
sudo systemctl restart openapi-mcp.service
sudo systemctl status  openapi-mcp.service
```

### 5. Wire up nginx (one line, one reload)

Edit the `server { ... }` block that already serves `/mcp/*` (usually in
`/etc/nginx/sites-available/mcp` or similar) and add **one** line:

```nginx
include snippets/openapi-mcp.conf;
```

Then test and reload:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Nothing else in your nginx config changes. `location /mcp/accubid/`,
`location /mcp/n8n/`, etc. remain intact because the snippet only declares
the single new `location /mcp/openapi-mcp/` block.

---

## Verify

```bash
# 1. Service is up
sudo systemctl is-active openapi-mcp.service
sudo journalctl -u openapi-mcp.service -n 50 --no-pager

# 2. Local endpoint responds (404 on GET is expected for Streamable HTTP;
#    the MCP URL only accepts POST with JSON-RPC. What matters is that
#    nginx can reach the upstream.)
curl -sS -I http://127.0.0.1:8754/mcp/openapi-mcp/mcp

# 3. Public endpoint through nginx
curl -sS -I https://<your-host>/mcp/openapi-mcp/mcp
```

Then point an MCP client (Trimble Agent Studio) at:

```
https://<your-host>/mcp/openapi-mcp/mcp
```

and call the `create_mcp_from_openapi_url` tool.

---

## Updating / redeploying

Pull new code and re-run the installer — it is idempotent:

```bash
cd ~/openapi-mcp && git pull
sudo bash deploy/install.sh
```

The installer preserves `/mcp/openapi-mcp/.env`, rebuilds the venv if
dependencies changed, and restarts the service.

---

## Rollback / removal

```bash
sudo systemctl disable --now openapi-mcp.service
sudo rm /etc/systemd/system/openapi-mcp.service
sudo rm /etc/nginx/snippets/openapi-mcp.conf
# Remove the `include snippets/openapi-mcp.conf;` line from the server block.
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl daemon-reload
sudo rm -rf /mcp/openapi-mcp
```

Siblings under `/mcp/*` are unaffected.

---

## Troubleshooting

| Symptom                                | Fix                                                                                   |
| -------------------------------------- | ------------------------------------------------------------------------------------- |
| `502 Bad Gateway` from nginx           | `sudo systemctl status openapi-mcp` — check the port and host in `.env`.              |
| 404 from the MCP client                | `MCP_PATH` in `.env` must be `/mcp/openapi-mcp/mcp` (matches the public URL).         |
| `AuthError` in logs                    | OBO header missing and no `TRIMBLE_ACCESS_TOKEN` / client credentials configured.     |
| SSE streams cut off at 60s             | Make sure `proxy_buffering off;` and the 1h timeouts from the snippet are applied.    |
| Port 8754 conflicts                    | Change `MCP_PORT` in `.env` and update `proxy_pass` in `snippets/openapi-mcp.conf`.   |
