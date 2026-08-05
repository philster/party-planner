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
#   * excludes __pycache__ / *.pyc / tests
#   * strips the "BUILD STATUS" HTML comment out of SKILL.md
#   * installs the Codex SKILL.md and AGENTS.md instructions
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

# SKILL.md: copy with the in-project BUILD STATUS comment stripped.
# AGENTS.md: copy the supplemental Codex agent instructions as-is.
if [ -n "$DRY" ]; then
  echo "would write $DST/SKILL.md (BUILD STATUS block stripped)"
  echo "would write $DST/AGENTS.md"
else
  python3 - "$SRC/SKILL.md" "$DST/SKILL.md" "$SRC/AGENTS.md" "$DST/AGENTS.md" <<'PY'
import re, sys
skill_src, skill_dst, agents_src, agents_dst = sys.argv[1:5]

text = open(skill_src, encoding="utf-8").read()
text = re.sub(r"\n<!-- BUILD STATUS.*?-->\n", "\n", text, count=1, flags=re.S)
open(skill_dst, "w", encoding="utf-8").write(text)

open(agents_dst, "w", encoding="utf-8").write(open(agents_src, encoding="utf-8").read())
PY
  chmod +x "$DST"/bin/*
fi

echo "done."
