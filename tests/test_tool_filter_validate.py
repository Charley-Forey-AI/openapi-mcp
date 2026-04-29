"""Tests for local tool_filter validation helper."""

from __future__ import annotations

from openapi_mcp_builder.tool_filter_validate import validate_openapi_tool_filter


def test_flags_unknown_path_pattern_and_invalid_regex() -> None:
    r = validate_openapi_tool_filter(
        {
            "path_pattern": "x",  # unknown; common mistake
            "include_paths": ["["],
        }
    )
    assert "path_pattern" in r["unknown_keys"]
    assert "include_paths[0]" in r["regex_errors"]
    assert r["ok"] is False


def test_valid_filter_ok() -> None:
    r = validate_openapi_tool_filter(
        {"include_tags": ["A"], "include_paths": [".*log.*", r"\/v1\/x"]}
    )
    assert r["ok"] is True
    assert "path_pattern" not in (r.get("unknown_keys") or [])


def test_glob_style_hint() -> None:
    r = validate_openapi_tool_filter(
        {
            "include_paths": ["*log*"],
        }
    )
    assert len(r["glob_style_hints"]) == 1
    assert r["ok"] is False
    assert "include_paths[0]" in r["regex_errors"]


def test_non_strict_allows_unknown_keys_if_regex_valid() -> None:
    r = validate_openapi_tool_filter(
        {"include_paths": [".*a.*"], "path_pattern": "not_used"},
    )
    assert r["ok"] is True
    assert "path_pattern" in r["unknown_keys"]


def test_strict_fails_on_unknown_keys() -> None:
    r = validate_openapi_tool_filter(
        {"include_paths": [".*a.*"], "path_pattern": "not_used"},
        strict=True,
    )
    assert r["ok"] is False
    assert "path_pattern" in r["unknown_keys"]


def test_strict_fails_on_glob_hint_even_if_regex_compiles() -> None:
    # *a* can compile in Python re? Actually * at start is error - skip
    r = validate_openapi_tool_filter(
        {"include_paths": ["*x*"]},
        strict=True,
    )
    assert r["ok"] is False
    assert r["strict"] is True
