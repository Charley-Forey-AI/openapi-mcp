"""Trimble ID access-token resolution for outbound API calls.

Three supported modes, evaluated per-request in this order:

1. OBO passthrough: use the caller's `Authorization: Bearer <token>` header
   from the active MCP HTTP request. This is the expected production mode
   when the MCP is deployed inside Trimble Agent Studio, which attaches the
   signed-in user's on-behalf-of TID token to every tool call.
2. Static env-var token (`TRIMBLE_ACCESS_TOKEN`): useful for stdio / local
   development when no HTTP context is available.
3. Client credentials grant: if `TRIMBLE_CLIENT_ID` and
   `TRIMBLE_CLIENT_SECRET` are set, mint a token against
   `TRIMBLE_TOKEN_URL` and cache it until it nears expiry.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from openapi_mcp_builder.config import Settings, get_settings


class AuthError(RuntimeError):
    """Raised when no usable Trimble ID token can be resolved."""


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float  # unix seconds


class TokenProvider:
    """Resolves a bearer token for each outbound API call."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._cached: _CachedToken | None = None
        self._lock = asyncio.Lock()

    async def get_bearer_token(self, obo_header: str | None = None) -> str:
        """Return a raw bearer token string (no `Bearer ` prefix).

        ``obo_header`` is the value of the inbound ``Authorization`` header if
        present (case-insensitively). When provided and well-formed, it wins.
        """
        if obo_header:
            token = _strip_bearer(obo_header)
            if token:
                return token

        if self._settings.trimble_access_token:
            return self._settings.trimble_access_token

        if self._settings.has_client_credentials:
            return await self._client_credentials_token()

        raise AuthError(
            "No Trimble ID token available. Provide one of: "
            "(1) an `Authorization: Bearer <token>` header from the MCP client, "
            "(2) `TRIMBLE_ACCESS_TOKEN` env var, or "
            "(3) `TRIMBLE_CLIENT_ID` + `TRIMBLE_CLIENT_SECRET` env vars."
        )

    async def _client_credentials_token(self) -> str:
        now = time.time()
        if self._cached and self._cached.expires_at - 30 > now:
            return self._cached.access_token

        async with self._lock:
            now = time.time()
            if self._cached and self._cached.expires_at - 30 > now:
                return self._cached.access_token

            data: dict[str, str] = {
                "grant_type": "client_credentials",
                "client_id": self._settings.trimble_client_id or "",
                "client_secret": self._settings.trimble_client_secret or "",
            }
            if self._settings.trimble_scopes:
                data["scope"] = self._settings.trimble_scopes

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self._settings.trimble_token_url,
                    data=data,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
            if resp.status_code >= 400:
                raise AuthError(
                    f"Trimble ID client_credentials exchange failed: "
                    f"HTTP {resp.status_code} {resp.text}"
                )
            payload = resp.json()
            access_token = payload.get("access_token")
            expires_in = int(payload.get("expires_in", 3600))
            if not access_token:
                raise AuthError("Trimble ID response missing `access_token`.")

            self._cached = _CachedToken(
                access_token=access_token,
                expires_at=time.time() + expires_in,
            )
            return access_token


def _strip_bearer(raw: str) -> str | None:
    """Return the token portion of an `Authorization` header value."""
    raw = raw.strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower == "bearer":
        return None
    if lower.startswith("bearer "):
        return raw[7:].strip() or None
    # Already just the token.
    return raw


def extract_obo_header() -> str | None:
    """Extract the caller's Authorization header from the active HTTP request.

    Returns None when the MCP is running over stdio or the header is absent.
    """
    try:
        from fastmcp.server.dependencies import get_http_headers
    except ImportError:  # pragma: no cover - fastmcp always installed
        return None

    try:
        headers = get_http_headers()
    except Exception:
        return None

    if not headers:
        return None

    for key in ("authorization", "Authorization", "AUTHORIZATION"):
        value = headers.get(key)
        if value:
            return value
    return None
