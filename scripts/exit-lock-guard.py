#!/usr/bin/env python3
"""PreToolUse hook (Bash) -- Exit Lock (Bulletproof, Tier 1), versao plugin.

Bloqueia `git commit` quando o commit toca CODIGO que nao esta provado verde (sem
um marcador -- carimbado por mark-green.sh via /testar -- que corresponda ao estado
atual do codigo). So age em projetos GERIDOS pelo plugin (a porta fv.py): um repo
sem o marcador, como o FA legado ou qualquer outro, passa SEMPRE. Commits so de
docs/config nao sao bloqueados. Fail-open: qualquer erro ou ambiente inesperado ->
NAO bloqueia (sai com codigo != 2).

Ficheiros NOVOS contam. O hook corre ANTES do comando, por isso num
`git add -A && git commit` o codigo novo ainda esta' por adicionar quando a guarda olha;
o `git diff HEAD` nao o ve. A guarda le a linha (cmdparse): se ha' um `git add` antes do
commit, junta ao que "este commit toca" o codigo por adicionar que esse `add` vai apanhar.
E a impressao digital (codefp) inclui sempre o codigo por adicionar, por conteudo, para o
verde carimbado antes do `git add` continuar valido depois dele.

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
import cmdparse
import codefp

STATE_BASE = os.environ.get("BULLETPROOF_STATE") or os.path.expanduser("~/.claude/state")


def git(args, cwd):
    return subprocess.run(["git", "-C", cwd] + args, capture_output=True, text=True).stdout


def find_commit(cmd, cwd):
    """(dir_do_commit, adds) do primeiro `git commit` da linha, ou (None, None).
    `adds` sao os argumentos dos `git add`/`git stage` que correm ANTES dele, cada um com
    o diretorio onde corre: e' o que vai entrar no commit e o git ainda nao ve."""
    adds = []
    for _text, toks, directory in cmdparse.effective_commands(cmd, cwd):
        sub, args, _dirs = cmdparse.git_parts(toks)
        if sub in ("add", "stage"):
            adds.append((directory, args))
        elif sub == "commit":
            return directory, adds
    return None, None


def untracked_code_being_added(repo, adds, regex):
    """O codigo por adicionar que os `git add` da linha vao meter no commit. Um caminho
    explicito de ficheiro conta so' esse ficheiro; tudo o resto (-A, ., pastas, globs)
    conta todo o codigo por adicionar -- a guarda nao adivinha para o lado permissivo."""
    if not adds:
        return []
    pending = [p for p in codefp.untracked(repo) if regex.search(p)]
    if not pending:
        return []
    picked, wide = set(), False
    root = os.path.realpath(repo)
    for directory, args in adds:
        flags = [a for a in args if a.startswith("-")]
        specs = [a for a in args if not a.startswith("-")]
        if any(f in ("-u", "--update") for f in flags):
            continue  # `add -u` so' atualiza ficheiros ja' seguidos: nao traz codigo novo
        if not specs:
            if any(f in ("-A", "--all") for f in flags):
                wide = True
            continue
        for spec in specs:
            full = os.path.realpath(os.path.join(directory, spec))
            rel = os.path.relpath(full, root)
            if os.path.isfile(full):
                if rel in pending:
                    picked.add(rel)
            else:
                wide = True  # pasta, ".", glob: nao adivinho para o lado permissivo
    return pending if wide else sorted(picked)


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
    if not re.search(r"\bcommit\b", cmd):
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    work, adds = find_commit(cmd, cwd)
    if work is None:
        sys.exit(0)

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

        code_re = codefp.code_regex(fvdata)
        touched = codefp.changed_code(repo, code_re, include_untracked=False)
        touched += untracked_code_being_added(repo, adds, code_re)
        if not touched:
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
            "BLOCKED (Exit Lock): this commit touches code that is not proven green. "
            "Run /bulletproof:testar; if it passes, it stamps the green and the commit goes "
            "through. If you already tested and changed the code afterwards, test again."
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
