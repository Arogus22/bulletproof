#!/bin/bash
# mark-green.sh -- stamps the current state of the code as "green" (the tests passed).
# Called by /testar at the END, only when the test layers pass. The Exit Lock
# (exit-lock-guard.py) reads this stamp to allow (or not) the git commit.
# Bulletproof layer 1. Idempotent, fail-open.
#
# Plugin version: it resolves fp.sh/ledger.py next to itself (dirname "$0"), not by a
# fixed ~/.claude/hooks path. State in ~/.claude/state (override with BULLETPROOF_STATE
# for tests). It records the green in the ledger (best-effort).
here="$(cd "$(dirname "$0")" && pwd)"
arg="${1:-.}"
state_base="${BULLETPROOF_STATE:-$HOME/.claude/state}"

repo=$(git -C "$arg" rev-parse --show-toplevel 2>/dev/null)
if [ -z "$repo" ]; then echo "mark-green: '$arg' is not a git repo, skipped"; exit 0; fi
fp=$(bash "$here/exit-lock-fp.sh" "$repo")
if [ -z "$fp" ]; then echo "mark-green: could not compute the fingerprint"; exit 0; fi
# The key is sha256(repo path), computed with python3 exactly as exit-lock-guard.py does.
# No shasum/sha256sum: neither is on every system, and python3 is already required.
key=$(python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())' "$repo")
if [ -z "$key" ]; then echo "mark-green: could not hash the repo path"; exit 0; fi
dir="$state_base/exit-lock/$key"
mkdir -p "$dir"
printf '%s' "$fp" > "$dir/last-green"
# record the green in the ledger (the denominator); best-effort, never fails the stamp
python3 "$here/ledger.py" test_green mark_green "$repo" --incident-seed "$fp" >/dev/null 2>&1 || true
echo "Exit Lock: green stamped for $repo (fp ${fp:0:12}...)"
