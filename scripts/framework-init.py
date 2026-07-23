#!/usr/bin/env python3
"""framework-init.py -- adota um projeto no Bulletproof (Fase 2: deteta as capacidades
e propoe as camadas).

Cria (ou estende, idempotente) o .framework-version v0.3 na raiz do projeto, com o
marcador do plugin, o status, as camadas ativas (derivadas das capacidades detetadas),
os stacks, e a config por camada. Reporta os sinais detetados e as perguntas de
confirmacao sobre o que a detecao NAO consegue ver (o humano fecha os falsos negativos).

Uso: python3 framework-init.py [dir] [--stack S ...]

Recusa-se a sobrescrever um .framework-version LEGADO (sem o marcador do plugin).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stacks as stackmod
import capabilities as capmod

SCHEMA_VERSION = "0.3"
DEFAULT_CODE_RE = r"\.(ts|tsx|js|jsx|mjs|cjs|svelte|vue|sql|py|go|rs|rb|java|kt|php|cs)$"


def read_local(root):
    """Le o .framework-version SO deste dir (o init opera na raiz indicada)."""
    path = os.path.join(root, ".framework-version")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def build_config(caps):
    """Config por camada, conforme as capacidades detetadas."""
    cfg = {"code_re": DEFAULT_CODE_RE}
    if caps.get("deploy_sensitive"):
        cfg["deploy"] = {"protected_branch": "main",
                         "deploy_cmds": ["wrangler deploy", "wrangler pages deploy", "vercel"]}
    if caps.get("db"):
        cfg["prod_db"] = {"kind": "d1", "guard_remote_only": True}
    return cfg


def plan(root, forced):
    """Devolve (data, action, caps, signals). data=None => recusa (legado)."""
    stacks = sorted(set(forced) | set(stackmod.detect(root)))
    caps, signals = capmod.detect(root)
    layers = capmod.layers_for(caps)
    existing = read_local(root)

    if existing is not None and existing.get("plugin") != "bulletproof":
        return None, "LEGADO", caps, signals

    if existing is not None:  # incremental: estende stacks, mantem status, re-propoe camadas
        stacks = sorted(set(existing.get("stacks", [])) | set(stacks))
        status = existing.get("status", "bootstrapping")
        tests = existing.get("tests", {}) if isinstance(existing.get("tests"), dict) else {}
        action = "ESTENDIDO"
    else:
        status = "bootstrapping"
        tests = {}
        action = "CRIADO"

    data = {"framework": "bulletproof", "version": SCHEMA_VERSION, "plugin": "bulletproof",
            "status": status, "layers": layers, "stacks": stacks, "tests": tests,
            "config": build_config(caps)}
    return data, action, caps, signals


def main(argv):
    p = argparse.ArgumentParser(description="adota o projeto no Bulletproof")
    p.add_argument("dir", nargs="?", default=".")
    p.add_argument("--stack", action="append", default=[], dest="stacks")
    a = p.parse_args(argv)
    root = os.path.abspath(a.dir)

    if not os.path.isdir(root):
        print("framework-init: '%s' nao e um diretorio." % root)
        return 2

    data, action, caps, signals = plan(root, a.stacks)
    path = os.path.join(root, ".framework-version")

    if data is None:  # legado
        print("framework-init: ja existe um .framework-version SEM o marcador do plugin "
              "(legado) em %s." % path)
        print("Nao vou sobrescrever um setup proprio. Faz backup/remove o ficheiro atual "
              "primeiro se queres adotar este projeto no plugin.")
        return 2

    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("Bulletproof: projeto %s." % ("estendido" if action == "ESTENDIDO" else "adotado"))
    print("  .framework-version: %s" % path)
    print("  camadas propostas: %s" % data["layers"])
    print("  status:  %s" % data["status"])
    print("  stacks:  %s" % (", ".join(data["stacks"]) if data["stacks"] else "(nenhum)"))
    if signals:
        print("  capacidades detetadas:")
        for s in signals:
            print("   + %s" % s)
    qs = capmod.confirm_questions(caps)
    if qs:
        print("  CONFIRMA (o que nao consigo ver do repositorio):")
        for q in qs:
            print("   ? %s" % q)
    if data["status"] == "bootstrapping":
        print("  proximo: Guia ativo; Exit Lock em espera ate ao primeiro /testar verde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
