"""Shared URL cleaner: strip tracking params, preserve everything else and the
original param order. Used by check_dup (so dedup can run before fetch) and,
later, by fetch_event. Kept platform-agnostic — a superset of the drop lists the
individual fetchers use.

  from clean_url import clean_url
  clean_url("https://lu.ma/openro-kwy3?utm_source=x&aff=y")  # -> https://lu.ma/openro-kwy3
"""
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# Dropped on every platform.
_DROP_EXACT = {
    "aff", "aff_id", "tk", "ref", "fbclid", "gclid",
    "_eboga", "keep_tld", "internal_ref", "invite",
}
_DROP_PREFIX = ("utm_", "lm_", "eb_")


def _keep(key):
    k = key.lower()
    return not (k in _DROP_EXACT or k.startswith(_DROP_PREFIX))


def clean_url(url):
    """Return `url` with tracking params removed. Adds https:// when the input
    has no scheme, so bare host/path strings clean correctly too."""
    parts = urlsplit(url)
    if not parts.scheme:
        parts = urlsplit("https://" + url)
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if _keep(k)]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
