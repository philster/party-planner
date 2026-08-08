"""Shared URL handling: strip tracking params, canonicalize known host aliases,
and read back the URL a stored description leads with.

`check_dup`, `fetch_event` and `plan_day` all have to agree on what "the same
URL" means, or dedup quietly fails open (a duplicate gets created) or closed (a
new event is refused). Keeping every rule here is what makes them agree.

  from clean_url import clean_url, normalize_url, leading_url
  clean_url("https://lu.ma/openro-kwy3?utm_source=x&aff=y")  # -> https://luma.com/openro-kwy3
"""
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# Dropped on every platform.
_DROP_EXACT = {
    "aff", "aff_id", "tk", "ref", "fbclid", "gclid",
    "_eboga", "keep_tld", "internal_ref", "invite",
}
_DROP_PREFIX = ("utm_", "lm_", "eb_")

# Host spellings that address the same page. Applied here rather than inside a
# single extractor so that the URL check_dup searches for and the URL
# build_payload stores can never disagree about, say, lu.ma vs luma.com.
_HOST_ALIASES = {"lu.ma": "luma.com", "www.lu.ma": "luma.com"}

_TAG_RE = re.compile(r"<[^>]{0,400}>")
_LEADING_URL_RE = re.compile(r"(?i)^(https?://[^\s<>\"']+)")


def _keep(key):
    k = key.lower()
    return not (k in _DROP_EXACT or k.startswith(_DROP_PREFIX))


def clean_url(url):
    """Return `url` with tracking params removed and known host aliases
    canonicalized. Adds https:// when the input has no scheme, so bare
    host/path strings clean correctly too."""
    parts = urlsplit(url)
    if not parts.scheme:
        parts = urlsplit("https://" + url)
    netloc = parts.netloc
    try:
        host, port = parts.hostname, parts.port
    except ValueError:
        host, port = None, None
    if host and host.lower() in _HOST_ALIASES:
        netloc = _HOST_ALIASES[host.lower()] + (":%d" % port if port else "")
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if _keep(k)]
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def normalize_url(url):
    """Collapse the cosmetic differences between two spellings of the same URL:
    scheme, a leading www., case, a trailing slash, and a host alias.

    The alias map matters here and not just in `clean_url`: descriptions written
    before a host was aliased still hold the old spelling, and a dedup check
    that read them as a different URL would file a second copy of an event the
    calendar already has."""
    u = (url or "").strip().lower()
    for prefix in ("https://", "http://"):
        if u.startswith(prefix):
            u = u[len(prefix):]
            break
    if u.startswith("www."):
        u = u[4:]
    host, slash, rest = u.partition("/")
    hostname = host.partition(":")[0]
    if hostname in _HOST_ALIASES:
        host = _HOST_ALIASES[hostname] + host[len(hostname):]
    return (host + slash + rest).rstrip("/")


def leading_url(description):
    """The URL a PARTYPLANNER description opens with, normalized, or "".

    build_payload always writes the event URL first, so that position is the
    claim worth trusting. Reading it positionally -- rather than searching the
    whole body -- means text further down cannot pass itself off as the event's
    URL, and tags are stripped first so a link Calendar auto-inserted around it
    does not hide it."""
    text = _TAG_RE.sub(" ", description or "").strip()
    if not text:
        return ""
    hit = _LEADING_URL_RE.match(text.split("\n", 1)[0].strip())
    # Clean before normalizing: descriptions written before this ran clean_url
    # still carry tracking params, and comparing those against a cleaned query
    # URL would read an existing event as new.
    return normalize_url(clean_url(hit.group(1))) if hit else ""
