"""Shared formatting helpers for the extractors: datetime parsing, the human
"date/time" string, and address de-duplication. Kept identical to the behaviour
the original fetch_*.sh scripts shipped, so output stays stable.
"""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UNKNOWN = "Unknown"


def resolve_zone(tzname):
    """Return (ZoneInfo, canonical_name), falling back to UTC on a bad name."""
    try:
        return ZoneInfo(tzname), tzname
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC"), "UTC"


def parse_iso(ts, tz):
    """Parse an ISO timestamp and express it in `tz`. Returns None on failure."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz)
    except (ValueError, AttributeError):
        return None


def clock(dt):
    # Cross-platform (no %-I): strip the leading zero off the 12-hour field.
    return dt.strftime("%I:%M %p").lstrip("0")


def human(a, b, clockfn=clock):
    """"Saturday, July 26 6:00 PM - 8:00 PM" style display; handles a missing
    end and a multi-day span."""
    if not a:
        return UNKNOWN
    day = a.strftime("%A, %B ") + str(a.day)
    if not b:
        return "%s %s" % (day, clockfn(a))
    if a.date() == b.date():
        return "%s %s - %s" % (day, clockfn(a), clockfn(b))
    return "%s %s - %s %s" % (day, clockfn(a), b.strftime("%A, %B ") + str(b.day), clockfn(b))


def dedupe(parts):
    """Strip/skip blanks and case-insensitive repeats, preserving order."""
    seen, out = set(), []
    for p in parts:
        p = (p or "").strip().strip(",")
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out
