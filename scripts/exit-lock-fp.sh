#!/bin/bash
# exit-lock-fp.sh -- prints the CODE fingerprint of a git repo.
# Single entry point for BOTH sides of the Exit Lock (mark-green.sh, which stamps, and
# exit-lock-guard.py, which checks), so the calculation is identical by construction.
# The calculation lives in codefp.py (the why of each choice is there): HEAD + a manifest
# by content of the code files that differ from HEAD, including the new untracked ones.
here="$(cd "$(dirname "$0")" && pwd)"
repo="${1:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -z "$repo" ] && exit 1
python3 "$here/codefp.py" "$repo"
