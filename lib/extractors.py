"""Per-platform event extractors behind a host registry, plus a generic
schema.org / OpenGraph fallback. Each extractor takes a cleaned URL and returns
the normalized event dict that build_payload consumes:

    platform, url, title, start, end, timezone[, timezone_identifier],
    datetime_display, location, location_available, event_id, description

Logic is ported from the original fetch_*.sh scripts (the proven source of
truth) but restructured to share httpfetch / eventfmt / clean_url. Adding a new
platform = one extract_* function + one REGISTRY row.
"""
import html as htmllib
import json
import re
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from clean_url import clean_url
from eventfmt import UNKNOWN, resolve_zone, parse_iso, human, dedupe
from httpfetch import UA, fetch, FetchError

NEXT_DATA_RE = re.compile(
    r"<script[^>]*\bid=\"__NEXT_DATA__\"[^>]*>(.*?)</script>", re.S)


def _next_data(page):
    m = NEXT_DATA_RE.search(page)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- #
# Luma
# --------------------------------------------------------------------------- #
_LUMA_BLOCKS = {"paragraph", "heading", "listItem", "blockquote",
                "codeBlock", "horizontalRule"}


def _prosemirror(node):
    if isinstance(node, list):
        return "".join(_prosemirror(n) for n in node)
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return node.get("text") or ""
    if kind in ("hard_break", "hardBreak"):
        return "\n"
    inner = _prosemirror(node.get("content") or [])
    return inner + "\n\n" if kind in _LUMA_BLOCKS else inner


def _luma_url(original):
    """Cleaned URL with the host normalized to luma.com."""
    return re.sub(r"^(https?://)(?:www\.)?lu\.ma/", r"\1luma.com/", clean_url(original))


def _luma_venue_join(geo, full):
    """Prepend the venue/place name to the full address when Luma provides one.
    Luma hides the name only inside `short_address`
    ("Blue Shield of California Building, 50 Beale St, San Francisco") while
    `full_address` omits it, so recover the name as the part of short_address
    that precedes the street `address`."""
    short = (geo.get("short_address") or "").strip()
    street = (geo.get("address") or "").strip()
    if short and street:
        i = short.find(street)
        name = short[:i].rstrip(" ,").strip() if i > 0 else ""
        if name and name.lower() not in full.lower():
            return name + ", " + full
    return full


def extract_luma(url):
    blob = _next_data(fetch(url))
    if not blob:
        raise FetchError("no __NEXT_DATA__ block (not a Luma event page?)")
    data = blob.get("props", {}).get("pageProps", {}).get("initialData", {}).get("data")
    if not isinstance(data, dict) or not isinstance(data.get("event"), dict):
        raise FetchError("page has no event payload (calendar or profile URL?)")
    event = data["event"]

    tz, tzname = resolve_zone(event.get("timezone") or "UTC")
    start, end = parse_iso(event.get("start_at"), tz), parse_iso(event.get("end_at"), tz)

    geo = event.get("geo_address_info") or {}
    full = (geo.get("full_address") or geo.get("address") or "").strip()
    if full:
        address, available = _luma_venue_join(geo, full), True
    elif event.get("location_type") == "online" or event.get("zoom_meeting_url"):
        address, available = "Online event", False
    else:
        base = (geo.get("city_state") or geo.get("city") or "").strip()
        sub = (geo.get("sublocality") or "").strip()
        segs = {s.strip().lower() for s in base.split(",") if s.strip()}
        coarse = ([sub] if sub and sub.lower() not in segs else []) + ([base] if base else [])
        address, available = (", ".join(coarse) if coarse else "Register to see address"), False

    description = re.sub(r"\n{3,}", "\n\n", _prosemirror(data.get("description_mirror"))).strip()
    if not description:
        description = (event.get("description_short") or "").strip()

    return {
        "platform": "luma",
        "url": _luma_url(url),
        "title": event.get("name") or UNKNOWN,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "timezone": tzname,
        "datetime_display": human(start, end),
        "location": address,
        "location_available": available,
        "event_id": event.get("api_id") or UNKNOWN,
        "description": description,
    }


def _host_luma(h):
    return h in ("lu.ma", "luma.com") or h.endswith(".lu.ma") or h.endswith(".luma.com")


