"""Pure helpers for safe AH diagnostic capture."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

_SENSITIVE_KEYS = {
    "address",
    "addresssingleline",
    "street",
    "housenumber",
    "housenumberextra",
    "postalcode",
    "zipcode",
    "city",
    "countrycode",
    "accesstoken",
    "access_token",
    "refreshtoken",
    "refresh_token",
    "memberid",
    "member_id",
    "token",
}


def _hash_order_id(value: Any) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:12]


def sanitize_for_diagnostics(value: Any) -> Any:
    """Return JSON-safe diagnostics with secrets/addresses removed.

    Order IDs are retained only as a short irreversible hash so multiple probe
    results can still be correlated without exposing the real order number.
    """
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "").replace("_", "").lower()
            if normalized in _SENSITIVE_KEYS:
                continue
            if normalized == "orderid":
                clean["orderIdHash"] = _hash_order_id(item)
                continue
            clean[str(key)] = sanitize_for_diagnostics(item)
        return clean
    if isinstance(value, list):
        return [sanitize_for_diagnostics(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_diagnostics(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def merge_fulfillment_payload(base: dict[str, Any], addon: dict[str, Any]) -> dict[str, Any]:
    """Merge additional orderFulfillments fields into a base response by orderId."""
    merged = deepcopy(base)
    base_root = merged.get("orderFulfillments")
    addon_root = addon.get("orderFulfillments") if isinstance(addon, dict) else None
    if not isinstance(base_root, dict) or not isinstance(addon_root, dict):
        return merged
    base_results = base_root.get("result")
    addon_results = addon_root.get("result")
    if not isinstance(base_results, list) or not isinstance(addon_results, list):
        return merged

    addon_by_id = {
        item.get("orderId"): item
        for item in addon_results
        if isinstance(item, dict) and item.get("orderId") is not None
    }
    for item in base_results:
        if not isinstance(item, dict):
            continue
        extra = addon_by_id.get(item.get("orderId"))
        if not isinstance(extra, dict):
            continue
        _deep_merge(item, extra)
    return merged


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge(target[key], value)
        elif value is not None:
            target[key] = deepcopy(value)
