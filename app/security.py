"""App-wide same-origin guard for every state-changing request.

Threat: any website the user visits can make their browser POST to this local
app. Browsers always attach an Origin header to cross-origin POSTs, so we
require it (or, failing that, Referer) to match this app's own origin. A Host
allow-list additionally blocks DNS rebinding, where Origin and Host would both
carry an attacker's name. Fails closed: no Origin and no Referer is rejected.
"""

from urllib.parse import urlsplit

from flask import render_template, request

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _origin_of(value):
    """Reduce a URL to (scheme, host, port); None if it is not a plain http(s) URL."""
    if not value or value == "null":
        return None
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    return (parts.scheme, host.lower(), port)


def origin_ok(req):
    """True if this (non-safe) request is same-origin and addressed to a local host."""
    try:
        host = urlsplit("//" + req.host).hostname
    except ValueError:
        return False
    if host is None or host.lower() not in LOCAL_HOSTS:
        return False
    own = _origin_of(req.host_url)
    if own is None:
        return False
    # Origin, when present, decides alone (so "null" is a mismatch, and a
    # matching Referer can never rescue a foreign Origin).
    claimed = req.headers.get("Origin")
    if claimed is None:
        claimed = req.headers.get("Referer")
    return _origin_of(claimed) == own


def guard():
    if request.method in SAFE_METHODS:
        return None
    if origin_ok(request):
        return None
    return render_template(
        "error.html",
        message="Request blocked: it did not come from this app. "
                "Reload the page and try again from Storyboard Studio itself.",
    ), 403
