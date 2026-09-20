#!/bin/bash
# mark-green.sh -- carimba o estado atual do codigo como "verde" (testes passaram).
# Chamado pelo /testar no FIM, so quando as camadas passam. O Exit Lock
# (exit-lock-guard.py) le este carimbo para deixar (ou nao) o git commit.
# Bulletproof Tier 1. Idempotente, fail-open.
#
# Versao plugin: resolve o fp.sh/ledger.py ao lado (dirname "$0"), nao por caminho
# fixo ~/.claude/hooks. Estado em ~/.claude/state (override por BULLETPROOF_STATE
# para testes). Regista o verde no ledger (best-effort).
here="$(cd "$(dirname "$0")" && pwd)"
arg="${1:-.}"
state_base="${BULLETPROOF_STATE:-$HOME/.claude/state}"

repo=$(git -C "$arg" rev-parse --show-toplevel 2>/dev/null)
if [ -z "$repo" ]; then echo "mark-green: '$arg' nao e um repo git, ignorado"; exit 0; fi
fp=$(bash "$here/exit-lock-fp.sh" "$repo")
if [ -z "$fp" ]; then echo "mark-green: nao consegui calcular o fingerprint"; exit 0; fi
# The key is sha256(repo path), computed with python3 exactly as exit-lock-guard.py does.
# No shasum/sha256sum: neither is on every system, and python3 is already required.
key=$(python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())' "$repo")
if [ -z "$key" ]; then echo "mark-green: could not hash the repo path"; exit 0; fi
dir="$state_base/exit-lock/$key"
mkdir -p "$dir"
printf '%s' "$fp" > "$dir/last-green"
# regista o verde no ledger (denominador); best-effort, nunca falha o carimbo
python3 "$here/ledger.py" test_green mark_green "$repo" --incident-seed "$fp" >/dev/null 2>&1 || true
echo "Exit Lock: verde carimbado para $repo (fp ${fp:0:12}...)"
