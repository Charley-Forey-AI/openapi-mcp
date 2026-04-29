"""Tests for OpenAPI spec trimming (physical path removal)."""

from __future__ import annotations

import json

import pytest

from openapi_mcp_builder.spec_trim import (
    spec_json_dumps_min,
    trim_openapi_document,
)


def _demo_spec() -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/a/dailyLog": {
                "get": {
                    "tags": ["Daily"],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/X"},
                                }
                            },
                        }
                    },
                }
            },
            "/b/other": {
                "post": {"tags": ["Other"], "responses": {"200": {"description": "ok"}}}
            },
        },
        "components": {
            "schemas": {
                "X": {"type": "string"},
                "Junk": {"type": "object", "description": "unused; should be pruned"},
            }
        },
    }


def test_trim_by_path_substring():
    spec = _demo_spec()
    out, before, after = trim_openapi_document(
        spec,
        path_substrings=["dailyLog"],
    )
    assert before == 2
    assert after == 1
    assert "/b/other" not in out["paths"]
    assert "/a/dailyLog" in out["paths"]
    assert "Junk" not in (out.get("components") or {}).get("schemas", {})


def test_trim_by_tag():
    spec = _demo_spec()
    out, before, after = trim_openapi_document(spec, include_tags=["Other"])
    assert before == 2
    assert after == 1
    assert "/a/dailyLog" not in out["paths"]


def test_trim_tag_or_path():
    spec = _demo_spec()
    out, _, after = trim_openapi_document(
        spec,
        include_tags=["Other"],
        path_substrings=["dailyLog"],
    )
    assert after == 2
    assert "/a/dailyLog" in out["paths"]
    assert "/b/other" in out["paths"]


def test_trim_validation_empty():
    spec = _demo_spec()
    with pytest.raises(ValueError):
        trim_openapi_document(spec, include_tags=[], path_substrings=[])


def test_trim_by_operation_keys():
    spec = _demo_spec()
    out, before, after = trim_openapi_document(
        spec,
        include_operation_keys=["get /a/dailyLog"],
    )
    assert before == 2
    assert after == 1
    assert "/a/dailyLog" in out["paths"]
    assert "/b/other" not in out["paths"]


def test_trim_by_operation_keys_rejects_mixed_with_tag_filter():
    spec = _demo_spec()
    with pytest.raises(ValueError, match="not both"):
        trim_openapi_document(
            spec,
            include_operation_keys=["GET /a/dailyLog"],
            include_tags=["Other"],
        )


def test_include_operation_keys_empty_rejected():
    spec = _demo_spec()
    with pytest.raises(ValueError, match="cannot be empty"):
        trim_openapi_document(spec, include_operation_keys=[])


def test_trim_by_path_prefix():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/v1/projects/1": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/v2/other": {"get": {"responses": {"200": {"description": "ok"}}}},
        },
    }
    out, before, after = trim_openapi_document(
        spec, include_path_prefixes=["/v1"]
    )
    assert before == 2
    assert after == 1
    assert "/v1/projects/1" in out["paths"]


def test_include_related_path_depth():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/v1/a/x": {
                "get": {"tags": ["T1"], "responses": {"200": {"description": "ok"}}}
            },
            "/v1/a/y": {
                "get": {"tags": ["Other"], "responses": {"200": {"description": "ok"}}}
            },
            "/u/z": {
                "get": {"tags": ["Other"], "responses": {"200": {"description": "ok"}}}
            },
        },
    }
    out, _, after = trim_openapi_document(
        spec,
        include_tags=["T1"],
        include_related_path_depth=2,
    )
    assert after == 2
    assert "/v1/a/x" in out["paths"]
    assert "/v1/a/y" in out["paths"]
    assert "/u/z" not in out["paths"]


def test_prune_components_false_keeps_unreferenced_schemas():
    spec = _demo_spec()
    out, _, _ = trim_openapi_document(
        spec, path_substrings=["dailyLog"], prune_referenced_components=False
    )
    assert "Junk" in (out.get("components") or {}).get("schemas", {})


def test_spec_json_dumps_min_roundtrip():
    spec = _demo_spec()
    s = spec_json_dumps_min(spec)
    assert json.loads(s)["openapi"] == "3.0.0"
