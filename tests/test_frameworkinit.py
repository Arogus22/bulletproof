#!/usr/bin/env python3
"""Prova do /framework-init mecanico: cria/estende o .framework-version v0.2 com o
marcador, deteta stacks, e' idempotente/incremental, e recusa-se a tocar num legado."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = "/Users/arogus/Desktop/Claude_Playground/bulletproof-plugin"
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
    for fn in files:
        open(os.path.join(d, fn), "w").close()
    return d

print("\n[1] projeto vazio -> cria bootstrapping, sem stacks")
d = mkproj("vazio")
rc, out = run_init(d)
fv = read_fv(d)
check("exit 0", rc == 0)
check("marcador do plugin presente", fv.get("plugin") == "bulletproof")
check("version 0.2", fv.get("version") == "0.2")
check("status bootstrapping", fv.get("status") == "bootstrapping")
check("stacks vazio", fv.get("stacks") == [])
check("tiers [2] (Guia; Exit Lock em espera)", fv.get("tiers") == [2])

print("\n[2] projeto com pyproject.toml -> deteta python")
d = mkproj("py", files=["pyproject.toml"])
run_init(d)
check("stacks = [python]", read_fv(d).get("stacks") == ["python"])

print("\n[3] --stack forcado")
d = mkproj("forced")
run_init(d, "--stack", "node")
check("stacks = [node]", read_fv(d).get("stacks") == ["node"])

print("\n[4] idempotente (correr 2x nao muda)")
d = mkproj("idem", files=["go.mod"])
run_init(d); first = read_fv(d)
run_init(d); second = read_fv(d)
check("conteudo estavel entre corridas", first == second and second.get("stacks") == ["go"])

print("\n[5] incremental (novo manifesto -> estende stacks, nunca deita fora)")
d = mkproj("incr", files=["pyproject.toml"])
run_init(d)
check("arranca [python]", read_fv(d).get("stacks") == ["python"])
open(os.path.join(d, "package.json"), "w").close()  # aparece node
run_init(d)
check("estende para [node, python]", read_fv(d).get("stacks") == ["node", "python"])

print("\n[6] a porta reconhece o ficheiro criado como gerido")
d = mkproj("porta")
run_init(d)
p = subprocess.run(["python3", FV, d], capture_output=True, text=True)
check("fv.py -> porta ABERTA (rc0)", p.returncode == 0 and "ABERTA" in p.stdout)

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
