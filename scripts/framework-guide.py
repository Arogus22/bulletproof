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

# manifestos que denunciam a presenca de um stack (para o aviso de drift)
STACK_MANIFESTS = {
    "node": ["package.json"],
    "python": ["pyproject.toml", "requirements.txt", "setup.py"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
    "ruby": ["Gemfile"],
}


def detect_present_stacks(root):
    found = set()
    for stack, files in STACK_MANIFESTS.items():
        if any(os.path.isfile(os.path.join(root, f)) for f in files):
            found.add(stack)
    return found


def message(fvdata, root):
    status = fvdata.get("status", "active")
    stacks = fvdata.get("stacks", []) or []

    if status == "bootstrapping":
        return ("Framework adotado, mas ainda SEM camada de testes (status: bootstrapping). "
                "Decide o stack e corre /bulletproof:framework-init para gerar os testes. "
                "O Exit Lock fica em espera ate haver verde; ate la os commits nao sao bloqueados.")

    # status active
    parts = ["Exit Lock ATIVO (Tier 1): antes de 'git commit' de codigo, o /testar "
             "tem de carimbar verde, senao o commit e' bloqueado."]
    if stacks:
        parts.append("Stacks geridos: %s." % ", ".join(stacks))
    # aviso de drift simples: apareceu um manifesto de um stack nao declarado?
    drift = detect_present_stacks(root) - set(stacks)
    if drift and stacks:
        parts.append("ATENCAO drift: ha manifestos de stack nao declarado (%s). "
                     "Corre /bulletproof:framework-init para estender os testes, senao o "
                     "Exit Lock fica dessincronizado." % ", ".join(sorted(drift)))
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
