#!/usr/bin/env python3
"""framework-init.py -- adota um projeto no Bulletproof (versao mecanica, Fase 1).

Cria (ou estende, idempotente) o .framework-version v0.2 na raiz do projeto, com
o marcador do plugin ("plugin": "bulletproof"), o status e os stacks detetados.
NAO gera ainda a camada de testes (isso e' a Fase 2); por isso o status arranca em
"bootstrapping" e o Exit Lock fica em espera ate haver verde.

Uso: python3 framework-init.py [dir] [--stack S ...]
  dir      raiz do projeto (default: diretorio atual)
  --stack  força um stack (repetivel); se omitido, deteta pelos manifestos.

Recusa-se a sobrescrever um .framework-version LEGADO (sem o marcador do plugin,
ex.: o do FA): protege setups proprios de serem apanhados por engano.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stacks as stackmod

SCHEMA_VERSION = "0.2"


def read_local(root):
    """Le o .framework-version SO deste dir (nao sobe a arvore, ao contrario da
    porta): o init opera na raiz que o utilizador indicou."""
    path = os.path.join(root, ".framework-version")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def plan(root, forced):
    """Devolve (data, action, existing). data=None => recusa (legado, nao mexer)."""
    want = sorted(set(forced) | set(stackmod.detect(root)))
    existing = read_local(root)

    if existing is not None and existing.get("plugin") != "bulletproof":
        return None, "LEGADO", existing

    if existing is not None:  # gerido -> incremental (estende, nunca deita fora)
        merged = sorted(set(existing.get("stacks", [])) | set(want))
        data = {"framework": "bulletproof", "version": SCHEMA_VERSION,
                "plugin": "bulletproof", "status": existing.get("status", "bootstrapping"),
                "stacks": merged, "tiers": existing.get("tiers", [2])}
        return data, "ESTENDIDO", existing

    data = {"framework": "bulletproof", "version": SCHEMA_VERSION,
            "plugin": "bulletproof", "status": "bootstrapping",
            "stacks": want, "tiers": [2]}
    return data, "CRIADO", None


def main(argv):
    p = argparse.ArgumentParser(description="adota o projeto no Bulletproof (mecanico)")
    p.add_argument("dir", nargs="?", default=".")
    p.add_argument("--stack", action="append", default=[], dest="stacks")
    a = p.parse_args(argv)
    root = os.path.abspath(a.dir)

    if not os.path.isdir(root):
        print("framework-init: '%s' nao e um diretorio." % root)
        return 2

    data, action, _existing = plan(root, a.stacks)
    path = os.path.join(root, ".framework-version")

    if data is None:  # legado -> nao sobrescrever
        print("framework-init: ja existe um .framework-version SEM o marcador do plugin "
              "(legado) em %s." % path)
        print("Nao vou sobrescrever um setup proprio. Se queres mesmo adotar este projeto "
              "no plugin, faz backup/remove o ficheiro atual primeiro.")
        return 2

    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("Bulletproof: projeto %s." % ("estendido" if action == "ESTENDIDO" else "adotado (criado)"))
    print("  .framework-version: %s" % path)
    print("  status:  %s" % data["status"])
    print("  stacks:  %s" % (", ".join(data["stacks"]) if data["stacks"] else "(nenhum detetado)"))
    print("  tiers:   %s" % data["tiers"])
    if data["status"] == "bootstrapping":
        print("  proximo: Guia ativo; Exit Lock em ESPERA ate haver camada de testes verdes.")
        if not data["stacks"]:
            print("           nenhum stack detetado; passa --stack <s> ou adiciona um manifesto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
