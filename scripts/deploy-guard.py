#!/usr/bin/env python3
"""PreToolUse(Bash) hook -- Guarda de deploy (Bulletproof, camada 3).

Pede APROVACAO ("ask") antes de PUBLICAR em producao, num projeto gerido pelo plugin
com a camada 3 ligada. Publicar == git push que toque o branch protegido (deploy
automatico), gh pr merge para ele, ou um comando de deploy manual (config.deploy.deploy_cmds:
`wrangler deploy`, `vercel`, ...). Passa: push a branches de trabalho, dry-runs, e tudo o
que nao publica.

Config (do .framework-version): config.deploy.protected_branch, config.deploy.deploy_cmds.
Fail-CLOSED dentro do perimetro (um push cujo destino nao consigo provar diferente do
protegido -> ask). Fail-open so no parse do payload e fora do perimetro (nao gerido /
camada 3 desligada / sem config de deploy).
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fv as gate


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "ask",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


def effective_dir(cmd, cwd):
    """Respeita um 'cd <path> &&' inicial no comando."""
    m = re.match(r'\s*cd\s+"?([^"&;]+?)"?\s*(?:&&|;)', cmd)
    return os.path.expanduser(m.group(1).strip()) if m else cwd


def current_branch(directory):
    try:
        return subprocess.run(["git", "-C", directory, "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def git_parts(cmd):
    """(subcomando, args_apos_subcomando) de um comando git, saltando as opcoes globais
    (-C <path>, -c <x>, --git-dir ...). (None, []) se nao houver subcomando git. Assim
    `git -C /x push origin main` reconhece-se como 'push', nao passa por engano."""
    m = re.search(r"\bgit\b(.*)", cmd, re.S)
    if not m:
        return None, []
    rest = re.split(r"[|;&]", m.group(1))[0]
    toks = rest.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t, toks[i + 1:]
    return None, []


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # sem payload -> nao intervem

    if data.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = (data.get("tool_input") or {}).get("command") or data.get("command") or ""
    cwd = data.get("cwd") or os.getcwd()
    work = effective_dir(cmd, cwd)

    # Gate: projeto gerido + camada 3 ligada + config de deploy.
    fvdata = gate.managed_project(work)
    if fvdata is None or 3 not in gate.layers_of(fvdata):
        sys.exit(0)
    dep = (fvdata.get("config") or {}).get("deploy") or {}
    if not dep:
        sys.exit(0)
    protected = dep.get("protected_branch", "main")
    deploy_cmds = dep.get("deploy_cmds", [])

    # Deploy manual (wrangler deploy, vercel, ...) -> ask.
    for dc in deploy_cmds:
        pat = r"\b" + r"\s+".join(re.escape(t) for t in dc.split()) + r"\b"
        if re.search(pat, cmd):
            ask("`%s` publica diretamente em producao. Regra do projeto: a tua aprovacao "
                "antes de qualquer coisa ir a producao. Autorizas publicar?" % dc)

    # gh pr merge pode fundir para o branch protegido -> ask.
    if re.search(r"\bgh\s+pr\s+merge\b", cmd):
        ask("`gh pr merge` pode fundir para `%s` (deploy automatico da producao). "
            "Autorizas o merge?" % protected)

    # A partir daqui, so git push (o subcomando, saltando -C <path> e opcoes globais).
    sub, args = git_parts(cmd)
    if sub != "push":
        sys.exit(0)
    if "--dry-run" in args:
        sys.exit(0)

    branch_ref = re.compile(r"(?<![\w/-])" + re.escape(protected) + r"(?![\w/-])")
    if branch_ref.search(" ".join(args)):
        ask("Este `git push` publica em `%s` -> deploy da PRODUCAO. Autorizas publicar?" % protected)

    # Determinar o destino: [remote] [refspec], flags fora.
    non_flags = [t for t in args if not t.startswith("-")]
    remotes = {"origin", "upstream"}
    refspec = None
    for t in non_flags:
        if t in remotes:
            continue
        refspec = t
        break
    if refspec is None:
        dst = current_branch(work)  # push implicito -> branch atual
    else:
        dst = refspec.split(":", 1)[1] if ":" in refspec else refspec
        if dst == "HEAD":
            dst = current_branch(work)

    # Branch de trabalho conhecido e != protegido -> passa (alimenta previews).
    if dst and dst != protected:
        sys.exit(0)
    # protegido, ou nao determinavel -> fail-closed, ask.
    ask("Este `git push` vai (ou pode ir) para `%s` -> deploy da PRODUCAO. Autorizas publicar?" % protected)


if __name__ == "__main__":
    main()
