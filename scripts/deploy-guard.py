#!/usr/bin/env python3
"""PreToolUse hook (Bash) -- Guarda de deploy de producao (Bulletproof, camada 3).

Pede APROVACAO ("ask") antes de PUBLICAR em producao, num projeto gerido pelo plugin
com a camada 3 ligada. Publicar == git push que toque o branch protegido (deploy
automatico), gh pr merge para ele, ou um comando de deploy manual (config.deploy.deploy_cmds:
`wrangler deploy`, `vercel`, ...). Passa: push a branches de trabalho, dry-runs, e tudo o
que nao publica.

A linha e' lida comando a comando (cmdparse): o `git push` no fim de
`git add -A && git commit -m x && git push`, o deploy atras de um `cd dashboard/api &&`,
e o `wrangler deploy` escondido num `npm run deploy` sao vistos como o que sao. Antes
desta leitura, essas tres formas (as que um agente realmente escreve) passavam caladas.

Config (do .framework-version): config.deploy.protected_branch, config.deploy.deploy_cmds.
Fail-CLOSED dentro do perimetro (um push cujo destino nao consigo provar diferente do
protegido -> ask). Fail-open so no parse do payload e fora do perimetro (nao gerido /
camada 3 off / sem config.deploy). Nunca "deny": devolve a decisao ao humano.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fv as gate
import cmdparse

# flags do `git push` que levam um valor a seguir (para nao o confundir com o remote)
PUSH_VALUE_FLAGS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec",
                    "--recurse-submodules", "--signed"}
# flags que empurram TODOS os branches (logo, tambem o protegido)
PUSH_EVERYTHING = {"--all", "--mirror", "--branches"}


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "ask",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


def current_branch(directory):
    try:
        return subprocess.run(["git", "-C", directory, "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def deploy_config(directory):
    """A config de deploy do projeto gerido que contem `directory`, ou None (fora do perimetro)."""
    fvdata = gate.managed_project(directory)
    if fvdata is None or 3 not in gate.layers_of(fvdata):
        return None
    return (fvdata.get("config") or {}).get("deploy") or None


def check_push(args, directory, protected):
    if "--dry-run" in args or "-n" in args:
        return
    if any(a in PUSH_EVERYTHING for a in args):
        ask("This `git push` pushes every branch, including `%s`, which deploys to PRODUCTION. "
            "Approve publishing?" % protected)

    # git push [<repositorio> [<refspec>...]] -- o 1.o nao-flag e' o remote, o resto refspecs.
    positional, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a in PUSH_VALUE_FLAGS:
            skip = True
            continue
        if a.startswith("-"):
            continue
        positional.append(a)
    refspecs = positional[1:]

    if not refspecs:  # push implicito -> o branch atual
        dst = current_branch(directory)
        if dst and dst != protected and dst != "HEAD":
            return
        ask("This `git push` goes (or may go) to `%s`, which deploys to PRODUCTION. "
            "Approve publishing?" % protected)

    for spec in refspecs:
        spec = spec.lstrip("+")
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        if dst in ("HEAD", "@", ""):
            dst = current_branch(directory)
        dst = re.sub(r"^refs/heads/", "", dst)
        if not dst or dst == protected:
            ask("This `git push` publishes to `%s`, which deploys to PRODUCTION. "
                "Approve publishing?" % protected)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # sem payload -> nao intervem

    if data.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = (data.get("tool_input") or {}).get("command") or data.get("command") or ""
    cwd = data.get("cwd") or os.getcwd()

    for text, toks, directory in cmdparse.effective_commands(cmd, cwd):
        dep = deploy_config(directory)
        if not dep:
            continue  # este comando corre fora de um projeto gerido com camada 3
        protected = dep.get("protected_branch", "main")

        # Deploy manual (wrangler deploy, vercel, ...) -> ask.
        for dc in dep.get("deploy_cmds", []):
            if cmdparse.has_sequence(toks, dc.split()):
                ask("`%s` publishes straight to production. Project rule: nothing goes to "
                    "production without your approval. Approve publishing?" % dc)

        # gh pr merge pode fundir para o branch protegido -> ask.
        prog, args = cmdparse.program(toks)
        if prog == "gh" and args[:2] == ["pr", "merge"]:
            ask("`gh pr merge` may merge into `%s`, which auto-deploys to production. "
                "Approve the merge?" % protected)

        sub, gargs, _dirs = cmdparse.git_parts(toks)
        if sub == "push":
            check_push(gargs, directory, protected)


if __name__ == "__main__":
    main()
