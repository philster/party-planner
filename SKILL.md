---
name: party-planner
description: Adds an event to Google Calendar from a pasted URL (Luma, Partiful, Eventbrite, Splashthat, or any page with schema.org/OpenGraph event data), checking for an existing duplicate first; also prints a day's agenda. Use when the user pastes an event link and asks to add, save, or RSVP it to the calendar, asks whether an event is already on the calendar, or asks to plan today or another day.
version: 1.0
created: 2026-08-05
allowed-tools:
  - Bash        # bin/ scripts + gws calendar
  - WebFetch    # fallback extraction for unsupported platforms
---

# PARTYPLANNER Skill

<!-- BUILD STATUS (in-project draft; remove before deploying to .claude/skills/):
     bin/build_payload  ✅ built + tested
     bin/check_dup      ✅ built + tested
     bin/fetch_event    ✅ built + tested (luma/partiful/eventbrite/splashthat + generic)
     bin/create_event   ✅ built + tested (gated gws insert wrapper; --dry-run)
     bin/plan_day       ✅ built + tested (daily summary; DST-safe bounds)
     lib/clean_url.py   ✅ shared URL cleaner
     lib/httpfetch.py   ✅ curl + curl_cffi fetch
     lib/eventfmt.py    ✅ shared datetime/address helpers
     lib/extractors.py  ✅ platform registry + generic ld+json/OG fallback -->

## Principle

Scripts do the deterministic work (parse, clean, format, math); the model does
only what a script cannot: **choose overrides, judge fuzzy duplicates, pick the
title emoji, handle unsupported platforms, and gate the calendar write.** Never
hand-assemble the insert body or hand-compute timezones — that is what the tools
are for, and doing it by hand reintroduces the bugs they exist to prevent.

All tools live in `bin/` alongside this file and emit JSON. Run `<tool> --help`
for full flags.

## Prerequisites

- Python 3.11 or newer
- `curl`
- `gws` on PATH, authenticated for the target Google Calendar
- `curl-cffi` — only needed for Splashthat extraction

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

| Tool | In → Out | Role |
|------|----------|------|
| `bin/check_dup <URL>` | any URL → dup report JSON | Clean URL, query calendar; exit 0 = new, 2 = error, 3 = dup |
| `bin/fetch_event <URL> --json` | URL → normalized event JSON | Detect platform, clean URL, extract fields |
| `bin/build_payload` | event JSON (stdin) → gws insert body | Encodes all title/desc/location/time rules |
| `bin/create_event` | insert body (stdin) → created event JSON | The **human-gated** write (wraps `gws … insert`) |
| `bin/plan_day [YYYY-MM-DD]` | date → sorted summary | Daily agenda (UTC math via zoneinfo) |

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

## Flow — new event

1. **Dedup first.** `bin/check_dup <URL> --calendar-id <picked>` — it cleans
   the URL itself (strips tracking params), so run it on the raw pasted URL
   before spending a fetch.
   - Exit **0** → new. Continue.
   - Exit **2** → error. Surface it; do not guess.
   - Exit **3** → duplicate. Report it (see below) and **stop**.
   - Exit **1** is never a deliberate result — `check_dup` doesn't use it.
     It means the process crashed with an unhandled exception (a bug), not
     a dup/no-dup/error verdict. Treat it like exit 2: surface it, don't guess.
2. **Fetch.** `bin/fetch_event <URL> --json --default-tz America/Los_Angeles` →
   normalized JSON. If the platform is unsupported, fall back to `WebFetch` and
   build the same JSON shape by hand.
