#!/usr/bin/env python3
"""Prova isolada da Fase 1 (esqueleto + porta + Guia). Monta fixtures numa dir
temporaria isolada e verifica a porta (fv.py) e o Guia (framework-guide.py) sem
instalar o plugin. Imprime so o veredito por caso."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo: parent of tests/
SCRIPTS = os.path.join(PLUGIN, "scripts")
FV = os.path.join(SCRIPTS, "fv.py")
GUIDE = os.path.join(SCRIPTS, "framework-guide.py")

results = []
def check(name, cond):
    results.append((name, cond))
    print("  %s  %s" % ("PASS" if cond else "FALHA", name))

# tempfile default (/var/folders) -> isolado, sem .framework-version acima, para
# a prova de "subir a arvore" nao apanhar um framework de um projeto pai.
root = tempfile.mkdtemp(prefix="bp-fase1-")

def mk(rel, fv=None, extra_files=()):
    d = os.path.join(root, rel)
    os.makedirs(d, exist_ok=True)
    if fv is not None:
        with open(os.path.join(d, ".framework-version"), "w") as f:
            json.dump(fv, f)
    for fn in extra_files:
        open(os.path.join(d, fn), "w").close()
    return d

# fixtures
boot = mk("managed-bootstrapping", {"framework": "bulletproof", "version": "0.2",
          "plugin": "bulletproof", "status": "bootstrapping", "stacks": [], "tiers": [2]})
active = mk("managed-active", {"framework": "bulletproof", "version": "0.2",
           "plugin": "bulletproof", "status": "active", "stacks": ["python"], "tiers": [1, 2]},
           extra_files=["pyproject.toml"])
drift = mk("managed-active-drift", {"framework": "bulletproof", "version": "0.2",
          "plugin": "bulletproof", "status": "active", "stacks": ["python"], "tiers": [1, 2]},
          extra_files=["pyproject.toml", "package.json"])
legacy = mk("legacy-fa", {"framework": "bulletproof", "version": "0.1", "tiers": [1, 2]})
plain = mk("plain-project")  # sem .framework-version
subdir = os.path.join(active, "platform")  # subir a arvore a partir de um subdir
os.makedirs(subdir, exist_ok=True)
# gerido active com layers [1,2] mas um sinal de D1 novo -> drift de capacidade
capdrift = mk("managed-cap-drift", {"framework": "bulletproof", "version": "0.3",
             "plugin": "bulletproof", "status": "active", "layers": [1, 2], "stacks": ["node"]})
with open(os.path.join(capdrift, "wrangler.toml"), "w") as f:
    f.write("[[d1_databases]]\nbinding='DB'\n")

def run_fv(path):
    p = subprocess.run(["python3", FV, path], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)

def run_guide(cwd):
    p = subprocess.run(["python3", GUIDE], input=json.dumps({"cwd": cwd}),
                       capture_output=True, text=True)
    return p.returncode, p.stdout.strip()

print("\n[1] Porta (fv.py)")
rc, out = run_fv(boot);    check("gerido bootstrapping -> porta ABERTA (rc0)", rc == 0 and "OPEN" in out)
rc, out = run_fv(active);  check("gerido active -> porta ABERTA (rc0)", rc == 0 and "OPEN" in out)
rc, out = run_fv(legacy);  check("legado FA (v0.1, sem marca) -> porta FECHADA (rc1)", rc == 1 and "CLOSED" in out)
rc, out = run_fv(plain);   check("sem .framework-version -> porta FECHADA (rc1)", rc == 1 and "CLOSED" in out)
rc, out = run_fv(subdir);  check("subdir platform/ -> sobe a arvore, porta ABERTA (rc0)", rc == 0 and "OPEN" in out)

print("\n[2] Guia (framework-guide.py)")
rc, out = run_guide(boot)
ok = rc == 0 and out != "" and "green" in out and "framework-init" in out
check("bootstrapping -> avisa p/ primeiro verde + framework-init", ok)
try:
    j = json.loads(out); has_ctx = "additionalContext" in j.get("hookSpecificOutput", {})
except Exception:
    has_ctx = False
check("bootstrapping -> output e' JSON valido de SessionStart", has_ctx)

rc, out = run_guide(active)
ok = (rc == 0 and "policing" in out and "python" in out and "drift" not in out
      and "new capability" not in out)
check("active (stack bate certo) -> Exit Lock a policiar, sem avisos", ok)

rc, out = run_guide(drift)
ok = rc == 0 and "Stack drift" in out and "node" in out
check("active + manifesto de stack nao declarado -> drift de stack (node)", ok)

rc, out = run_guide(capdrift)
ok = rc == 0 and "new capability" in out and "3" in out
check("active + capacidade nova (D1) -> avisa camada 3 por ligar", ok)

rc, out = run_guide(plain)
check("nao-gerido (sem marca) -> SILENCIO total (sem output, rc0)", rc == 0 and out == "")

rc, out = run_guide(legacy)
check("legado FA -> SILENCIO total (o plugin ignora-o, rc0)", rc == 0 and out == "")

shutil.rmtree(root, ignore_errors=True)
n_pass = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n_pass, len(results)))
raise SystemExit(0 if n_pass == len(results) else 1)
