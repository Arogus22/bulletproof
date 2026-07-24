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
        return ("Framework adotado (camadas %s), ainda SEM verde. Corre /testar; ao primeiro "
                "verde o projeto passa a 'active' e o Exit Lock arma-se. Ate la os commits de "
                "codigo nao sao bloqueados. (Falta o stack ou os testes? corre "
                "/bulletproof:framework-init.)" % layers)

    parts = ["Camadas ativas: %s. Exit Lock a policiar: 'git commit' de codigo exige um "
             "verde do /testar." % layers]
    if 3 in layers:
        parts.append("Guardas de producao (camada 3) ligadas: publicar e escrever na BD de "
                     "prod pedem a tua aprovacao.")
    if stacks:
        parts.append("Stacks: %s." % ", ".join(stacks))
    # drift de stack: apareceu um manifesto de um stack nao declarado?
    sdrift = set(stackmod.detect(root)) - set(stacks)
    if sdrift and stacks:
        parts.append("Drift de stack: apareceu %s; corre /bulletproof:framework-init." %
                     ", ".join(sorted(sdrift)))
    # drift de capacidade: um sinal novo (BD/deploy) que ainda nao esta nas camadas
    try:
        caps, _ = capmod.detect(root)
        new_layers = sorted(set(capmod.layers_for(caps)) - set(layers))
        if new_layers:
            parts.append("ATENCAO capacidade nova detetada (camada %s por ligar): corre "
                         "/bulletproof:framework-init para ligar as guardas." % new_layers)
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
