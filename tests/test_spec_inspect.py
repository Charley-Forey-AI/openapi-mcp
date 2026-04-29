"""Unit tests for OpenAPI spec inspection and tool_filter helpers."""

from __future__ import annotations

import json

import pytest

from openapi_mcp_builder.spec_inspect import (
    build_summary,
    count_operations_matching_any_tag,
    enumerate_operations,
    parse_openapi_spec_bytes,
    search_openapi_operations,
    tool_filter_from_tags,
)


def test_enumerate_and_tags():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/a": {
                "get": {"tags": ["Pet"], "operationId": "listA"},
                "post": {
                    "tags": ["Store", "Pet"],
                    "responses": {"200": {"description": "ok"}},
                },
            },
        },
    }
    ops = enumerate_operations(spec)
    assert len(ops) == 2
    assert ops[0]["operation_key"] == "GET /a"
    assert ops[0]["tags"] == ["Pet"]
    post = [o for o in ops if o["method"] == "POST"][0]
    assert set(post["tags"]) == {"Store", "Pet"}


def test_count_matching_tags():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {"/x": {"get": {"tags": ["A"]}}, "/y": {"get": {"tags": ["B"]}}},
    }
    ops = enumerate_operations(spec)
    assert count_operations_matching_any_tag(ops, ["A"]) == 1
    assert count_operations_matching_any_tag(ops, ["A", "B"]) == 2
    assert count_operations_matching_any_tag(ops, ["Z"]) == 0


def test_build_summary_exceeds_limit():
    paths = {
        f"/p{i}": {
            "get": {"tags": ["G"], "responses": {"200": {"description": "x"}}}
        }
        for i in range(60)
    }
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": paths,
    }
    ops = enumerate_operations(spec)
    s = build_summary(
        spec,
        operations=ops,
        platform_max_operations=50,
        max_sample_ops_per_tag=2,
    )
    assert s["total_operations"] == 60
    assert s["exceeds_platform_limit"] is True


def test_tool_filter_from_tags():
    t = tool_filter_from_tags(["RFI", "Docs"])
    assert t == {"include_tags": ["RFI", "Docs"]}


def test_parse_bytes_json():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
    }
    b = json.dumps(spec).encode()
    out = parse_openapi_spec_bytes(b)
    assert out["openapi"] == "3.0.0"


def test_parse_rejects_non_openapi():
    with pytest.raises(ValueError):
        parse_openapi_spec_bytes(b"{} ")


def test_search_openapi_operations_ranks_path_and_op_id():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/v1/dailyLog": {
                "get": {
                    "operationId": "getDaily",
                    "tags": ["DailyLog"],
                    "responses": {"200": {"description": "x"}},
                }
            },
            "/b": {"get": {"tags": ["Z"], "responses": {"200": {"description": "x"}}}},
        },
    }
    r = search_openapi_operations(spec, "daily", limit=10)
    assert len(r) == 1
    assert "dailyLog" in r[0]["path"]


def test_next_steps_in_summary():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {"/x": {"get": {}}},
    }
    s = build_summary(
        spec,
        platform_max_operations=50,
    )
    assert "next_steps" in s
    assert any("export_trimmed" in step for step in s["next_steps"])
    assert "external_ref_count" in s
    assert s["external_ref_count"] == 0
