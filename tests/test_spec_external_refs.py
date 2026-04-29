"""Tests for external $ref detection."""

from __future__ import annotations

from openapi_mcp_builder.spec_external_refs import (
    summarize_external_refs,
)


def test_detects_http_ref() -> None:
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/a": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "https://example.com/schemas/Pet.json"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }
    s = summarize_external_refs(spec, max_samples=10)
    assert s["external_ref_count"] == 1
    assert "https://example.com/schemas/Pet.json" in s["external_ref_samples"]


def test_ignores_local_json_pointer() -> None:
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/x": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/X"},
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {"schemas": {"X": {"type": "string"}}},
    }
    s = summarize_external_refs(spec)
    assert s["external_ref_count"] == 0
