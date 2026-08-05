# Party Planner

An agent skill that adds events to Google Calendar from a pasted URL. It
checks for duplicates before fetching anything, and it can also print a day's
agenda. The deterministic work lives in `bin/` scripts; the model's job is to
judge ambiguity and to gate the actual write.

Everything a script can do, a script does: clean the URL, look up dupes,
detect the platform and extract fields, build the insert payload (title,
description, location, end-time rules), compute the day window with
`zoneinfo` instead of a hardcoded offset, and perform the write itself. What's
left for the model is summarizing a rambling description, picking a title
emoji, handling a page none of the extractors know, flagging a possible
cross-URL duplicate, and asking before anything gets written.

## What's here

- `bin/check_dup` — cleans the URL and searches the calendar first, so a
  duplicate gets caught before a fetch is even attempted.
- `bin/fetch_event` — extracts from Luma, Partiful, Eventbrite, and
  Splashthat by platform, falling back to a generic schema.org/OpenGraph
  reader for anything else. Pages neither can parse exit 4 and hand off to
  the agent's own web-fetch tool.
- `bin/build_payload` — every title, description, location, and end-time rule
  lives here, in one place, so nobody hand-assembles an insert body or
  hand-computes a timezone offset.
- `bin/create_event` — the only script that writes. It wraps `gws calendar
  events insert` and only runs after the user has approved the event; it also
  supports `--dry-run`.
- `bin/plan_day` — a sorted agenda for a given day.

The full flow and exact flags are in [`SKILL.md`](SKILL.md).

## Prerequisites

Python 3.11+, `curl`, and [`gws`](https://github.com/googleworkspace) on
`PATH`, authenticated against the calendar you're targeting. `curl-cffi` is
needed too, but only for Splashthat.

## Installing the skill

Both sync scripts mirror `bin/` and `lib/` into the agent's skills directory
(pruning anything you deleted from source) and mark the scripts executable.
Run them from inside this directory.

### Claude Code

```sh
./sync_claude.sh              # sync to ~/.claude/skills/party-planner
./sync_claude.sh --dry-run    # preview only, writes nothing
DST=/path ./sync_claude.sh    # deploy somewhere else
```

This also installs `SKILL.md`, with the in-project "BUILD STATUS" comment
stripped out first. Claude Code picks the skill up automatically once
`~/.claude/skills/party-planner/SKILL.md` exists.

### Codex

```sh
./sync_codex.sh                    # sync to ~/.agents/skills/party-planner
./sync_codex.sh --dry-run          # preview only, writes nothing
SKILL_NAME=name ./sync_codex.sh    # install under a different name
DST=/path ./sync_codex.sh          # deploy somewhere else
```

This installs `SKILL.md` and `AGENTS.md` as-is — Codex reads the latter for
its own operating instructions.

Re-run the relevant script any time `bin/`, `lib/`, `SKILL.md`, or `AGENTS.md`
changes. Both are safe to run repeatedly.

## Layout

```
bin/      the tools: check_dup, fetch_event, build_payload, create_event, plan_day
lib/      shared helpers — URL cleaning, HTTP fetch, extractors, datetime/address formatting
evals/    scenario-based eval cases for the skill's core flows
SKILL.md  Claude Code skill definition
AGENTS.md Codex operating instructions
```

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
