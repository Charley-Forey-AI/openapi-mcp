"""HTTP client for the Trimble Agentic AI Platform Tools API.

Thin, typed async wrapper around the experimental `/v1/openapi-servers/*`
endpoints. Each method takes an already-resolved bearer ``token`` (callers
get it from :class:`openapi_mcp_builder.auth.TokenProvider`), which keeps the
client stateless and safe to share across requests with different identities.
"""

from __future__ import annotations

from typing import Any

import httpx

from openapi_mcp_builder.config import Settings, get_settings
from openapi_mcp_builder.models import (
    OpenAPIServer,
    OpenAPIServerCreate,
    OpenAPIServerList,
    OpenAPIServerUpdate,
    ParsedToolList,
)


class TrimbleToolsAPIError(RuntimeError):
    """Raised when the Tools API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str, body: Any = None) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.body = body


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        body = resp.json()
        message = body.get("detail") or body.get("message") or resp.text
    except Exception:
        body = resp.text
        message = resp.text
    raise TrimbleToolsAPIError(resp.status_code, message, body)


class ToolsAPIClient:
    """Async client for the Agentic AI Platform Tools API."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=self._settings.trimble_tools_api_base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> ToolsAPIClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    @staticmethod
    def _auth_headers(token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    async def create_server(
        self, token: str, payload: OpenAPIServerCreate
    ) -> OpenAPIServer:
        resp = await self._http.post(
            "/v1/openapi-servers",
            headers=self._auth_headers(token, {"Content-Type": "application/json"}),
            json=payload.model_dump(exclude_none=True, mode="json"),
        )
        _raise_for_status(resp)
        return OpenAPIServer.model_validate(resp.json())

    async def list_servers(
        self,
        token: str,
        q: str | None = None,
        search: str | None = None,
        path: str | None = None,
    ) -> OpenAPIServerList:
        params = {k: v for k, v in {"q": q, "search": search, "path": path}.items() if v}
        resp = await self._http.get(
            "/v1/openapi-servers",
            headers=self._auth_headers(token),
            params=params,
        )
        _raise_for_status(resp)
        return OpenAPIServerList.model_validate(resp.json())

    async def get_server(self, token: str, server_id: str) -> OpenAPIServer:
        resp = await self._http.get(
            f"/v1/openapi-servers/{server_id}",
            headers=self._auth_headers(token),
        )
        _raise_for_status(resp)
        return OpenAPIServer.model_validate(resp.json())

    async def update_server(
        self,
        token: str,
        server_id: str,
        payload: OpenAPIServerUpdate,
        reupload: bool = False,
        if_match: str | None = None,
    ) -> OpenAPIServer:
        headers = self._auth_headers(
            token, {"Content-Type": "application/merge-patch+json"}
        )
        if if_match:
            headers["If-Match"] = if_match
        resp = await self._http.patch(
            f"/v1/openapi-servers/{server_id}",
            headers=headers,
            params={"reupload": "true" if reupload else "false"},
            json=payload.model_dump(exclude_none=True, mode="json"),
        )
        _raise_for_status(resp)
        return OpenAPIServer.model_validate(resp.json())

    async def delete_server(
        self, token: str, server_id: str, if_match: str | None = None
    ) -> None:
        headers = self._auth_headers(token)
        if if_match:
            headers["If-Match"] = if_match
        resp = await self._http.delete(
            f"/v1/openapi-servers/{server_id}", headers=headers
        )
        _raise_for_status(resp)

    async def refresh_server(
        self, token: str, server_id: str, force: bool = False
    ) -> OpenAPIServer:
        resp = await self._http.post(
            f"/v1/openapi-servers/{server_id}/refresh",
            headers=self._auth_headers(token),
            params={"force": "true" if force else "false"},
        )
        _raise_for_status(resp)
        return OpenAPIServer.model_validate(resp.json())

    async def list_parsed_tools(self, token: str, server_id: str) -> ParsedToolList:
        resp = await self._http.get(
            f"/v1/openapi-servers/{server_id}/tools",
            headers=self._auth_headers(token),
        )
        _raise_for_status(resp)
        return ParsedToolList.model_validate(resp.json())

    async def upload_spec_to_sas_url(
        self,
        spec_upload_url: str,
        spec_bytes: bytes,
        content_type: str = "application/json",
    ) -> None:
        """PUT the raw spec bytes to an Azure Blob SAS URL.

        Azure requires the ``x-ms-blob-type: BlockBlob`` header on PUT.
        """
        headers = {
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": content_type,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            resp = await client.put(spec_upload_url, content=spec_bytes, headers=headers)
        if resp.status_code not in (200, 201):
            raise TrimbleToolsAPIError(
                resp.status_code,
                f"SAS upload failed: {resp.text[:500]}",
                resp.text,
            )
