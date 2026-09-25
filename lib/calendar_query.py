"""Read-only calendar lookups shared by `check_dup` and `create_event`.

Both have to answer "does the calendar already hold an event for this URL?" the
same way: a loose `q` full-text search, every page walked, then each hit
confirmed by the URL its description leads with. If the two drifted apart,
`create_event`'s last-moment guard could wave through a duplicate that
`check_dup` would have caught.

Failures raise `CalendarQueryError` instead of exiting, so a batch caller can
record one bad lookup and carry on with the rest.

  from calendar_query import CalendarQueryError, find_url_matches
"""
import json
import subprocess
from datetime import datetime, timedelta, timezone

from clean_url import leading_url, normalize_url

DEFAULT_LOOKBACK = timedelta(days=365)


class CalendarQueryError(RuntimeError):
    pass


def default_time_min():
    return (datetime.now(timezone.utc) - DEFAULT_LOOKBACK).isoformat()


def _run_page(calendar_id, url, max_results, page_token, time_min, time_max):
    params = {
        "calendarId": calendar_id,
        "q": url,
        "maxResults": max_results,
        "singleEvents": True,
    }
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max
    if page_token:
        params["pageToken"] = page_token
    cmd = ["gws", "calendar", "events", "list", "--params", json.dumps(params)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise CalendarQueryError("`gws` not found on PATH")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise CalendarQueryError("gws query failed (exit %d): %s"
                                 % (proc.returncode, detail[:500]))

    # gws prints a keyring notice to stderr; stdout is the raw Calendar API JSON.
    # Decode from the first brace to tolerate any incidental prefix.
    out = proc.stdout
    brace = out.find("{")
    if brace == -1:
        raise CalendarQueryError("gws returned no JSON object")
    try:
        return json.JSONDecoder().raw_decode(out, brace)[0]
    except json.JSONDecodeError as err:
        raise CalendarQueryError("could not parse gws response: %s" % err)


def _run_query(calendar_id, url, max_results, max_pages, time_min, time_max):
    """Walk every page of results rather than judging on the first.

    `q` is a loose full-text search, so a busy calendar can push the real match
    past a single page -- and a dedup check that stops early reports "new" for
    an event that already exists. Returns (items, exhausted)."""
    items, token = [], None
    for _ in range(max_pages):
        data = _run_page(calendar_id, url, max_results, token, time_min, time_max)
        items.extend(data.get("items") or [])
        token = data.get("nextPageToken")
        if not token:
            return items, True
    return items, False


def summarize(item):
    when = item.get("start") or {}
    return {
        "id": item.get("id"),
        "summary": item.get("summary"),
        "start": when.get("dateTime") or when.get("date"),
        "location": item.get("location"),
        "htmlLink": item.get("htmlLink"),
    }


def find_url_matches(calendar_id, url, time_min=None, time_max=None,
                     max_results=250, max_pages=10):
    """Events whose description leads with `url` (already cleaned).

    Returns (matches, examined, exhausted). Positional, not a substring search:
    PARTYPLANNER writes the URL first, so a real duplicate leads with it. A
    loose `in` check also matched a URL that merely appeared somewhere in the
    body -- including inside another link's query string -- and reported a
    duplicate that was not one."""
    items, exhausted = _run_query(calendar_id, url, max_results, max_pages,
                                  time_min, time_max)
    target = normalize_url(url)
    matches = [summarize(it) for it in items
               if target and leading_url(it.get("description") or "") == target]
    return matches, len(items), exhausted