# --------------------------------------------------------------------------- #
# Partiful
# --------------------------------------------------------------------------- #
def _ics_unescape(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _ics_location(cal_url):
    try:
        req = urllib.request.Request(cal_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception:
        return None
    text = re.sub(r"\r?\n[ \t]", "", text)  # RFC 5545 line unfolding
    hit = re.search(r"^LOCATION(?:;[^:\r\n]*)?:(.*)$", text, re.M)
    return _ics_unescape(hit.group(1)).strip() if hit else None


def extract_partiful(url):
    blob = _next_data(fetch(url))
    if not blob:
        raise FetchError("no __NEXT_DATA__ block (not a Partiful event page?)")
    page = blob.get("props", {}).get("pageProps", {})
    event = page.get("event")
    if not isinstance(event, dict):
        if page.get("passwordRequired"):
            raise FetchError("event is password-protected")
        raise FetchError("page has no event payload (profile or listing URL?)")

    tz, tzname = resolve_zone(event.get("timezone") or "UTC")
    start, end = parse_iso(event.get("startDate"), tz), parse_iso(event.get("endDate"), tz)

    info = event.get("locationInfo") or {}
    maps = info.get("mapsInfo") or {}
    lines = maps.get("addressLines") if isinstance(maps.get("addressLines"), list) else []
    address = ", ".join(dedupe([maps.get("name")] + list(lines))) or None
    if not address:
        for key in ("address", "text", "custom", "name", "value"):
            if isinstance(info.get(key), str) and info[key].strip():
                address = info[key].strip()
                break
    available = bool(address)
    if not address and event.get("calendarFile"):
        found = _ics_location(event["calendarFile"])
        if found:
            address, available = found, True
    if not address:
        coarse = dedupe([info.get("neighborhood"), maps.get("approximateLocation")])
        address = ", ".join(coarse) if coarse else "RSVP for full location"

    description = re.sub(r"\n{3,}", "\n\n", (event.get("description") or "")).strip()

    return {
        "platform": "partiful",
        "url": "https://partiful.com/e/" + event["id"] if event.get("id") else clean_url(url),
        "title": re.sub(r"\s+", " ", (event.get("title") or UNKNOWN)).strip(),
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "timezone": tzname,
        "datetime_display": human(start, end),
        "location": address,
        "location_available": available,
        "event_id": event.get("id") or UNKNOWN,
        "description": description,
    }


def _host_partiful(h):
    return h == "partiful.com" or h.endswith(".partiful.com")


# --------------------------------------------------------------------------- #
# Eventbrite
# --------------------------------------------------------------------------- #
from html.parser import HTMLParser  # noqa: E402

_EB_BLOCKS = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
              "li", "ul", "ol", "blockquote", "pre", "tr", "section", "article", "hr"}


class _EBFlattener(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in _EB_BLOCKS:
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")

    def handle_endtag(self, tag):
        if tag in _EB_BLOCKS:
            self.out.append("\n")

    def handle_data(self, data):
        self.out.append(data)


def _eb_flatten(fragment):
    p = _EBFlattener()
    p.feed(fragment or "")
    p.close()
    body = re.sub(r"[ \t ]+", " ", "".join(p.out))
    body = re.sub(r" *\n *", "\n", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def _eb_clock(dt):
    fmt = "%I %p" if dt.minute == 0 else "%I:%M %p"
    return dt.strftime(fmt).lstrip("0")


def _eb_join(parts):
    parts = [str(p).strip() for p in parts if p and str(p).strip()]
    return ", ".join(p for i, p in enumerate(parts) if i == 0 or p != parts[i - 1]) or None


def _eb_ld(page):
    for raw in re.findall(r"<script[^>]*type=\"application/ld\+json\"[^>]*>(.*?)</script>", page, re.S):
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in doc if isinstance(doc, list) else [doc]:
            if isinstance(node, dict) and "Event" in str(node.get("@type", "")):
                return node
    return None


def extract_eventbrite(url):
    page = fetch(url)
    blob = _next_data(page)
    ctx = None
    if blob:
        c = blob.get("props", {}).get("pageProps", {}).get("context")
        if isinstance(c, dict) and isinstance(c.get("basicInfo"), dict):
            ctx = c
    ld = _eb_ld(page)
    if ctx is None and ld is None:
        raise FetchError("no event payload found (not an Eventbrite event page?)")
    info = (ctx or {}).get("basicInfo", {})

    def from_basic(key):
        node = info.get(key)
        if not isinstance(node, dict):
            return None, None
        try:
            return datetime.fromisoformat(node.get("local")), node.get("timezone")
        except (TypeError, ValueError):
            return None, node.get("timezone")

    def from_ld(key):
        try:
            return datetime.fromisoformat((ld or {}).get(key))
        except (TypeError, ValueError):
            return None

    start, tzname = from_basic("startDate")
    end, end_tz = from_basic("endDate")
    start = start or from_ld("startDate")
    end = end or from_ld("endDate")
    tzname = tzname or end_tz or UNKNOWN
    show_start = not info.get("hideStartDate")
    show_end = not info.get("hideEndDate")

    def stamp(dt, with_time):
        day = dt.strftime("%A, %B ") + str(dt.day)
        return "%s  •  %s" % (day, _eb_clock(dt)) if with_time else day

    def display(a, b):
        if not a:
            return UNKNOWN
        if not b:
            return stamp(a, show_start)
        if a.date() == b.date():
            if show_start and show_end:
                return "%s - %s" % (stamp(a, True), _eb_clock(b))
            return stamp(a, show_start)
        return "%s - %s" % (stamp(a, show_start), stamp(b, show_end))

    venue = info.get("venue") if isinstance(info.get("venue"), dict) else None
    address = None
    if venue:
        addr = venue.get("address") if isinstance(venue.get("address"), dict) else {}
        lines = addr.get("localizedMultiLineAddressDisplay")
        if not isinstance(lines, list) or not lines:
            single = addr.get("localizedAddressDisplay") or addr.get("address_1")
            lines = [single] if single else []
        address = _eb_join([venue.get("name")] + list(lines))
    if not address and isinstance((ld or {}).get("location"), dict):
        place = ld["location"]
        addr = place.get("address") if isinstance(place.get("address"), dict) else {}
        address = _eb_join([place.get("name"), addr.get("streetAddress")])
    available = bool(address)
    if not address:
        online = info.get("isOnline") or "Online" in str((ld or {}).get("eventAttendanceMode", ""))
        address = "Online event" if online else UNKNOWN

    chunks = []
    for module in ((ctx or {}).get("structuredContent") or {}).get("modules") or []:
        if not isinstance(module, dict):
            continue
        if module.get("type") == "text" and module.get("text"):
            chunks.append(_eb_flatten(module["text"]))
        elif module.get("caption"):
            chunks.append(_eb_flatten(module["caption"]))
    description = re.sub(r"\n{3,}", "\n\n", "\n\n".join(c for c in chunks if c)).strip()
    if not description:
        description = (info.get("summary") or htmllib.unescape((ld or {}).get("description") or "")).strip()

    return {
        "platform": "eventbrite",
        "url": info.get("url") or (ld or {}).get("url") or clean_url(url),
        "title": info.get("name") or (ld or {}).get("name") or UNKNOWN,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "timezone": tzname,
        "datetime_display": display(start, end),
        "location": address,
        "location_available": available,
        "event_id": info.get("id") or UNKNOWN,
        "description": description,
    }


def _host_eventbrite(h):
    return bool(re.search(r"(^|\.)eventbrite\.", h))


# --------------------------------------------------------------------------- #
# Splashthat (host-based only; vanity domains fall to generic/WebFetch)
# --------------------------------------------------------------------------- #
def _detag(s):
    if not s:
        return ""
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p\s*>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+\n", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def extract_splashthat(url):
    page = fetch(url, impersonate="chrome")  # DataDome fingerprint check
    m = re.search(r"splash\.server\._event\s*=\s*", page)
    event = None
    if m:
        try:
            event, _ = json.JSONDecoder().raw_decode(page, m.end())
        except json.JSONDecodeError:
            event = None
    if not isinstance(event, dict):
        raise FetchError("no splash.server._event object (not a Splashthat page?)")

    date = event.get("date") or {}
    tzid = (date.get("timezone_identifier") or "").replace(" ", "_")
    tzabbr = (date.get("timezone") or "").strip()
    tz, tzid = resolve_zone(tzid or "UTC")
    tzdisplay = tzabbr or tzid

    def from_ts(ms):
        return datetime.fromtimestamp(ms / 1000, tz) if ms else None

    start = from_ts(date.get("start_timestamp"))
    if not start and date.get("start"):
        try:
            start = datetime.strptime(date["start"], "%m/%d/%Y %H:%M:%S").replace(tzinfo=tz)
        except ValueError:
            start = None
    end = from_ts(date.get("end_timestamp"))

    venue = event.get("venue") or {}
    city_line = " ".join(dedupe([venue.get("city"), venue.get("state"), venue.get("zip_code")]))
    address = ", ".join(dedupe([venue.get("name"), venue.get("address"), city_line])) or None
    available = bool(address)
    if not address:
        address = "To be determined" if venue.get("tbd") else "Location not published"

    domain = (event.get("domain") or {}).get("effective", "")
    return {
        "platform": "splashthat",
        "url": ("https://" + domain) if domain else clean_url(url),
        "title": re.sub(r"\s+", " ", str(event.get("title") or UNKNOWN)).strip(),
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "timezone": tzid,
        "timezone_identifier": tzid,
        "datetime_display": human(start, end) + ((" " + tzdisplay) if start and tzdisplay else ""),
        "location": address,
        "location_available": available,
        "event_id": event.get("id") or UNKNOWN,
        "description": _detag(event.get("description")),
    }


def _host_splashthat(h):
    return h == "splashthat.com" or h.endswith(".splashthat.com")


# --------------------------------------------------------------------------- #
# Generic fallback: schema.org ld+json Event / OpenGraph
# --------------------------------------------------------------------------- #
def _og(page, prop):
    hit = re.search(
        r"<meta[^>]+(?:property|name)=\"" + re.escape(prop) + r"\"[^>]*\bcontent=\"(.*?)\"",
        page, re.S)
    return htmllib.unescape(hit.group(1)).strip() if hit else None


# ld+json Event timestamps carry an offset but no IANA zone. The caller's
# default_tz (from the SKILL/AGENTS default-timezone setting) renders the wall
# time as it should appear on the target calendar: for an offset-bearing stamp
# the absolute instant is preserved and shown in that zone; a naive stamp is
# assumed already-local.
def _generic_dt(ts, zone):
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(zone) if dt.tzinfo else dt.replace(tzinfo=zone)


def extract_generic(url, default_tz):
    """Best-effort: any schema.org Event in ld+json, else OpenGraph title only.
    Returns None when there is nothing usable (caller then defers to WebFetch).
    `default_tz` is the IANA zone (an agent-supplied default; see SKILL.md) used
    to render timestamps that carry an offset but no zone name."""
    page = fetch(url)
    node = _eb_ld(page)  # reuse the ld+json Event finder
    og_title = _og(page, "og:title")
    if node is None and not og_title:
        return None

    zone = ZoneInfo(default_tz)
    node = node or {}
    start = _generic_dt(node.get("startDate"), zone)
    end = _generic_dt(node.get("endDate"), zone)

    address = None
    loc = node.get("location")
    if isinstance(loc, dict):
        addr = loc.get("address")
        if isinstance(addr, dict):
            address = _eb_join([loc.get("name"), addr.get("streetAddress"),
                                addr.get("addressLocality"), addr.get("addressRegion")])
        elif isinstance(addr, str):
            address = _eb_join([loc.get("name"), addr])
        else:
            address = loc.get("name")
    elif isinstance(loc, str):
        address = loc

    return {
        "platform": "generic",
        "url": clean_url(url),
        "title": node.get("name") or og_title or UNKNOWN,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "timezone": default_tz if start else UNKNOWN,
        "datetime_display": human(start, end),
        "location": address or _og(page, "og:street-address") or UNKNOWN,
        "location_available": bool(address),
        "event_id": UNKNOWN,
        "description": (node.get("description")
                       or _og(page, "og:description") or "").strip(),
    }


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
REGISTRY = [
    ("luma", _host_luma, extract_luma),
    ("partiful", _host_partiful, extract_partiful),
    ("eventbrite", _host_eventbrite, extract_eventbrite),
    ("splashthat", _host_splashthat, extract_splashthat),
]


def extractor_for_host(host):
    """Return the (name, extract_fn) whose host predicate matches, or None."""
    host = (host or "").lower()
    for name, pred, fn in REGISTRY:
        if pred(host):
            return name, fn
    return None
