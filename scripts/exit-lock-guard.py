#!/usr/bin/env python3
"""PreToolUse hook (Bash) -- Exit Lock (Bulletproof, Tier 1), versao plugin.

Bloqueia `git commit` quando o commit toca CODIGO que nao esta provado verde (sem
um marcador -- carimbado por mark-green.sh via /testar -- que corresponda ao estado
atual do codigo). So age em projetos GERIDOS pelo plugin (a porta fv.py): um repo
sem o marcador, como o FA legado ou qualquer outro, passa SEMPRE. Commits so de
docs/config nao sao bloqueados. Fail-open: qualquer erro ou ambiente inesperado ->
NAO bloqueia (sai com codigo != 2).

Override por env (testes): BULLETPROOF_STATE (base do estado), BULLETPROOF_LEDGER.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fv as gate  # a porta do marcador

STATE_BASE = os.environ.get("BULLETPROOF_STATE") or os.path.expanduser("~/.claude/state")

CODE_RE = re.compile(
    r"\.(ts|tsx|js|jsx|mjs|cjs|svelte|vue|sql|py|go|rs|rb|java|kt|kts|c|cc|cpp|h|hpp|php|cs)$",
    re.I,
)


def git(args, cwd):
    return subprocess.run(["git", "-C", cwd] + args, capture_output=True, text=True).stdout


def resolve_workdir(cmd, cwd):
    """Onde e que o git vai mesmo correr: respeita 'git -C <path>' e 'cd <path> &&'."""
    m = re.search(r"\bgit\b[^|;&]*?-C\s+(\S+)", cmd) or re.search(r"\bcd\s+(\S+)\s*&&", cmd)
    if m:
        p = m.group(1).strip("'\"")
        return p if os.path.isabs(p) else os.path.join(cwd, p)
    return cwd


def log_block(repo, fp, cmd, session):
    """Grava a intervencao no ledger. Best-effort: nunca rebenta o hook."""
    try:
        import ledger
        ledger.record(event="block", gate="exit_lock", project=repo,
                      reason="no_green_stamp", incident_seed=fp,
                      session=session, detail={"cmd": cmd})
    except Exception:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = payload.get("tool_input", {}).get("command", "") or payload.get("command", "")
    # so morde num git commit (nao em status/push/merge)
    if not re.search(r"\bgit\b[^|;&]*\bcommit\b", cmd):
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    work = resolve_workdir(cmd, cwd)

    # PORTA: so age em projetos geridos pelo plugin. Sem marca -> passa (fail-open).
    fvdata = gate.managed_project(work)
    if fvdata is None:
        sys.exit(0)
    # O Exit Lock so morde quando o projeto esta "active" (ha camada de testes que
    # carimba verde). Em "bootstrapping" (sem testes ainda) fica em espera -> passa.
    if fvdata.get("status") != "active":
        sys.exit(0)
    # Camada 2 so liga se estiver nas layers ativas (invariante: camada so liga por
    # layers). Um v0.2 sem layers mapeia para [1, 2], portanto a 2 esta la.
    if 2 not in gate.layers_of(fvdata):
        sys.exit(0)

    try:
        repo = git(["rev-parse", "--show-toplevel"], work).strip()
        if not repo:
            sys.exit(0)  # nao e repo -> fail-open

        changed = [l for l in git(["diff", "HEAD", "--name-only"], repo).splitlines() if l.strip()]
        if not any(CODE_RE.search(f) for f in changed):
            sys.exit(0)  # so docs/config -> nao morde

        fp = subprocess.run(
            ["bash", os.path.join(HERE, "exit-lock-fp.sh"), repo],
            capture_output=True, text=True,
        ).stdout.strip()
        if not fp:
            sys.exit(0)  # nao consegui calcular -> fail-open

        key = hashlib.sha256(repo.encode()).hexdigest()
        marker = os.path.join(STATE_BASE, "exit-lock", key, "last-green")
        ok = os.path.exists(marker) and open(marker).read().strip() == fp
    except Exception:
        sys.exit(0)  # fail-open

    if not ok:
        log_block(repo, fp, cmd, payload.get("session_id"))
        sys.stderr.write(
            "BLOQUEADO (Exit Lock): este commit toca codigo que nao esta provado verde. "
            "Corre /testar; se passar, ele carimba o verde e o commit passa. "
            "Se ja testaste e mexeste no codigo a seguir, testa outra vez."
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
