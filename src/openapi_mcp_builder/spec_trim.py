"""Build a smaller OpenAPI document by keeping only selected paths/operations.

The Agentic executor may count operations in the **uploaded** spec before
``tool_filter`` is applied, so a smaller ``paths`` map is often required to
satisfy OPENAPI_MAX_SPEC_OPERATIONS, not ``tool_filter`` alone.
"""

from __future__ import annotations

import copy
import json
from typing import Any

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


def _keep_operation(
    op: dict[str, Any],
    path: str,
    tag_set: frozenset[str] | None,
    path_substrings: tuple[str, ...] | None,
) -> bool:
    """Tag match, path match, or OR when both filters are provided."""
    n_tag = tag_set is not None and len(tag_set) > 0
    n_path = path_substrings is not None and len(path_substrings) > 0
    by_tag = False
    if n_tag and tag_set is not None:
        otags = {t.lower() for t in (op.get("tags") or []) if isinstance(t, str)}
        want = {t.lower() for t in tag_set if t}
        by_tag = bool(otags and want and (otags & want))
    by_path = False
    if n_path and path_substrings is not None:
        pl = path.lower()
        by_path = any(s and s.lower() in pl for s in path_substrings)
    if n_tag and n_path:
        return by_tag or by_path
    if n_tag:
        return by_tag
    if n_path:
        return by_path
    return False


def trim_openapi_document(
    spec: dict[str, Any],
    *,
    include_tags: list[str] | None = None,
    path_substrings: list[str] | None = None,
) -> tuple[dict[str, Any], int, int]:
    """Copy ``spec`` and remove path operations that do not match the filters.

    * ``include_tags`` — if non-empty, only operations whose OpenAPI ``tags``
      intersect this set (case-insensitive) are candidates when this is the
      only filter.
    * ``path_substrings`` — if non-empty, the request *path* string (e.g.
      ``/v1/dailyLog``) must contain one of these substrings (case-insensitive,
      literal match — not a regex).
    * If both are non-empty, an operation is kept if **either** tag or path
      matches (OR). If only one side is set, that rule applies alone.

    ``components`` and other top-level fields are left unchanged to preserve
    ``$ref`` resolution.
    """
    tag_set: frozenset[str] | None = None
    if include_tags and any(str(t).strip() for t in include_tags):
        tag_set = frozenset(s.strip() for s in include_tags if s and str(s).strip())
    ps: tuple[str, ...] = tuple(
        s.strip() for s in (path_substrings or []) if s and str(s).strip()
    )
    if (tag_set is None or len(tag_set) == 0) and len(ps) == 0:
        raise ValueError(
            "Pass at least one non-empty value in include_tags and/or path_substrings."
        )

    new_spec = copy.deepcopy(spec)
    paths = new_spec.get("paths")
    if not isinstance(paths, dict):
        return new_spec, 0, 0

    before = _count_operations(new_spec)
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
            if _keep_operation(
                mval, pkey, tag_set, ps if len(ps) > 0 else None
            ):
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

    after = _count_operations(new_spec)
    return new_spec, before, after


def spec_json_dumps_min(spec: dict[str, Any]) -> str:
    """Minified JSON for OpenAPI 3.x upload."""
    return json.dumps(spec, ensure_ascii=False, separators=(",", ":")) + "\n"
