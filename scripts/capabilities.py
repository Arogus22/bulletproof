#!/usr/bin/env python3
"""capabilities.py -- deteta as capacidades de um projeto a partir dos sinais no
repositorio, para decidir que camadas do Bulletproof se ligam. Partilhado pelo
framework-init (propor na adocao) e pelo Guia (avisar drift de capacidades).

Capacidades: db, deploy_sensitive, staging. Cada uma vem de sinais de FICHEIRO
(evidencia do projeto, nao do ambiente global). A deteccao devolve tambem os sinais
encontrados (para mostrar ao humano) e as perguntas de confirmacao sobre o que a
deteccao NAO consegue ver do repositorio (para apanhar falsos negativos).
"""
import os
import re

SKIP_DIRS = {"node_modules", ".git", ".wrangler", "dist", "build", ".svelte-kit", ".next"}


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def _walk_find(root, names, depth=3):
    """Caminhos de quaisquer `names` (ficheiro ou dir) ate `depth` niveis abaixo de
    root, ignorando node_modules/.git/etc. (o codigo pode viver num subdir, ex.: o
    Dashboard tem o wrangler.toml em dashboard/api/)."""
    found = []
    root = os.path.abspath(root)
    wanted = set(names)
    for dirpath, dirs, files in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        d = 0 if rel == "." else rel.count(os.sep) + 1
        if d >= depth:
            dirs[:] = []
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for n in wanted:
            if n in files or n in dirs:
                found.append(os.path.join(dirpath, n))
    return found


def detect(root):
    """Devolve (caps: dict[str,bool], signals: list[str])."""
    caps = {"db": False, "deploy_sensitive": False, "staging": False}
    signals = []

    for w in _walk_find(root, ["wrangler.toml", "wrangler.jsonc", "wrangler.json"]):
        rel = os.path.relpath(w, root)
        caps["deploy_sensitive"] = True
        signals.append("deploy: Cloudflare (%s)" % rel)
        content = _read(w)
        if re.search(r"d1_databases", content, re.I):
            caps["db"] = True
            signals.append("db: Cloudflare D1 (%s)" % rel)
        if re.search(r"\[env\.staging\]|\[env\.preview\]", content, re.I):
            caps["staging"] = True
            signals.append("staging: [env.staging] (%s)" % rel)

    for marker in ["drizzle.config.ts", "supabase", "prisma", "migrations"]:
        hit = _walk_find(root, [marker])
        if hit:
            caps["db"] = True
            signals.append("db: %s" % marker)
            break

    if _walk_find(root, ["vercel.json"], depth=2):
        caps["deploy_sensitive"] = True
        signals.append("deploy: Vercel (vercel.json)")

    gh = os.path.join(root, ".github", "workflows")
    if os.path.isdir(gh):
        try:
            if any(re.search(r"deploy|pages|publish|release", f, re.I) for f in os.listdir(gh)):
                caps["deploy_sensitive"] = True
                signals.append("deploy: workflow in .github/workflows")
        except Exception:
            pass

    if _walk_find(root, [".env.staging"]):
        caps["staging"] = True
        signals.append("staging: .env.staging")

    return caps, signals


def layers_for(caps):
    """Capacidades -> camadas ATIVAS nesta fase. 1-2 sempre; 3 se ha deploy sensivel
    ou BD de prod. (Camadas 4 staging e 5 invariantes sao Fase 3, nao se ligam ainda.)"""
    layers = [1, 2]
    if caps.get("db") or caps.get("deploy_sensitive"):
        layers.append(3)
    return layers


def confirm_questions(caps):
    """Perguntas sobre o que a deteccao NAO viu, para o humano confirmar na adocao
    (apanha falsos negativos: uma guarda que devia existir e nao apareceu)."""
    qs = []
    if not caps.get("deploy_sensitive"):
        qs.append("I found no production deploy. Does this project publish anywhere "
                  "(a push that reaches production, a manual deploy)?")
    if not caps.get("db"):
        qs.append("I found no production database. Does this project write to a real "
                  "database (through something that leaves no trace in the repository)?")
    return qs


if __name__ == "__main__":
    import json
    import sys
    where = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    caps, signals = detect(where)
    print(json.dumps({"capabilities": caps, "layers": layers_for(caps),
                      "signals": signals, "confirm": confirm_questions(caps)},
                     indent=2, ensure_ascii=False))
