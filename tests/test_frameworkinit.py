#!/usr/bin/env python3
"""Prova do /framework-init (Fase 2): cria/estende o .framework-version v0.3 com as
camadas derivadas das capacidades detetadas, idempotente/incremental, recusa legado."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo: parent of tests/
SCRIPTS = os.path.join(PLUGIN, "scripts")
INIT = os.path.join(SCRIPTS, "framework-init.py")
FV = os.path.join(SCRIPTS, "fv.py")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FALHA", name))

root = os.path.realpath(tempfile.mkdtemp(prefix="bp-init-"))

def run_init(d, *args):
    p = subprocess.run(["python3", INIT, d, *args], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr

def read_fv(d):
    with open(os.path.join(d, ".framework-version")) as f:
        return json.load(f)

def mkproj(name, files=()):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    if isinstance(files, dict):
        for rel, content in files.items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(content)
    else:
        for fn in files:
            open(os.path.join(d, fn), "w").close()
    return d

print("\n[1] projeto vazio -> v0.3, bootstrapping, camadas [1,2]")
d = mkproj("vazio")
rc, out = run_init(d)
fv = read_fv(d)
check("exit 0", rc == 0)
check("marcador do plugin", fv.get("plugin") == "bulletproof")
check("version 0.3", fv.get("version") == "0.3")
check("status bootstrapping", fv.get("status") == "bootstrapping")
check("camadas [1,2]", fv.get("layers") == [1, 2])
check("pergunta pelo que nao viu (CONFIRMA)", "CONFIRMA" in out)

print("\n[2] projeto Cloudflare + D1 -> camadas [1,2,3] + config")
d = mkproj("cf", {"api/wrangler.toml": "[[d1_databases]]\nbinding='DB'\n"})
rc, out = run_init(d)
fv = read_fv(d)
check("camadas [1,2,3]", fv.get("layers") == [1, 2, 3])
check("config.deploy presente", "deploy" in fv.get("config", {}))
check("config.prod_db kind=d1", fv.get("config", {}).get("prod_db", {}).get("kind") == "d1")

print("\n[3] deteta stack + --stack forcado")
d = mkproj("py", files=["pyproject.toml"])
run_init(d)
check("stack python", read_fv(d).get("stacks") == ["python"])
d = mkproj("forced")
run_init(d, "--stack", "node")
check("--stack node", read_fv(d).get("stacks") == ["node"])

print("\n[4] idempotente (2x nao muda)")
d = mkproj("idem", files=["go.mod"])
run_init(d); a = read_fv(d)
run_init(d); b = read_fv(d)
check("estavel entre corridas", a == b and b.get("stacks") == ["go"])

print("\n[5] incremental (novo manifesto estende stacks)")
d = mkproj("incr", files=["pyproject.toml"])
run_init(d)
check("arranca [python]", read_fv(d).get("stacks") == ["python"])
open(os.path.join(d, "package.json"), "w").close()
run_init(d)
check("estende [node, python]", read_fv(d).get("stacks") == ["node", "python"])

print("\n[6] a porta reconhece o v0.3 como gerido")
d = mkproj("porta")
run_init(d)
p = subprocess.run(["python3", FV, d], capture_output=True, text=True)
check("porta ABERTA", p.returncode == 0 and "ABERTA" in p.stdout)

print("\n[7] legado (sem marcador) -> recusa, nao sobrescreve")
d = mkproj("legado")
legacy = {"framework": "bulletproof", "version": "0.1", "tiers": [1, 2]}
with open(os.path.join(d, ".framework-version"), "w") as f:
    json.dump(legacy, f)
rc, out = run_init(d)
check("recusa (exit 2)", rc == 2)
check("ficheiro legado intacto", read_fv(d) == legacy)

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
