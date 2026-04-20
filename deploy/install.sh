#!/usr/bin/env bash
# Idempotent installer for openapi-mcp-builder on an Ubuntu host where
# multiple MCPs live under /mcp/<name> and are fronted by a single nginx
# `server { ... }` block.
#
# Run as root (or with sudo). Re-running is safe.
#
#   sudo bash deploy/install.sh
#
# This script will:
#   1. Create the `mcp` system user + /mcp if missing.
#   2. Rsync the repo into /mcp/openapi-mcp.
#   3. Create a Python 3.11+ venv and `pip install -e .`.
#   4. Install and enable the systemd unit.
#   5. Install the nginx location snippet, test, and reload.
#
# It will NOT:
#   * Touch other /mcp/<sibling> folders.
#   * Overwrite an existing /mcp/openapi-mcp/.env.
#   * Replace your top-level nginx server block; it only drops a
#     per-MCP snippet into /etc/nginx/snippets/openapi-mcp.conf and
#     expects the main server block to `include snippets/openapi-mcp.conf;`.

set -euo pipefail

APP_NAME="openapi-mcp"
APP_DIR="/mcp/${APP_NAME}"
APP_USER="mcp"
APP_GROUP="mcp"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SOURCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_FILE="${SOURCE_DIR}/deploy/systemd/openapi-mcp.service"
NGINX_SNIPPET_SRC="${SOURCE_DIR}/deploy/nginx/openapi-mcp.conf"
NGINX_SNIPPET_DST="/etc/nginx/snippets/openapi-mcp.conf"

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "ERROR: run this script with sudo/root." >&2
        exit 1
    fi
}

log() { printf '\n\033[1;36m[install]\033[0m %s\n' "$*"; }

ensure_user() {
    if ! id "${APP_USER}" &>/dev/null; then
        log "Creating system user ${APP_USER}"
        useradd --system --home /mcp --shell /usr/sbin/nologin \
            --user-group "${APP_USER}"
    fi
}

ensure_dirs() {
    install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0755 /mcp
    install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0755 "${APP_DIR}"
}

sync_code() {
    log "Syncing source into ${APP_DIR}"
    rsync -a --delete \
        --exclude '.git' \
        --exclude '.venv' \
        --exclude '__pycache__' \
        --exclude '.pytest_cache' \
        --exclude '.ruff_cache' \
        --exclude '.env' \
        --exclude 'dist' \
        --exclude 'build' \
        "${SOURCE_DIR}/" "${APP_DIR}/"
    chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}"
}

ensure_env_file() {
    if [[ ! -f "${APP_DIR}/.env" ]]; then
        log "Seeding ${APP_DIR}/.env from .env.example"
        install -o "${APP_USER}" -g "${APP_GROUP}" -m 0600 \
            "${APP_DIR}/.env.example" "${APP_DIR}/.env"
        echo "    -> EDIT ${APP_DIR}/.env before starting the service." >&2
    else
        log "Preserving existing ${APP_DIR}/.env"
    fi
}

build_venv() {
    log "Building Python venv at ${APP_DIR}/.venv"
    sudo -u "${APP_USER}" "${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
    sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
    sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install --quiet -e "${APP_DIR}"
}

install_service() {
    log "Installing systemd unit"
    install -m 0644 "${SERVICE_FILE}" /etc/systemd/system/openapi-mcp.service
    systemctl daemon-reload
    systemctl enable openapi-mcp.service
}

install_nginx_snippet() {
    log "Installing nginx snippet at ${NGINX_SNIPPET_DST}"
    install -d -m 0755 /etc/nginx/snippets
    install -m 0644 "${NGINX_SNIPPET_SRC}" "${NGINX_SNIPPET_DST}"

    cat <<EOF

>>> NGINX INCLUDE <<<
Add ONE line inside the server { ... } block that already serves /mcp/*:

    include snippets/openapi-mcp.conf;

Then:
    sudo nginx -t && sudo systemctl reload nginx

EOF
}

restart_service() {
    log "Restarting openapi-mcp.service"
    systemctl restart openapi-mcp.service
    systemctl --no-pager --full status openapi-mcp.service | head -n 20 || true
}

main() {
    require_root
    ensure_user
    ensure_dirs
    sync_code
    ensure_env_file
    build_venv
    install_service
    install_nginx_snippet
    restart_service
    log "Done. Public URL: https://<host>/mcp/openapi-mcp/mcp"
}

main "$@"
