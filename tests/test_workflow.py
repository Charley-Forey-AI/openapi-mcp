"""Integration-style tests for the create-from-URL workflow."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from openapi_mcp_builder.client import ToolsAPIClient
from openapi_mcp_builder.config import Settings
from openapi_mcp_builder.models import ToolFilter
from openapi_mcp_builder.workflow import (
    SpecDownloadError,
    create_mcp_from_spec_url,
    download_spec,
)

SPEC = {
    "openapi": "3.0.1",
    "info": {"title": "Demo", "version": "1.0"},
    "servers": [{"url": "https://api.demo.example.com"}],
    "paths": {"/ping": {"get": {"responses": {"200": {"description": "ok"}}}}},
}


@pytest.fixture
def settings() -> Settings:
    return Settings(
        trimble_access_token="env-token",
        trimble_tools_api_base_url="https://tools.test.local",
        parse_poll_interval_seconds=0.01,
        parse_poll_timeout_seconds=2.0,
    )


async def test_download_spec_rejects_non_openapi_yaml():
    with respx.mock(assert_all_called=False) as router:
        router.get("https://example.com/bad.yaml").mock(
            return_value=httpx.Response(200, text="just: a random mapping\n")
        )
        with pytest.raises(SpecDownloadError):
            await download_spec("https://example.com/bad.yaml", max_bytes=10_000)


async def test_download_spec_accepts_json():
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.com/spec.json").mock(
            return_value=httpx.Response(
                200,
                text=json.dumps(SPEC),
                headers={"content-type": "application/json"},
            )
        )
        body, ct = await download_spec("https://example.com/spec.json", max_bytes=100_000)
    assert ct == "application/json"
    assert json.loads(body)["openapi"] == "3.0.1"


async def test_create_from_spec_url_full_flow(settings: Settings):
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.com/spec.json").mock(
            return_value=httpx.Response(200, text=json.dumps(SPEC))
        )
        router.post("https://tools.test.local/v1/openapi-servers").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": "srv_123",
                    "name": "demo",
                    "base_url": "https://api.demo.example.com",
                    "parse_status": "pending",
                    "spec_upload_url": "https://blob.test/sas?sig=abc",
                    "path": "/openapi/demo",
                    "namespace": "openapi",
                },
            )
        )
        router.put("https://blob.test/sas").mock(return_value=httpx.Response(201))
        get_route = router.get("https://tools.test.local/v1/openapi-servers/srv_123")
        get_route.mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "id": "srv_123",
                        "name": "demo",
                        "parse_status": "parsing",
                        "path": "/openapi/demo",
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "id": "srv_123",
                        "name": "demo",
                        "parse_status": "success",
                        "path": "/openapi/demo",
                        "gateway_url": "https://tools.test.local/openapi/demo",
                        "tool_count": 1,
                    },
                ),
            ]
        )

        async with ToolsAPIClient(settings=settings) as client:
            result = await create_mcp_from_spec_url(
                token="env-token",
                spec_url="https://example.com/spec.json",
                name="demo",
                settings=settings,
                client=client,
            )

    assert result.parse_status == "success"
    assert result.mcp_server_url == "https://tools.test.local/openapi/demo"
    assert result.tool_count == 1
    assert result.server.id == "srv_123"


async def test_create_preflight_blocks_when_enforced_and_over_limit(settings: Settings):
    s2 = settings.model_copy(
        update={
            "create_preflight_enforce": True,
            "platform_max_openapi_operations": 1,
        }
    )
    big_spec = {
        "openapi": "3.0.0",
        "info": {"title": "B", "version": "1"},
        "servers": [{"url": "https://api.demo.example.com"}],
        "paths": {
            f"/p{i}": {
                "get": {"responses": {"200": {"description": "ok"}}},
            }
            for i in range(3)
        },
    }
    with respx.mock(assert_all_called=False) as router:
        router.get("https://example.com/big.json").mock(
            return_value=httpx.Response(200, text=json.dumps(big_spec))
        )

        def _post_should_not_run(_: httpx.Request) -> httpx.Response:
            raise AssertionError("pre-flight should stop before register")

        router.post("https://tools.test.local/v1/openapi-servers").mock(
            side_effect=_post_should_not_run
        )

        async with ToolsAPIClient(settings=s2) as client:
            with pytest.raises(SpecDownloadError) as excinfo:
                await create_mcp_from_spec_url(
                    token="env-token",
                    spec_url="https://example.com/big.json",
                    name="demo",
                    settings=s2,
                    client=client,
                )
    assert "Pre-flight" in str(excinfo.value)


async def test_create_preflight_ack_allows_create(settings: Settings):
    s2 = settings.model_copy(
        update={
            "create_preflight_enforce": True,
            "platform_max_openapi_operations": 1,
        }
    )
    big_spec = {
        "openapi": "3.0.0",
        "info": {"title": "B", "version": "1"},
        "servers": [{"url": "https://api.demo.example.com"}],
        "paths": {
            f"/p{i}": {
                "get": {"responses": {"200": {"description": "ok"}}},
            }
            for i in range(3)
        },
    }
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.com/big2.json").mock(
            return_value=httpx.Response(200, text=json.dumps(big_spec))
        )
        router.post("https://tools.test.local/v1/openapi-servers").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": "srv_big",
                    "name": "demo",
                    "base_url": "https://api.demo.example.com",
                    "parse_status": "success",
                    "path": "/openapi/demo",
                    "namespace": "openapi",
                    "spec_upload_url": "https://blob.test/sas2",
                },
            )
        )
        router.put("https://blob.test/sas2").mock(return_value=httpx.Response(201))

        async with ToolsAPIClient(settings=s2) as client:
            result = await create_mcp_from_spec_url(
                token="env-token",
                spec_url="https://example.com/big2.json",
                name="demo",
                settings=s2,
                client=client,
                acknowledge_openapi_operation_limit=True,
                wait_for_parse=False,
            )

    assert result.server.id == "srv_big"


async def test_create_preflight_skips_when_tool_filter_set(settings: Settings):
    s2 = settings.model_copy(
        update={
            "create_preflight_enforce": True,
            "platform_max_openapi_operations": 1,
        }
    )
    big_spec = {
        "openapi": "3.0.0",
        "info": {"title": "B", "version": "1"},
        "servers": [{"url": "https://api.demo.example.com"}],
        "paths": {
            f"/p{i}": {
                "get": {"responses": {"200": {"description": "ok"}}},
            }
            for i in range(3)
        },
    }
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.com/tf.json").mock(
            return_value=httpx.Response(200, text=json.dumps(big_spec))
        )
        router.post("https://tools.test.local/v1/openapi-servers").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": "srv_tf",
                    "name": "demo",
                    "base_url": "https://api.demo.example.com",
                    "parse_status": "success",
                    "path": "/openapi/x",
                    "namespace": "openapi",
                    "spec_upload_url": "https://blob.test/sas3",
                },
            )
        )
        router.put("https://blob.test/sas3").mock(return_value=httpx.Response(201))

        async with ToolsAPIClient(settings=s2) as client:
            result = await create_mcp_from_spec_url(
                token="env-token",
                spec_url="https://example.com/tf.json",
                name="demo",
                settings=s2,
                client=client,
                tool_filter=ToolFilter(include_tags=["x"]),
                wait_for_parse=False,
            )

    assert result.server.id == "srv_tf"
