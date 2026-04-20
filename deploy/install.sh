#!/usr/bin/env bash
# Idempotent installer for openapi-mcp-builder on an Ubuntu host where
# multiple MCPs live under /mcp/<name> and are fronted by a single nginx
# `server { ... }` block.
#
# Run as root (or with sudo). Re-running is safe.
#
#   sudo bash deploy/install.sh             # apply changes
#   sudo bash deploy/install.sh --dry-run   # preview changes, touch nothing
#
# Guarantees (things this script will NEVER do):
#   * Touch any sibling /mcp/<other-name>/ folder, file, or venv.
#   * Reload or restart any sibling systemd unit.
#   * Reload the running nginx process. It only drops a snippet at
#     /etc/nginx/snippets/openapi-mcp.conf. That snippet is inert until
#     *you* manually add `include snippets/openapi-mcp.conf;` to the
#     existing server block and run `nginx -t && systemctl reload nginx`.
#   * Overwrite an existing /mcp/openapi-mcp/.env.
#   * Chown or chmod /mcp itself if it already exists (preserves whatever
#     ownership your current setup relies on).
#
# What it WILL do (all scoped to new resources):
#   1. Create the `mcp` system user if missing.
#   2. Create /mcp and /mcp/openapi-mcp if missing.
#   3. Rsync the repo into /mcp/openapi-mcp (excludes .git, .venv, .env).
#   4. Create a Python venv at /mcp/openapi-mcp/.venv and `pip install -e .`.
#   5. Install /etc/systemd/system/openapi-mcp.service and enable it.
#   6. Install /etc/nginx/snippets/openapi-mcp.conf (inert until included).
#   7. Restart openapi-mcp.service only.

set -euo pipefail

APP_NAME="openapi-mcp"
APP_DIR="/mcp/${APP_NAME}"
APP_USER="mcp"
APP_GROUP="mcp"
APP_PORT="${APP_PORT:-8754}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SOURCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_FILE="${SOURCE_DIR}/deploy/systemd/openapi-mcp.service"
NGINX_SNIPPET_SRC="${SOURCE_DIR}/deploy/nginx/openapi-mcp.conf"
NGINX_SNIPPET_DST="/etc/nginx/snippets/openapi-mcp.conf"
SERVICE_DST="/etc/systemd/system/openapi-mcp.service"

DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run|-n) DRY_RUN=1 ;;
        -h|--help)
            sed -n '2,33p' "$0"
            exit 0
            ;;
        *) echo "Unknown flag: $arg" >&2; exit 2 ;;
    esac
done

