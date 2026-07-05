#!/usr/bin/env python3
"""fv.py -- a "porta" do plugin Bulletproof.

Le o .framework-version do projeto e decide se ESTE projeto e' gerido pelo
plugin. E' a invariante-mae: os hooks empacotados sao globais por natureza
(registados via ${CLAUDE_PLUGIN_ROOT}), mas so agem onde a porta abre. Um
.framework-version legado -- sem o marcador "plugin": "bulletproof", como o do
FA (v0.1) -- fecha a porta, e o hook ignora o projeto por completo.

Usado como modulo (`import fv; fv.managed_project(cwd)`) e standalone (debug:
`python3 fv.py [caminho]`). Fail-safe: qualquer duvida -> porta FECHADA (None).
"""
import json
import os

PLUGIN_ID = "bulletproof"
FRAMEWORK_FILE = ".framework-version"


def find_framework_file(start):
    """Sobe a partir de `start` a' procura do .framework-version.

    Fix FA: o repo git pode ser um subdir (platform/) com o .framework-version
    um nivel acima; por isso subimos a arvore em vez de olhar so para `start`.
    """
    cur = os.path.abspath(start)
    while True:
        cand = os.path.join(cur, FRAMEWORK_FILE)
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:  # cheguei a' raiz do disco
            return None
        cur = parent


def read_fv(start):
    """Devolve o dict do .framework-version mais proximo (subindo), ou None."""
    path = find_framework_file(start)
    if not path:
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def managed_project(start):
    """A PORTA. Devolve o dict do .framework-version se este projeto e' gerido
    pelo plugin (marcador "plugin" == PLUGIN_ID); senao None (porta fechada).
    """
    fv = read_fv(start)
    if fv is None:
        return None
    if fv.get("plugin") != PLUGIN_ID:
        return None
    return fv


def root_of(start):
    """A raiz do projeto gerido: o diretorio que contem o .framework-version."""
    path = find_framework_file(start)
    return os.path.dirname(path) if path else None


if __name__ == "__main__":
    import sys
    where = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    data = managed_project(where)
    if data is None:
        print("porta FECHADA (nao gerido pelo plugin): %s" % os.path.abspath(where))
        raise SystemExit(1)
    print("porta ABERTA (%s): %s" % (root_of(where), json.dumps(data)))
    raise SystemExit(0)
