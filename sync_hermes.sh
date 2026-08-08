#!/usr/bin/env bash
# Sync the source tree to the deployed party-planner skill.
#
#   ./sync_hermes.sh                       # sync to ~/.hermes/skills/productivity/party-planner
#   ./sync_hermes.sh --dry-run             # show what would change, write nothing
#   CATEGORY=calendar ./sync_hermes.sh     # override the category subdirectory
#   DST=/path ./sync_hermes.sh             # override the full deploy target (skips CATEGORY)
#
# What it does (idempotent):
#   * mirrors bin/ and lib/ with --delete (prunes files removed from source)
#   * excludes __pycache__ / *.pyc
#   * copies SKILL.md verbatim
#   * marks bin/ scripts executable
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CATEGORY="${CATEGORY:-productivity}"
DST="${DST:-$HOME/.hermes/skills/$CATEGORY/party-planner}"
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
