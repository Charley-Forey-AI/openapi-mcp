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
                "get": {"tags": ["Daily"], "responses": {"200": {"description": "ok"}}}
            },
            "/b/other": {
                "post": {"tags": ["Other"], "responses": {"200": {"description": "ok"}}}
            },
        },
        "components": {"schemas": {"X": {"type": "string"}}},
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
    assert "components" in out


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


def test_spec_json_dumps_min_roundtrip():
    spec = _demo_spec()
    s = spec_json_dumps_min(spec)
    assert json.loads(s)["openapi"] == "3.0.0"
