#!/usr/bin/env bash
# Sync the source tree to the deployed party-planner skill.
#
#   ./sync.sh              # sync to ~/.claude/skills/party-planner
#   ./sync.sh --dry-run    # show what would change, write nothing
#   DST=/path ./sync.sh    # override the deploy target
#
# What it does (idempotent):
#   * mirrors bin/ and lib/ with --delete (prunes files removed from source)
#   * excludes __pycache__ / *.pyc / tests
#   * strips the "BUILD STATUS" HTML comment out of SKILL.md
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

# SKILL.md: copy with the in-project BUILD STATUS comment stripped.
if [ -n "$DRY" ]; then
  echo "would write $DST/SKILL.md (BUILD STATUS block stripped)"
else
  python3 - "$SRC/SKILL.md" "$DST/SKILL.md" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
text = re.sub(r"\n<!-- BUILD STATUS.*?-->\n", "\n", text, count=1, flags=re.S)
open(dst, "w", encoding="utf-8").write(text)
PY
  chmod +x "$DST"/bin/*
fi

echo "done."
