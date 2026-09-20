#!/usr/bin/env python3
"""Proof of capability detection (Phase 2): repository signals -> capabilities ->
layers. Isolated fixtures only, including one shaped like a real adopted monorepo."""
import os
import shutil
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo: parent of tests/
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
import capabilities as cap

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FALHA", name))

root = os.path.realpath(tempfile.mkdtemp(prefix="bp-caps-"))

def mk(name, files):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    for rel, content in files.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
    return d

print("\n[1] wrangler + D1 -> db + deploy, camadas [1,2,3]")
d = mk("cf-d1", {"api/wrangler.toml": '[[d1_databases]]\nbinding = "DB"\ndatabase_name = "x"\n', "app.ts": "x"})
caps, sig = cap.detect(d)
check("db detetado", caps["db"])
check("deploy detetado", caps["deploy_sensitive"])
check("staging nao", not caps["staging"])
check("layers [1,2,3]", cap.layers_for(caps) == [1, 2, 3])

print("\n[2] projeto vazio (so codigo) -> [1,2], pergunta pelo que nao viu")
d = mk("plain", {"app.py": "print(1)\n"})
caps, _ = cap.detect(d)
check("nada detetado", not any(caps.values()))
check("layers [1,2]", cap.layers_for(caps) == [1, 2])
check("2 perguntas de confirmacao (deploy + BD)", len(cap.confirm_questions(caps)) == 2)

print("\n[3] drizzle.config.ts -> db")
check("db por drizzle", cap.detect(mk("drz", {"drizzle.config.ts": "export default {}\n"}))[0]["db"])

print("\n[4] supabase/ -> db")
check("db por supabase/", cap.detect(mk("sb", {"supabase/config.toml": "x\n"}))[0]["db"])

print("\n[5] vercel.json -> deploy")
check("deploy por vercel", cap.detect(mk("vc", {"vercel.json": "{}\n"}))[0]["deploy_sensitive"])

print("\n[6] .env.staging -> staging")
d = mk("stg", {"wrangler.toml": "name='x'\n"})
open(os.path.join(d, ".env.staging"), "w").close()
check("staging detetado", cap.detect(d)[0]["staging"])

print("\n[7] deteta em subdir (nao so na raiz)")
caps, _ = cap.detect(mk("nested", {"packages/api/wrangler.toml": "[[d1_databases]]\n"}))
check("db+deploy num subdir", caps["db"] and caps["deploy_sensitive"])

print("\n[8] ignora node_modules")
caps, _ = cap.detect(mk("nm", {"node_modules/foo/wrangler.toml": "[[d1_databases]]\n", "app.py": "x"}))
check("nao apanha wrangler em node_modules", not caps["deploy_sensitive"])

print("\n[9] real-world shape: a monorepo with the worker two levels down (api + frontend)")
# The layout of the first project that adopted the plugin, rebuilt as a fixture so the
# proof runs on any machine: nothing at the root, a Cloudflare Worker with D1 and drizzle
# in app/api/, a separate frontend in app/frontend/.
mono = mk("monorepo", {
    "README.md": "# monorepo\n",
    "app/api/wrangler.toml": ('name = "api"\nmain = "src/index.ts"\n\n[[d1_databases]]\n'
                              'binding = "DB"\ndatabase_name = "app-db"\n'),
    "app/api/drizzle.config.ts": 'export default { dialect: "sqlite", driver: "d1-http" }\n',
    "app/api/package.json": '{"scripts": {"deploy": "wrangler deploy", "test": "vitest run"}}\n',
    "app/api/src/index.ts": "export default {}\n",
    "app/frontend/package.json": '{"scripts": {"build": "vite build", "test": "vitest run"}}\n',
    "app/frontend/src/main.ts": "export {}\n",
})
caps, sig = cap.detect(mono)
check("db (D1) detected", caps["db"])
check("deploy (Cloudflare) detected", caps["deploy_sensitive"])
check("proposed layers = [1,2,3]", cap.layers_for(caps) == [1, 2, 3])
print("     signals:", " | ".join(sig))

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
