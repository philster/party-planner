#!/usr/bin/env bash
# Sync the source tree to the deployed party-planner skill.
#
#   ./sync.sh              # sync to ~/.claude/skills/party-planner
#   ./sync.sh --dry-run    # show what would change, write nothing
#   DST=/path ./sync.sh    # override the deploy target
#
# What it does (idempotent):
#   * mirrors bin/ and lib/ with --delete (prunes files removed from source)
#   * excludes __pycache__ / *.pyc
#   * copies SKILL.md verbatim
#   * marks bin/ scripts executable
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST="${DST:-$HOME/.claude/skills/party-planner}"
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

# SKILL.md: deployed as-is.
if [ -n "$DRY" ]; then
  echo "would write $DST/SKILL.md"
else
  cp "$SRC/SKILL.md" "$DST/SKILL.md"
  chmod +x "$DST"/bin/*
fi

echo "done."
