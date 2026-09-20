#!/usr/bin/env python3
"""capabilities.py -- detects a project's capabilities from the signals in the
repository, to decide which Bulletproof layers get switched on. Shared by
framework-init (to propose them on adoption) and by the Guide (to warn about
capability drift).

Capabilities: db, deploy_sensitive, staging. Each one comes from FILE signals
(evidence from the project, not from the global environment). Detection also returns
the signals it found (to show the human) and the confirmation questions about what
detection CANNOT see from the repository (to catch false negatives).
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
    """Paths of any of `names` (file or dir) down to `depth` levels below root,
    ignoring node_modules/.git/etc. (the code can live in a subdir: a real monorepo
    keeps its wrangler.toml in dashboard/api/)."""
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
    """Returns (caps: dict[str,bool], signals: list[str])."""
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
    """Capabilities -> the layers that are ACTIVE today. 1-2 always; 3 if there is a
    sensitive deploy or a production database. (Layer 4, staging-first, and layer 5,
    invariants, are planned and not switched on yet.)"""
    layers = [1, 2]
    if caps.get("db") or caps.get("deploy_sensitive"):
        layers.append(3)
    return layers


def confirm_questions(caps):
    """Questions about what detection did NOT see, for the human to confirm on
    adoption (catches false negatives: a guard that should exist and did not show up)."""
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
