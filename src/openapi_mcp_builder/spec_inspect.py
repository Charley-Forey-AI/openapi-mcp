"""Parse OpenAPI / Swagger documents and summarize operations for MCP tool_filter planning."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

import yaml

from openapi_mcp_builder.models import ToolFilter

# Platform default from typical Agentic executor errors (OPENAPI_MAX_SPEC_OPERATIONS).
DEFAULT_PLATFORM_MAX_OPERATIONS = 50

OAS3_HTTP = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


def parse_openapi_spec_bytes(data: bytes) -> dict[str, Any]:
    """Parse raw JSON or YAML into a spec dict. Raises ValueError on failure."""
    return _parse_spec_bytes(data)


def _parse_spec_bytes(data: bytes) -> dict[str, Any]:
    text = data.decode("utf-8", errors="replace").lstrip()
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as exc:  # pragma: no cover - download_spec pre-validates
            raise ValueError(f"Invalid YAML/JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("OpenAPI document must be a JSON object.")
    if "openapi" not in parsed and "swagger" not in parsed:
        raise ValueError("Not an OpenAPI or Swagger document (missing openapi / swagger).")
    return parsed


def enumerate_operations(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """List every path/method in the spec with tags and stable keys for tool_filter.

    Returns dicts: ``method``, ``path``, ``operation_id``, ``tags`` (list, possibly empty),
    ``operation_key`` (``\"GET /x\"``) for use with ``include_operations`` when the
    platform expects method+path form.
    """
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return []
    out: list[dict[str, Any]] = []
    for path, item in paths.items():
        if not isinstance(path, str) or not isinstance(item, dict):
            continue
        for method, raw_op in item.items():
            if method in ("parameters", "servers", "summary", "description", "$ref"):
                continue
            lower = method.lower()
            if lower not in OAS3_HTTP:
                continue
            if not isinstance(raw_op, dict):
                continue
            op = raw_op
            op_id = op.get("operationId")
            if not isinstance(op_id, str):
                op_id = None
            tag_list: list[str] = []
            raw_tags = op.get("tags")
            if isinstance(raw_tags, list):
                for t in raw_tags:
                    if isinstance(t, str) and t.strip():
                        tag_list.append(t.strip())
            m = lower.upper()
            key = f"{m} {path}"
            out.append(
                {
                    "method": m,
                    "path": path,
                    "operation_id": op_id,
                    "tags": tag_list,
                    "operation_key": key,
                }
            )
    return out


def _path_prefix(path: str) -> str:
    p = path.strip() or "/"
    if not p.startswith("/"):
        p = "/" + p
    parts = [x for x in p.split("/") if x]
    if not parts:
        return "/"
    return f"/{parts[0]}"


def build_summary(
    spec: dict[str, Any],
    *,
    operations: list[dict[str, Any]] | None = None,
    platform_max_operations: int = DEFAULT_PLATFORM_MAX_OPERATIONS,
    max_sample_ops_per_tag: int = 5,
    path_prefix_top_n: int = 30,
) -> dict[str, Any]:
    """Aggregate tag counts, path-prefix counts, and filter hints for agents."""
    ops = operations if operations is not None else enumerate_operations(spec)
    total = len(ops)
    by_tag: dict[str, list[str]] = defaultdict(list)
    for op in ops:
        keys = [op["operation_key"]]
        tgs = op["tags"]
        if not tgs:
            by_tag["(untagged)"].extend(keys)
        else:
            for t in tgs:
                by_tag[t].extend(keys)

    tag_rows: list[dict[str, Any]] = []
    for tag, op_keys in sorted(
        by_tag.items(), key=lambda x: (-len(x[1]), str(x[0]).lower())
    ):
        uniq = list(dict.fromkeys(op_keys))
        tag_rows.append(
            {
                "tag": tag,
                "operation_count": len(uniq),
                "sample_operation_keys": uniq[: max(0, max_sample_ops_per_tag)],
            }
        )

    prefix_counter: Counter[str] = Counter()
    for op in ops:
        prefix_counter[_path_prefix(str(op.get("path", "")))] += 1
    top_prefixes = [
        {"path_prefix": p, "operation_count": c}
        for p, c in prefix_counter.most_common(path_prefix_top_n)
    ]

    oa = spec.get("openapi")
    sw = spec.get("swagger")
    version = f"openapi {oa}" if oa is not None else (f"swagger {sw}" if sw else "unknown")

    return {
        "openapi_version": version,
        "title": (spec.get("info") or {}).get("title")
        if isinstance(spec.get("info"), dict)
        else None,
        "total_operations": total,
        "platform_operation_limit": platform_max_operations,
        "exceeds_platform_limit": total > platform_max_operations,
        "tags": tag_rows,
        "path_prefixes_top": top_prefixes,
        "filter_hints": {
            "description": (
                "Use `tool_filter` on create (if supported) or "
                "`update_openapi_mcp_server` with `tool_filter` to re-parse. "
                "Fields: include_tags, exclude_tags, include_paths, exclude_paths, "
                "include_operations, exclude_operations. "
                "include_operations often uses `operation_key` like `GET /v1/pets`."
            ),
        },
    }


def tool_filter_from_tags(include_tags: list[str]) -> dict[str, Any]:
    """Convenience: build a ToolFilter including only the given tag names."""
    f = ToolFilter(include_tags=include_tags)
    return f.model_dump(exclude_none=True)


def count_operations_matching_any_tag(
    operations: list[dict[str, Any]], include_tags: list[str]
) -> int:
    """How many operations have at least one tag in ``include_tags`` (rough lower bound)."""
    if not include_tags:
        return 0
    want = set(include_tags)
    n = 0
    for op in operations:
        op_tags = {t for t in (op.get("tags") or []) if isinstance(t, str)}
        if op_tags and (op_tags & want):
            n += 1
    return n
