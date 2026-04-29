"""Validate a ``tool_filter`` dict before it is sent to the Tools API."""

from __future__ import annotations

import re
from typing import Any

# Known first-class fields on the client ToolFilter; extras may still be forwarded
# if the platform uses ``extra="allow"``-style payloads — we surface unknown keys.
_KNOWN_TOOL_FILTER_KEYS: frozenset[str] = frozenset(
    {
        "include_tags",
        "exclude_tags",
        "include_operations",
        "exclude_operations",
        "include_paths",
        "exclude_paths",
    }
)


def validate_openapi_tool_filter(
    tool_filter: dict[str, Any],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Return validation: regex status for path patterns, unknown keys, and glob-style hints.

    Does **not** mutate the input. With ``strict=False`` (default), invalid regexes set
    ``ok`` to false, but unknown extra keys are only listed. With ``strict=True``,
    ``ok`` is false if there are unknown keys, regex errors, or glob-style path patterns.
    """
    if not isinstance(tool_filter, dict):
        return {
            "ok": False,
            "error": "TypeError",
            "message": "tool_filter must be a JSON object.",
        }

    unknown: list[str] = sorted(
        k for k in tool_filter if k not in _KNOWN_TOOL_FILTER_KEYS
    )

    glob_like_hints: list[dict[str, str]] = []
    bad_regex: dict[str, str] = {}
    for key in ("include_paths", "exclude_paths"):
        raw = tool_filter.get(key)
        if not isinstance(raw, list):
            continue
        for i, pat in enumerate(raw):
            if not isinstance(pat, str):
                bad_regex[f"{key}[{i}]"] = "not a string"
                continue
            s = pat.strip()
            if len(s) >= 2 and s[0] == "*" and s[-1] == "*":
                glob_like_hints.append(
                    {
                        "key": f"{key}[{i}]",
                        "value": s,
                        "hint": (
                            "Globs are not valid regex. Use the dot star form, e.g. "
                            ".*name.*, not *name*."
                        ),
                    }
                )
            try:
                re.compile(pat)
            except re.error as exc:  # pragma: no cover - re.error message varies
                bad_regex[f"{key}[{i}]"] = f"invalid regex: {exc}"

    ok = (
        (not bad_regex and not unknown and not glob_like_hints)
        if strict
        else (not bad_regex)
    )
    return {
        "ok": bool(ok),
        "strict": strict,
        "unknown_keys": unknown,
        "known_keys": sorted(_KNOWN_TOOL_FILTER_KEYS),
        "regex_errors": bad_regex,
        "glob_style_hints": glob_like_hints,
        "note": (
            "The platform expects ``include_paths`` and ``exclude_paths`` entries to be "
            "Python-compatible regular expressions, not shell globs. Invalid field names "
            "(e.g. ``path_pattern``) are not applied—use the known keys from ``known_keys``."
        ),
    }
