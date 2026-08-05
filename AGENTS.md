# Party Planner

Use this skill when the user asks to add an event to the calendar, check whether
an event already exists, or plan a calendar day. The skill parses event URLs,
checks duplicates, builds Google Calendar payloads, and creates events only
after explicit user approval.

## Operating rules

The scripts do deterministic work: URL cleaning, extraction, date/time math,
payload construction, and calendar queries. The agent handles only judgment:
summarizing descriptions, choosing an emoji, supplying fallback location or end
time, judging possible cross-URL duplicates, handling unsupported pages, and
gating the calendar write.

Never hand-assemble an insert body or hand-compute timezone offsets.

The files in this directory are installed together. Resolve this file's
directory first and invoke the tools with absolute paths (the current working
directory is not guaranteed to be the skill directory):

```sh
SKILL_DIR="/path/to/party-planner"
```

Use `python3` and the executable scripts under `$SKILL_DIR/bin/`. They emit
JSON unless otherwise noted.

## Prerequisites

- Python 3.11 or newer
- `curl`
- `gws` on PATH, authenticated for the target Google Calendar
- `curl-cffi` only for Splashthat extraction

If a prerequisite is missing, report the error. Do not guess event data or
pretend a calendar write succeeded.

## Defaults

The scripts hold no fallback location or timezone of their own — every flag
below is **required**, with no built-in default, so this file is the single
source of truth for them. Pass these two values explicitly on every call that
takes them; do not guess or hand-roll a different default:

- **Fallback location:** `San Francisco, CA` — pass as `bin/build_payload
  --fallback-location "San Francisco, CA"`.
- **Default timezone:** `America/Los_Angeles` — pass as `--default-tz
  America/Los_Angeles` (`build_payload`, `fetch_event`) or `--timezone
  America/Los_Angeles` (`plan_day`).

## Tools

| Tool | Input → output | Purpose |
|---|---|---|
| `bin/check_dup <URL>` | URL → duplicate report JSON | Cleans the URL and queries the calendar |
| `bin/fetch_event <URL> --json` | URL → normalized event JSON | Detects the platform and extracts fields |
| `bin/build_payload` | event JSON on stdin → insert body JSON | Applies title, description, location, and time rules |
| `bin/create_event` | insert body on stdin → created event JSON | Performs the gated calendar write |
| `bin/plan_day [YYYY-MM-DD]` | date → agenda | Queries and sorts the day's events |

`check_dup` exit codes are 0 = no duplicate, 3 = duplicate, and 2 = error.
`fetch_event` exits 0 when extraction succeeds, 2 for a known-platform or usage
error, and 4 when the page is unsupported and needs web-tool fallback.

## Calendar selection

Before the dedup step — before touching Google Calendar in any way, in either
flow below — list the user's writable calendars and let them pick which one
this run uses:

```
gws calendar calendarList list --params '{"minAccessRole":"writer"}'
```

Present each entry's `summary` (and `id` if it differs from the summary) and
ask the user to pick one. There is no default — every run starts with this
prompt. Pass the chosen id as `--calendar-id <picked>` explicitly on **every**
`bin/` call for the rest of this run (`check_dup`, `create_event`,
`plan_day`); never omit the flag and rely on a script's built-in fallback.
Ask again at the start of each new run — the choice is not persisted.

## Add an event

1. Run `check_dup <URL> --calendar-id <picked>` on the raw pasted URL before
   fetching it.

   - Exit 3: report the matching events and stop.
   - Exit 0: continue.
   - Exit 2: report the error and stop.

2. Run `fetch_event <URL> --json --default-tz America/Los_Angeles` and read the
   resulting JSON.

   If it exits 4, use Codex's web retrieval tool to inspect the page and build
   the same normalized event shape. Do not invent missing dates or times. The
   normalized object should contain `url`, `title`, `start`, `end`, `timezone`,
   `location`, `location_available`, and `description`.

3. Run `build_payload` using the normalized JSON, always passing
   `--fallback-location "San Francisco, CA" --default-tz America/Los_Angeles`,
   plus flags for any judgment call:

   - `--emoji <E>`: title prefix; default 🤡.
   - `--description "<summary>"`: a concise 2–3 sentence summary after reading
     the fetched description. This is the only summarization point.
   - `--location "<address>"`: fallback when the published location is gated or
     coarse; a real published address always wins.
   - `--end-date <WHEN>`: fallback when no published end exists.

   When judgment is needed, keep the fetch and build steps separate so the
   event JSON is read first:

   ```sh
   event_json="$(mktemp)"
   payload_json="$(mktemp)"
   "$SKILL_DIR/bin/fetch_event" "$URL" --json --default-tz America/Los_Angeles \
     >"$event_json"
   "$SKILL_DIR/bin/build_payload" --description "$SUMMARY" \
     --fallback-location "San Francisco, CA" --default-tz America/Los_Angeles \
     <"$event_json" >"$payload_json"
   ```

4. Show the user the finalized title, date/time, location, and URL. Ask for
   explicit approval. Do not invoke `create_event` before the user says yes.

5. After approval, run:

   ```sh
   "$SKILL_DIR/bin/create_event" --calendar-id <picked> <"$payload_json"
   ```

6. Report the created title, date/time, location, URL, and `htmlLink`. Treat a
   nonzero exit or missing created response as a failed write.

## Duplicate reporting

For an exit-3 report, relay each match's title, start, location, matching URL,
and `htmlLink`, then state that nothing was created. The built-in check is an
exact cleaned-URL match. If the same event may exist under a different URL,
explain that suspicion and ask before creating.

## Daily planning

For “plan today” or “plan [day]”, run [Calendar selection](#calendar-selection)
first if it hasn't happened yet this run, then run `bin/plan_day --calendar-id
<picked> --timezone America/Los_Angeles` with no date argument for today, or
with `YYYY-MM-DD` for a specific day. Present each event as title, date, time,
location, and URL, with a blank line between events. The script uses
`zoneinfo`; never replace its DST-safe bounds with a hardcoded UTC offset.

## Rules encoded by `build_payload`

- The cleaned event URL is always first in the description.
- A real published address wins; otherwise use the supplied fallback, a coarse
  published hint, or `--fallback-location` (see [Defaults](#defaults)).
- A published venue name is included when available.
- A published end wins; otherwise the end defaults to start plus two hours.
- The default timezone is `--default-tz` (see [Defaults](#defaults)); valid
  event IANA zones win.

## Emoji guidance

- 🤡: default
- 😒: last-minute or low-signal information
- 🚨: high-priority or do-not-miss event

## URL cleaning

Tracking parameters such as `utm_*`, `aff`, `tk`, `lm_*`, `ref`, `fbclid`,
`gclid`, `_eboga`, and `eb_*` are stripped. The cleaned URL is used for
deduplication and placed at the front of the calendar description.
