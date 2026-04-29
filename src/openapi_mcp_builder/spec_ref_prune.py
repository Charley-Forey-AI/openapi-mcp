"""Prune OpenAPI 3.x ``components`` to the $ref-closure of kept ``paths``."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _deref_local(spec: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        return None
    cur: Any = spec
    for p in ref[2:].split("/"):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _collect_dollar_refs(obj: Any) -> list[str]:
    if isinstance(obj, dict):
        out: list[str] = []
        r = obj.get("$ref")
        if isinstance(r, str) and r.startswith("#/"):
            out.append(r)
        for k, v in obj.items():
            if k == "$ref":
                continue
            out.extend(_collect_dollar_refs(v))
        return out
    if isinstance(obj, list):
        acc: list[str] = []
        for x in obj:
            acc.extend(_collect_dollar_refs(x))
        return acc
    return []


def _components_section_name(ref: str) -> tuple[str, str] | None:
    prefix = "#/components/"
    if not ref.startswith(prefix):
        return None
    rest = ref[len(prefix) :]
    if "/" not in rest:
        return None
    sec, name = rest.split("/", 1)
    if not sec or not name:
        return None
    return sec, name


def prune_openapi_components_to_ref_closure(spec: dict[str, Any]) -> None:
    """In-place: drop unused ``components/*`` entries not reachable from ``paths`` via ``$ref``.

    Only local JSON Pointer refs (``#/...``) are followed. External refs (``http:``) are
    not expanded; anything only needed via external indirection is kept only if
    still referenced from a retained in-document subtree.

    If ``components`` is missing or empty, this is a no-op.
    """
    comp = spec.get("components")
    if not isinstance(comp, dict) or not comp:
        return

    roots: list[Any] = []
    paths = spec.get("paths")
    if isinstance(paths, dict):
        for pitem in paths.values():
            if isinstance(pitem, dict):
                roots.append(pitem)
    wh = spec.get("webhooks")
    if isinstance(wh, dict):
        for witem in wh.values():
            if isinstance(witem, dict):
                roots.append(witem)

    queue: list[str] = []
    for root in roots:
        queue.extend(_collect_dollar_refs(root))

    seen: set[str] = set()
    while queue:
        ref = queue.pop()
        if ref in seen or not ref.startswith("#/"):
            continue
        seen.add(ref)
        if _components_section_name(ref) is None and ref.startswith("#/components/"):
            # Malformed; still try to deref in case of nested / in name (rare).
            pass
        obj = _deref_local(spec, ref)
        if obj is None:
            continue
        for r2 in _collect_dollar_refs(obj):
            if r2 not in seen and r2.startswith("#/"):
                queue.append(r2)

    used: dict[str, set[str]] = defaultdict(set)
    for ref in seen:
        p = _components_section_name(ref)
        if p is not None:
            used[p[0]].add(p[1])

    for section, names in list(comp.items()):
        if not isinstance(names, dict):
            continue
        u = used.get(section)
        if u is None:
            for k in list(names.keys()):
                del names[k]
        else:
            for k in list(names.keys()):
                if k not in u:
                    del names[k]

    for sk in list(comp.keys()):
        sub = comp.get(sk)
        if isinstance(sub, dict) and not sub:
            del comp[sk]
    if not comp:
        del spec["components"]
