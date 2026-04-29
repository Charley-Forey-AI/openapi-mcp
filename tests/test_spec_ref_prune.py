"""Tests for components $ref-closure pruning."""

from __future__ import annotations

from openapi_mcp_builder.spec_ref_prune import prune_openapi_components_to_ref_closure


def test_prune_drops_unreferenced_schemas() -> None:
    spec: dict = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/a": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Kept"},
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Kept": {
                    "type": "object",
                    "properties": {
                        "x": {"$ref": "#/components/schemas/Child"},
                    },
                },
                "Child": {"type": "string"},
                "UnusedProjectSight": {"type": "object", "description": "noise"},
            }
        },
    }
    prune_openapi_components_to_ref_closure(spec)
    assert "UnusedProjectSight" not in spec["components"]["schemas"]
    assert "Kept" in spec["components"]["schemas"]
    assert "Child" in spec["components"]["schemas"]
