from __future__ import annotations

from collections.abc import Callable
from typing import Any

SanitizeUrl = Callable[[str], str]

_BREADCRUMB_URL_KEYS = ("url", "from", "to")
# sentry-sdk's http breadcrumbs (httpx, urllib, ...) also store these separately from `url`.
_BREADCRUMB_DROP_KEYS = ("http.query", "http.fragment")


def safe_url(fn: SanitizeUrl | None, url: str) -> str:
    """Fail closed: a sanitizer that raises must never let the raw URL through."""
    if fn is None:
        return url
    try:
        out = fn(url)
    except Exception:  # noqa: BLE001
        return "/"
    return out if isinstance(out, str) else "/"


def scrub_breadcrumb(crumb: dict[str, Any], fn: SanitizeUrl | None) -> dict[str, Any]:
    """Scrub a Sentry breadcrumb's URL fields in place."""
    data = crumb.get("data")
    if fn is None or not isinstance(data, dict):
        return crumb
    for key in _BREADCRUMB_URL_KEYS:
        if isinstance(data.get(key), str):
            data[key] = safe_url(fn, data[key])
    for key in _BREADCRUMB_DROP_KEYS:
        data.pop(key, None)
    return crumb


def scrub_event(event: dict[str, Any], fn: SanitizeUrl | None) -> dict[str, Any]:
    """Scrub the URLs on a Sentry event in place."""
    if fn is None:
        return event
    req = event.get("request")
    if isinstance(req, dict):
        if isinstance(req.get("url"), str):
            req["url"] = safe_url(fn, req["url"])
        # The sanitizer owns the URL; a separately stored query string would undo it.
        req.pop("query_string", None)
        headers = req.get("headers")
        if isinstance(headers, dict):
            for name in list(headers):
                if name.lower() == "referer" and isinstance(headers[name], str):
                    headers[name] = safe_url(fn, headers[name])
    crumbs = event.get("breadcrumbs")
    if isinstance(crumbs, dict):  # sentry-sdk wraps them as {"values": [...]}
        crumbs = crumbs.get("values")
    if isinstance(crumbs, list):
        for crumb in crumbs:
            if isinstance(crumb, dict):
                scrub_breadcrumb(crumb, fn)
    return event
