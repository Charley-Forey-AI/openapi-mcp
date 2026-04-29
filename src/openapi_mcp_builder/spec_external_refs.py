"""Find non-local ``$ref`` values (not starting with ``#/``) in an OpenAPI document."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

_EXTERNAL_REF_REMEDIATION = (
    "This document references other files or URLs. Bundle or inline those references "
    "(e.g. Redocly `bundle`, `swagger-cli bundle`, or your OpenAPI editor) into a single "
    "file with only `#/...` JSON Pointers, then re-upload. Trimming and local $ref-pruning "
    "do not resolve external references."
)


def _collect_ref_strings(obj: Any) -> list[str]:
    if isinstance(obj, dict):
        out: list[str] = []
        r = obj.get("$ref")
        if isinstance(r, str) and r and not r.startswith("#/"):
            out.append(r)
        for k, v in obj.items():
            if k == "$ref":
                continue
            out.extend(_collect_ref_strings(v))
        return out
    if isinstance(obj, list):
        acc: list[str] = []
        for x in obj:
            acc.extend(_collect_ref_strings(x))
        return acc
    return []


def _bucket(ref: str) -> str:
    if "://" in ref:
        p = urlparse(ref)
        return f"url_{(p.scheme or 'unknown').lower()}"
    if ref.startswith(("./", "../", "/")) or ref.endswith((".yaml", ".yml", ".json")):
        return "file_or_relative"
    if ref.strip().startswith("#") and not ref.strip().startswith("#/"):
        return "fragment_not_json_pointer"
    return "other"


def summarize_external_refs(
    spec: dict[str, Any],
    *,
    max_samples: int = 20,
) -> dict[str, Any]:
    """Return count, capped samples, buckets, and a static remediation note."""
    all_refs = _collect_ref_strings(spec)
    unique = list(dict.fromkeys(all_refs))  # preserve order, unique
    buckets: dict[str, int] = {}
    for r in unique:
        b = _bucket(r)
        buckets[b] = buckets.get(b, 0) + 1
    return {
        "external_ref_count": len(unique),
        "external_ref_samples": unique[: max(0, max_samples)],
        "external_ref_buckets": dict(sorted(buckets.items())),
        "external_refs_note": _EXTERNAL_REF_REMEDIATION,
    }


def external_ref_warnings_for_spec(
    spec: dict[str, Any],
    *,
    max_warnings: int = 15,
) -> list[dict[str, str]]:
    """Structured rows for tool responses: code, ref, hint."""
    summ = summarize_external_refs(spec, max_samples=max(0, int(max_warnings)))
    refs: list[str] = summ.get("external_ref_samples") or []
    out: list[dict[str, str]] = []
    for r in refs:
        out.append(
            {
                "code": "EXTERNAL_REF",
                "ref": r,
                "bucket": _bucket(r),
                "hint": _EXTERNAL_REF_REMEDIATION,
            }
        )
    return out