3. **Build.** Pipe the event JSON into `bin/build_payload`, always passing
   `--fallback-location "San Francisco, CA" --default-tz America/Los_Angeles`,
   plus flags for any judgment call:
   - `--emoji <E>` — pick by condition (see Emoji).
   - `--description "<summary>"` — **the one summarization point.** Read the
     `description` field in step 2's JSON; if it is long/rambling, condense it to
     a readable 2–3 sentences and pass that here. `build_payload` still puts the
     URL first, then your summary. This is the *only* place summarizing belongs —
     `create_event` receives a finalized body and never reshapes it.
   - `--location "<addr>"` — fallback address, used only when the fetched
     location is gated/coarse (`location_available` false). A real published
     address always wins, so pass this for events whose venue isn't published.
   - `--end-date <WHEN>` — fallback end when none is published (a published end
     always wins).

   Summarizing (or any judgment on the text) means you must **read the fetch
   output before building** — so split the pipe instead of streaming it:
   ```
   TMPDIR=${TMPDIR:-/tmp}
   bin/fetch_event <URL> --json --default-tz America/Los_Angeles \
     > "$TMPDIR/partyplanner-event.json"        # then READ it
   bin/build_payload --description "<2-3 sentence summary>" \
     --fallback-location "San Francisco, CA" --default-tz America/Los_Angeles \
     < "$TMPDIR/partyplanner-event.json" > "$TMPDIR/partyplanner-payload.json"
   ```
   When no summary/override is needed, the straight pipe is fine:
   ```
   bin/fetch_event <URL> --json --default-tz America/Los_Angeles \
     | bin/build_payload --fallback-location "San Francisco, CA" \
       --default-tz America/Los_Angeles > "$TMPDIR/partyplanner-payload.json"
   ```
   (add `--emoji 🤡/😒/🚨` per the Emoji section's conditions)
4. **Confirm.** Show the payload (title, date/time, location, URL) and **ask
   permission**. Do not write without an explicit yes.
5. **Create.** On yes: `bin/create_event --calendar-id <picked> < "$TMPDIR/partyplanner-payload.json"`.
   It wraps:
   ```
   gws calendar events insert \
     --params '{"calendarId":"<picked>"}' --json @"$TMPDIR/partyplanner-payload.json"
   ```
6. **Confirm created.** Report title, date/time, location, URL, and the link.

## Emoji (title prefix)

`--emoji` is optional; omitted, the summary is plain `"<title>"`. Choose by
condition — these three are the only options, never invent another one:

- 🤡 — ordinary event, no special flag
- 😒 — last-minute or low-signal info
- 🚨 — high priority / don't-miss

No match on any of the three → omit `--emoji`.

## Duplicate notice output

When `check_dup` reports a duplicate, relay from its `matches`:
- Event title, start, location, and the URL that matched
- The `htmlLink` to the existing event
- A clear statement that the event already exists → nothing created.

`check_dup` matches on the URL stored verbatim at the front of the description,
so its hits are exact. If you *suspect* a duplicate it missed (same event, a
different URL — e.g. a Luma vs. Partiful copy), that is a **judgment call**:
say so and ask before creating.

## Daily summary

- **Trigger:** "plan today" / "plan [day]".
- **Calendar:** run [Calendar selection](#calendar-selection) first if it
  hasn't happened yet this run.
- **Run:** `bin/plan_day --calendar-id <picked> --timezone America/Los_Angeles`
  (no date arg = today) or `bin/plan_day --calendar-id <picked> --timezone
  America/Los_Angeles 2026-07-20`.
- `plan_day` computes the day's UTC bounds in `--timezone` with `zoneinfo`
  (correct across a DST boundary — do **not** hardcode a +7h offset), queries
  the calendar, and returns events sorted by start.
- **Format:** Title / Date / Time / Location / URL, one blank line between events.

## Description & location rules (handled by build_payload)

- **URL is ALWAYS first** in the description, then a blank line, then the body
  (`--description` override, else the fetched text).
- Location: a **real** published address (fetcher flag `location_available`),
  else `--location`, else a coarse published hint, else `--fallback-location`
  (see [Defaults](#defaults)). A published venue name is prepended to the
  street address when the platform exposes one ("Blue Shield of California
  Building, 50 Beale St, …"). Gated/placeholder strings ("RSVP for full
  location", "Unknown", …) never win.
- End time: the published end, else **start + 2h**.

## Timezone

- Pass `--default-tz` (see [Defaults](#defaults)). `build_payload` keeps each
  event's own IANA zone when present (resolving Splashthat's `PDT` ↔
  `timezone_identifier` split).
- Never compute UTC offsets by hand; the tools use `zoneinfo`.

## URL cleaning

`fetch_event` strips tracking params (`utm_*`, `aff`, `tk`, `lm_*`, `ref`,
`fbclid`, `gclid`, `_eboga`, `eb_*`) and preserves the original param order. The
cleaned `url` field is what feeds `check_dup` and leads the description.

## Temporary File Management

Write all transient files to the system temporary directory:
- Use `$TMPDIR` on macOS/Linux, or `$TEMP` on Windows
- If system temp access is restricted, create and reference a local `tmp/` folder at the root of the current working directory
- Ensure all temporary file names follow the format: `[session-id]-[purpose].[extension]` to prevent overlapping filenames

Example:
```bash
TMPDIR=${TMPDIR:-/tmp}
bin/fetch_event <URL> --json --default-tz America/Los_Angeles > "$TMPDIR/partyplanner-event.json"
bin/build_payload --description "<summary>" --fallback-location "San Francisco, CA" \
  --default-tz America/Los_Angeles < "$TMPDIR/partyplanner-event.json" > "$TMPDIR/partyplanner-payload.json"
bin/create_event < "$TMPDIR/partyplanner-payload.json"
```
