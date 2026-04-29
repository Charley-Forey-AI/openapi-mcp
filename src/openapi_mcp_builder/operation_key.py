"""Canonical operation keys: same shape as ``enumerate_operations`` (``"GET /path"``)."""

from __future__ import annotations


def canonical_operation_key(method: str, path: str) -> str:
    """``METHOD /path`` with method uppercased, path normalized like spec dict keys."""
    m = (method or "get").strip().lower()
    p = (path or "").strip() or "/"
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 1 and p.endswith("/"):
        p = p.rstrip("/")
    return f"{m.upper()} {p}"


def parse_operation_key(key: str) -> tuple[str, str] | None:
    """Parse ``METHOD /path``; return ``(method_lower, path)`` or None."""
    s = (key or "").strip()
    if " " not in s:
        return None
    method, path = s.split(" ", 1)
    method = method.strip()
    path = (path or "").strip()
    if not method or not path:
        return None
    return (method.lower(), path)


def normalize_operation_key_input(key: str) -> str | None:
    """Normalize a user-provided key to the canonical form."""
    p = parse_operation_key(key)
    if p is None:
        return None
    m, path = p
    return canonical_operation_key(m, path)
