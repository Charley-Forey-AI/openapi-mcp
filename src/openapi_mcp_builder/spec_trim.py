"""Build a smaller OpenAPI document by keeping only selected paths/operations.

The Agentic executor may count operations in the **uploaded** spec before
``tool_filter`` is applied, so a smaller ``paths`` map is often required to
satisfy OPENAPI_MAX_SPEC_OPERATIONS, not ``tool_filter`` alone.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from openapi_mcp_builder.operation_key import (
    canonical_operation_key,
    normalize_operation_key_input,
)
from openapi_mcp_builder.spec_ref_prune import prune_openapi_components_to_ref_closure

OAS3_HTTP = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)
_PATH_ITEM_NON_METHOD = {"parameters", "servers", "summary", "description", "$ref"}


def _count_operations(spec: dict[str, Any]) -> int:
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return 0
    n = 0
    for pitem in paths.values():
        if not isinstance(pitem, dict):
            continue
        for mkey, mval in pitem.items():
            if mkey in _PATH_ITEM_NON_METHOD:
                continue
            if mkey.lower() in OAS3_HTTP and isinstance(mval, dict):
                n += 1
    return n


def _normalize_path(path: str) -> str:
    s = (path or "").strip() or "/"
    if not s.startswith("/"):
        s = "/" + s
    if len(s) > 1 and s.endswith("/"):
        s = s.rstrip("/")
    return s


def _path_under_path_prefix(path: str, prefix: str) -> bool:
    """True if path equals prefix or extends it: ``/a`` matches ``/a`` and ``/a/b``."""
    a = _normalize_path(path)
    b = _normalize_path(prefix)
    return a == b or a.startswith(b + "/")


def _path_prefix_n_segments(path: str, n: int) -> str:
    p = _normalize_path(path)
    if n <= 0:
        return "/"
    parts = [x for x in p.split("/") if x]
    if not parts:
        return "/"
    take = min(n, len(parts))
    return "/" + "/".join(parts[:take])


def _keep_operation(
    op: dict[str, Any],
    path: str,
    tag_set: frozenset[str] | None,
    path_substrings: tuple[str, ...] | None,
    path_prefixes: tuple[str, ...] | None,
) -> bool:
    """OR across active filters: tag, path substring, path-prefix."""
    n_tag = tag_set is not None and len(tag_set) > 0
    n_sub = path_substrings is not None and len(path_substrings) > 0
    n_pfx = path_prefixes is not None and len(path_prefixes) > 0
    if not n_tag and not n_sub and not n_pfx:
        return False

    by_tag = False
    if n_tag and tag_set is not None:
        otags = {t.lower() for t in (op.get("tags") or []) if isinstance(t, str)}
        want = {t.lower() for t in tag_set if t}
        by_tag = bool(otags and want and (otags & want))

    by_sub = False
    if n_sub and path_substrings is not None:
        pl = path.lower()
        by_sub = any(s and s.lower() in pl for s in path_substrings)

    by_pfx = False
    if n_pfx and path_prefixes is not None:
        by_pfx = any(_path_under_path_prefix(path, pr) for pr in path_prefixes if pr)

    checks: list[bool] = []
    if n_tag:
        checks.append(by_tag)
    if n_sub:
        checks.append(by_sub)
    if n_pfx:
        checks.append(by_pfx)
    return any(checks)


def trim_openapi_document(
    spec: dict[str, Any],
    *,
    include_operation_keys: list[str] | None = None,
    include_tags: list[str] | None = None,
    path_substrings: list[str] | None = None,
    include_path_prefixes: list[str] | None = None,
    include_related_path_depth: int | None = None,
    prune_referenced_components: bool = True,
) -> tuple[dict[str, Any], int, int]:
    """Copy ``spec`` and remove path operations that do not match the filters.

    * ``include_operation_keys`` — if provided and non-empty, keep **only** those
      operations (``operation_key`` form from ``enumerate_operations`` / search:
      ``GET /v1/pets``). This mode is **exclusive**; do not pass tag/path/prefix
      filters in the same call.
    * Otherwise, use tag/path options below (at least one required).
    * ``include_tags`` — if non-empty, only operations whose OpenAPI ``tags``
      intersect this set (case-insensitive) are candidates.
    * ``path_substrings`` — if non-empty, the *path* string (e.g.
      ``/v1/dailyLog``) must contain one of these substrings (case-insensitive,
      literal — not a regex / glob).
    * ``include_path_prefixes`` — if non-empty, the path is kept if it equals
      or extends one of these prefixes (``/a`` matches ``/a`` and ``/a/b/...``).
    * With multiple filters present, the operation is kept if **any** of them
      match (OR).

    **Heuristic (optional)**: ``include_related_path_depth`` (>= 1) expands the
    primary match: for every path that matched, take the first *N* path
    segments as a prefix and keep *all* operations on paths under those
    prefixes. This can pull in sibling or parent collection endpoints; it is
    **not** a guarantee of correct runtime call order or domain dependencies.

    When ``prune_referenced_components`` is true, ``components`` is reduced to
    the $ref-closure of kept operations (shrink responses; all refs from paths
    still resolve). Otherwise ``components`` is left as a full copy of the
    input (larger, but same behavior as pre-prune).
    """
    key_list: list[str] = []
    if include_operation_keys is not None:
        key_list = [str(x).strip() for x in include_operation_keys if str(x).strip()]

    tag_set: frozenset[str] | None = None
    if include_tags and any(str(t).strip() for t in include_tags):
        tag_set = frozenset(s.strip() for s in include_tags if s and str(s).strip())
    ps: tuple[str, ...] = tuple(
        s.strip() for s in (path_substrings or []) if s and str(s).strip()
    )
    pfx: tuple[str, ...] = tuple(
        s.strip() for s in (include_path_prefixes or []) if s and str(s).strip()
    )

    if include_operation_keys is not None and not key_list:
        raise ValueError(
            "include_operation_keys cannot be empty. Omit the argument to use "
            "include_tags / path_substrings / include_path_prefixes instead."
        )

    legacy_active = (tag_set and len(tag_set) > 0) or len(ps) > 0 or len(pfx) > 0
    if key_list and legacy_active:
        raise ValueError(
            "Use either include_operation_keys or tag/path/prefix filters, not both."
        )
    if include_related_path_depth is not None and int(include_related_path_depth) < 1:
        raise ValueError("include_related_path_depth must be >= 1 or None.")
    if key_list and include_related_path_depth is not None:
        raise ValueError(
            "include_related_path_depth applies only to tag/path filters, not to "
            "include_operation_keys."
        )

    if not key_list and not legacy_active:
        raise ValueError(
            "Pass at least one non-empty value in include_operation_keys, or use "
            "include_tags, path_substrings, and/or include_path_prefixes."
        )

    new_spec = copy.deepcopy(spec)
    paths = new_spec.get("paths")
    if not isinstance(paths, dict):
        return new_spec, 0, 0

    before = _count_operations(new_spec)

    if key_list:
        wanted: set[str] = set()
        for r in key_list:
            c = normalize_operation_key_input(r)
            if c is None:
                raise ValueError(
                    f"Invalid operation key {r!r}; expected a string like 'GET /v1/pets'."
                )
            wanted.add(c)
        to_delete_path_keys_k: list[str] = []
        for pkey, pitem in list(paths.items()):
            if not isinstance(pkey, str) or not isinstance(pitem, dict):
                continue
            to_remove_method: list[str] = []
            for mkey, mval in list(pitem.items()):
                if mkey in _PATH_ITEM_NON_METHOD:
                    continue
                if mkey.lower() not in OAS3_HTTP or not isinstance(mval, dict):
                    continue
                ck = canonical_operation_key(mkey, pkey)
                if ck in wanted:
                    continue
                to_remove_method.append(mkey)
            for m in to_remove_method:
                del pitem[m]
            if not any(
                k.lower() in OAS3_HTTP and isinstance(pitem.get(k), dict) for k in pitem
            ):
                to_delete_path_keys_k.append(pkey)
        for pkey in to_delete_path_keys_k:
            del paths[pkey]
        if prune_referenced_components:
            prune_openapi_components_to_ref_closure(new_spec)
        after = _count_operations(new_spec)
        return new_spec, before, after

    tset = tag_set
    psub = ps if len(ps) > 0 else None
    ppre = pfx if len(pfx) > 0 else None

    def _op_keeps_primary(mval: dict[str, Any], pkey: str) -> bool:
        return _keep_operation(
            mval, pkey, tset, psub, ppre
        )

    related_prefixes: set[str] = set()
    if include_related_path_depth is not None:
        d = int(include_related_path_depth)
        for pkey, pitem in paths.items():
            if not isinstance(pkey, str) or not isinstance(pitem, dict):
                continue
            for mkey, mval in pitem.items():
                if mkey in _PATH_ITEM_NON_METHOD:
                    continue
                if mkey.lower() not in OAS3_HTTP or not isinstance(mval, dict):
                    continue
                if _op_keeps_primary(mval, pkey):
                    related_prefixes.add(_path_prefix_n_segments(pkey, d))

    def _op_keeps_final(mval: dict[str, Any], pkey: str) -> bool:
        if _op_keeps_primary(mval, pkey):
            return True
        if not related_prefixes:
            return False
        return any(_path_under_path_prefix(pkey, r) for r in related_prefixes)

    to_delete_path_keys: list[str] = []
    for pkey, pitem in list(paths.items()):
        if not isinstance(pkey, str) or not isinstance(pitem, dict):
            continue
        to_remove_method: list[str] = []
        for mkey, mval in list(pitem.items()):
            if mkey in _PATH_ITEM_NON_METHOD:
                continue
            if mkey.lower() not in OAS3_HTTP or not isinstance(mval, dict):
                continue
            if _op_keeps_final(mval, pkey):
                continue
            to_remove_method.append(mkey)
        for m in to_remove_method:
            del pitem[m]
        if not any(
            k.lower() in OAS3_HTTP and isinstance(pitem.get(k), dict) for k in pitem
        ):
            to_delete_path_keys.append(pkey)

    for pkey in to_delete_path_keys:
        del paths[pkey]

    if prune_referenced_components:
        prune_openapi_components_to_ref_closure(new_spec)

    after = _count_operations(new_spec)
    return new_spec, before, after


def spec_json_dumps_min(spec: dict[str, Any]) -> str:
    """Minified JSON for OpenAPI 3.x upload."""
    return json.dumps(spec, ensure_ascii=False, separators=(",", ":")) + "\n"
