#!/usr/bin/env python3
"""SessionStart hook -- Bulletproof, Tier 2 (Guia), versao plugin.

Injeta contexto no arranque SO em projetos geridos pelo plugin (decidido pela
porta fv.py). Num projeto nao-gerido -- o FA legado, ou qualquer outro projeto
do utilizador -- cala-se por completo (exit 0 sem output). NUNCA bloqueia; e'
um guia, nao um policia. Fail-open: qualquer erro -> exit 0.

Le o schema v0.2 do .framework-version: `status` (bootstrapping|active) e
`stacks`. Em bootstrapping (stack por decidir, sem testes) avisa para correr o
/framework-init; em active confirma o Exit Lock e faz um aviso de drift simples.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fv as gate  # a porta do marcador
import stacks as stackmod  # detecao de stacks
import capabilities as capmod  # detecao de capacidades (drift de camadas)


def message(fvdata, root):
    status = fvdata.get("status", "active")
    stacks = fvdata.get("stacks", []) or []
    layers = gate.layers_of(fvdata)

    if status == "bootstrapping":
        return ("Framework adopted (layers %s), NO green yet. Run /bulletproof:testar; on the "
                "first green the project becomes 'active' and the Exit Lock arms itself. Until "
                "then code commits are not blocked. (Missing the stack or the tests? Run "
                "/bulletproof:framework-init.)" % layers)

    parts = ["Active layers: %s. Exit Lock policing: a 'git commit' that touches code needs "
             "a green from /bulletproof:testar." % layers]
    if 3 in layers:
        parts.append("Production guards (layer 3) are on: publishing and writing to the "
                     "production database ask for your approval.")
    if stacks:
        parts.append("Stacks: %s." % ", ".join(stacks))
    # drift de stack: apareceu um manifesto de um stack nao declarado?
    sdrift = set(stackmod.detect(root)) - set(stacks)
    if sdrift and stacks:
        parts.append("Stack drift: %s appeared; run /bulletproof:framework-init." %
                     ", ".join(sorted(sdrift)))
    # drift de capacidade: um sinal novo (BD/deploy) que ainda nao esta nas camadas
    try:
        caps, _ = capmod.detect(root)
        new_layers = sorted(set(capmod.layers_for(caps)) - set(layers))
        if new_layers:
            parts.append("WARNING new capability detected (layer %s not switched on yet): run "
                         "/bulletproof:framework-init to switch the guards on." % new_layers)
    except Exception:
        pass
    return " ".join(parts)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    cwd = payload.get("cwd") or os.getcwd()
    try:
        fvdata = gate.managed_project(cwd)
        if fvdata is None:
            sys.exit(0)  # porta fechada -> silencio total
        root = gate.root_of(cwd) or cwd
        out = {"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "[Bulletproof] %s" % message(fvdata, root),
        }}
        print(json.dumps(out))
    except Exception:
        sys.exit(0)  # fail-open


if __name__ == "__main__":
    main()
