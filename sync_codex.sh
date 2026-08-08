#!/usr/bin/env bash
# Sync the source tree to the deployed party-planner skill.
#
#   ./sync.sh              # sync to ~/.agents/skills/party-planner
#   ./sync.sh --dry-run    # show what would change, write nothing
#   SKILL_NAME=name ./sync.sh  # override the installed skill name
#   DST=/path ./sync.sh        # override the deploy target
#
# What it does (idempotent):
#   * mirrors bin/ and lib/ with --delete (prunes files removed from source)
#   * excludes __pycache__ / *.pyc
#   * installs SKILL.md and the AGENTS.md instructions verbatim
#   * marks bin/ scripts executable
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="${SKILL_NAME:-party-planner}"
DST="${DST:-$HOME/.agents/skills/$SKILL_NAME}"
DRY=""
[ "${1:-}" = "--dry-run" ] && DRY="--dry-run"

echo "sync: $SRC  ->  $DST${DRY:+  (dry-run)}"

RSYNC_EXCLUDES=(--exclude '__pycache__/' --exclude '*.pyc')
if [ -z "$DRY" ]; then
  mkdir -p "$DST/bin" "$DST/lib"
fi

# bin/ and lib/: mirror with delete so orphaned files don't linger in the skill.
rsync -a --delete $DRY "${RSYNC_EXCLUDES[@]}" "$SRC/bin/" "$DST/bin/"
rsync -a --delete $DRY "${RSYNC_EXCLUDES[@]}" "$SRC/lib/" "$DST/lib/"

# SKILL.md and the supplemental Codex AGENTS.md: both deployed as-is.
if [ -n "$DRY" ]; then
  echo "would write $DST/SKILL.md"
  echo "would write $DST/AGENTS.md"
else
  cp "$SRC/SKILL.md" "$DST/SKILL.md"
  cp "$SRC/AGENTS.md" "$DST/AGENTS.md"
  chmod +x "$DST"/bin/*
fi

echo "done."