log()  { printf '\n\033[1;36m[install]\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }

run() {
    # Execute a command, or print it prefixed with [dry-run].
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        printf '\033[1;35m[dry-run]\033[0m %s\n' "$*"
    else
        eval "$@"
    fi
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "ERROR: run this script with sudo/root." >&2
        exit 1
    fi
}

# ---------------------------------------------------------------- pre-flight #

preflight_report() {
    log "Pre-flight audit of /mcp and system state"

    if [[ -d /mcp ]]; then
        local owner group mode
        owner=$(stat -c '%U' /mcp)
        group=$(stat -c '%G' /mcp)
        mode=$(stat -c '%a' /mcp)
        echo "  /mcp exists (owner=${owner} group=${group} mode=${mode}) -- will NOT be modified."
        local siblings
        siblings=$(find /mcp -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null | sort || true)
        if [[ -n "${siblings}" ]]; then
            echo "  Existing /mcp/* entries (none will be touched):"
            printf '    - %s\n' ${siblings}
        fi
    else
        echo "  /mcp does NOT exist -- will be created as ${APP_USER}:${APP_GROUP} mode 0755."
    fi

    if id "${APP_USER}" &>/dev/null; then
        echo "  user ${APP_USER} already exists -- will NOT be modified."
    else
        echo "  user ${APP_USER} does not exist -- will be created (system, nologin)."
    fi

    if [[ -d "${APP_DIR}" ]]; then
        echo "  ${APP_DIR} exists -- contents will be rsynced (excluding .env, .venv, .git)."
    else
        echo "  ${APP_DIR} does NOT exist -- will be created."
    fi

    if [[ -f "${APP_DIR}/.env" ]]; then
        echo "  ${APP_DIR}/.env exists -- will be PRESERVED."
    else
        echo "  ${APP_DIR}/.env does not exist -- will be seeded from .env.example."
    fi

    if [[ -f "${SERVICE_DST}" ]]; then
        echo "  ${SERVICE_DST} exists -- will be replaced with the repo version."
    else
        echo "  ${SERVICE_DST} does not exist -- will be installed."
    fi

    if [[ -f "${NGINX_SNIPPET_DST}" ]]; then
        echo "  ${NGINX_SNIPPET_DST} exists -- will be replaced (content-identical if unchanged)."
    else
        echo "  ${NGINX_SNIPPET_DST} does not exist -- will be installed."
    fi

    # Port collision check (does not fail the install; just warns).
    if command -v ss &>/dev/null && ss -lntp 2>/dev/null | grep -q ":${APP_PORT}\b"; then
        warn "Port ${APP_PORT} is already listening on this host:"
        ss -lntp 2>/dev/null | grep ":${APP_PORT}\b" | sed 's/^/    /'
        warn "Our service will fail to bind. Change MCP_PORT in /mcp/openapi-mcp/.env and proxy_pass in the nginx snippet."
    fi

    # List sibling systemd units so the operator can see what exists.
    local other_units
    other_units=$(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
        | awk '{print $1}' | grep -E '^(mcp|openapi|accubid|n8n|arcgis)' | grep -v '^openapi-mcp\.service$' || true)
    if [[ -n "${other_units}" ]]; then
        echo "  Sibling MCP-looking systemd units (none will be touched):"
        printf '    - %s\n' ${other_units}
    fi
}

# ---------------------------------------------------------------- actions    #

ensure_user() {
    if id "${APP_USER}" &>/dev/null; then
        log "User ${APP_USER} already exists, skipping."
        return
    fi
    log "Creating system user ${APP_USER}"
    run "useradd --system --home /mcp --shell /usr/sbin/nologin --user-group '${APP_USER}'"
}

ensure_dirs() {
    if [[ ! -d /mcp ]]; then
        log "Creating /mcp (owner ${APP_USER}:${APP_GROUP}, mode 0755)"
        run "install -d -o '${APP_USER}' -g '${APP_GROUP}' -m 0755 /mcp"
    else
        log "/mcp already exists; leaving ownership and mode untouched."
    fi

    if [[ ! -d "${APP_DIR}" ]]; then
        log "Creating ${APP_DIR} (owner ${APP_USER}:${APP_GROUP}, mode 0755)"
        run "install -d -o '${APP_USER}' -g '${APP_GROUP}' -m 0755 '${APP_DIR}'"
    fi
}

sync_code() {
    log "Syncing source into ${APP_DIR} (rsync --delete scoped to ${APP_DIR} only)"
    run "rsync -a --delete \
        --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
        --exclude '.pytest_cache' --exclude '.ruff_cache' \
        --exclude '.env' --exclude 'dist' --exclude 'build' \
        '${SOURCE_DIR}/' '${APP_DIR}/'"
    run "chown -R '${APP_USER}:${APP_GROUP}' '${APP_DIR}'"
}

ensure_env_file() {
    if [[ -f "${APP_DIR}/.env" ]]; then
        log "Preserving existing ${APP_DIR}/.env"
        return
    fi
    log "Seeding ${APP_DIR}/.env from .env.example (mode 0600)"
    run "install -o '${APP_USER}' -g '${APP_GROUP}' -m 0600 \
        '${APP_DIR}/.env.example' '${APP_DIR}/.env'"
    echo "    -> EDIT ${APP_DIR}/.env before starting the service." >&2
}

build_venv() {
    log "Building Python venv at ${APP_DIR}/.venv"
    run "sudo -u '${APP_USER}' '${PYTHON_BIN}' -m venv '${APP_DIR}/.venv'"
    run "sudo -u '${APP_USER}' '${APP_DIR}/.venv/bin/pip' install --quiet --upgrade pip"
    run "sudo -u '${APP_USER}' '${APP_DIR}/.venv/bin/pip' install --quiet -e '${APP_DIR}'"
}

install_service() {
    log "Installing systemd unit at ${SERVICE_DST}"
    run "install -m 0644 '${SERVICE_FILE}' '${SERVICE_DST}'"
    # daemon-reload re-reads unit files; it does NOT restart any services.
    run "systemctl daemon-reload"
    run "systemctl enable openapi-mcp.service"
}

install_nginx_snippet() {
    log "Installing nginx snippet at ${NGINX_SNIPPET_DST} (INERT until you include it)"
    run "install -d -m 0755 /etc/nginx/snippets"
    run "install -m 0644 '${NGINX_SNIPPET_SRC}' '${NGINX_SNIPPET_DST}'"

    cat <<EOF

>>> NGINX INCLUDE (manual step) <<<
The snippet exists but nginx does not know about it yet. Your running
nginx config is unchanged. To activate, add ONE line inside the server
{ ... } block that already serves /mcp/*:

    include snippets/openapi-mcp.conf;

Then TEST FIRST, then reload:

    sudo nginx -t
    sudo systemctl reload nginx   # graceful reload, zero-downtime for siblings

EOF
}

restart_service() {
    log "Restarting openapi-mcp.service (sibling services untouched)"
    run "systemctl restart openapi-mcp.service"
    if [[ "${DRY_RUN}" -eq 0 ]]; then
        systemctl --no-pager --full status openapi-mcp.service | head -n 20 || true
    fi
}

main() {
    require_root
    preflight_report
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        log "DRY-RUN: showing planned actions only. Nothing will be changed."
    fi
    ensure_user
    ensure_dirs
    sync_code
    ensure_env_file
    build_venv
    install_service
    install_nginx_snippet
    restart_service
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        log "DRY-RUN complete. Re-run without --dry-run to apply."
    else
        log "Done. Public URL: https://<host>/mcp/openapi-mcp"
    fi
}

main "$@"
