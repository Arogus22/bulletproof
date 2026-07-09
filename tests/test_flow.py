#!/usr/bin/env python3
"""Prova do FLUXO COMPLETO (Fase 1, pos-revisao CE): framework-init (bootstrapping)
-> /testar verde PROMOVE 'active' e arma o Exit Lock -> mexer no codigo -> commit
BLOQUEIA -> /testar verde -> commit passa. Sem editar o .framework-version a' mao
em lado nenhum. Repos git reais; ledger/estado isolados."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = "/Users/arogus/Desktop/Claude_Playground/bulletproof-plugin"
SCRIPTS = os.path.join(PLUGIN, "scripts")
INIT = os.path.join(SCRIPTS, "framework-init.py")
TESTAR = os.path.join(SCRIPTS, "testar.py")
GUARD = os.path.join(SCRIPTS, "exit-lock-guard.py")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FALHA", name))

root = os.path.realpath(tempfile.mkdtemp(prefix="bp-flow-"))
LEDGER = os.path.join(root, "ledger.jsonl")
STATE = os.path.join(root, "state")

def env():
    e = dict(os.environ)
    e["BULLETPROOF_LEDGER"] = LEDGER
    e["BULLETPROOF_STATE"] = STATE
    return e

def sh(args):
    return subprocess.run(args, capture_output=True, text=True, env=env())

def status_of(repo):
    with open(os.path.join(repo, ".framework-version")) as f:
        return json.load(f).get("status")

def run_testar(repo):
    p = sh(["python3", TESTAR, repo])
    return p.returncode, p.stdout + p.stderr

def run_guard(repo):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git -C %s commit -m x" % repo},
               "cwd": repo, "session_id": "s"}
    p = subprocess.run(["python3", GUARD], input=json.dumps(payload),
                       capture_output=True, text=True, env=env())
    return p.returncode, p.stderr

# setup: repo git com app.py committed, adotado pelo script real (mecanico -> bootstrapping)
repo = os.path.join(root, "proj")
os.makedirs(repo)
with open(os.path.join(repo, "app.py"), "w") as f:
    f.write("def add(a, b):\n    return a + b\n")
for a in (["git", "init", "-q", repo], ["git", "-C", repo, "config", "user.email", "t@t"],
          ["git", "-C", repo, "config", "user.name", "t"], ["git", "-C", repo, "add", "-A"],
          ["git", "-C", repo, "commit", "-q", "-m", "init"]):
    sh(a)
sh(["python3", INIT, repo, "--stack", "python"])  # cria .framework-version bootstrapping
# o init mecanico nao configura o comando de teste; fixamos um controlado (simula a
# camada de testes existir), para o /testar ter um verde real
fvpath = os.path.join(repo, ".framework-version")
with open(fvpath) as f:
    fv = json.load(f)
fv["tests"] = {"python": "bash -c 'exit 0'"}
with open(fvpath, "w") as f:
    json.dump(fv, f, indent=2)
    f.write("\n")

print("\n[1] apos framework-init -> status bootstrapping")
check("status == bootstrapping", status_of(repo) == "bootstrapping")

print("\n[2] em bootstrapping, o Exit Lock esta EM ESPERA")
with open(os.path.join(repo, "app.py"), "a") as f:
    f.write("\ndef sub(a, b):\n    return a - b\n")  # suja o codigo
rc, _ = run_guard(repo)
check("commit de codigo sujo PASSA (exit 0): lock em espera", rc == 0)

print("\n[3] /testar verde -> PROMOVE a active (sem hand-edit) + carimba")
rc, out = run_testar(repo)
check("/testar verde (rc0)", rc == 0 and "VERDE" in out)
check("status promovido a 'active' automaticamente", status_of(repo) == "active")
check("reporta a promocao", "active" in out)

print("\n[4] agora active: mexer no codigo e o commit BLOQUEIA")
with open(os.path.join(repo, "app.py"), "a") as f:
    f.write("\ndef mul(a, b):\n    return a * b\n")  # suja de novo, invalida o verde
rc, err = run_guard(repo)
check("Exit Lock bloqueia (exit 2)", rc == 2 and "BLOQUEADO" in err)

print("\n[5] /testar verde de novo -> carimba o novo estado -> commit passa")
rc, out = run_testar(repo)
check("/testar verde (rc0)", rc == 0)
check("continua active, sem re-promover (idempotente)", status_of(repo) == "active")
rc, _ = run_guard(repo)
check("commit passa (exit 0)", rc == 0)

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
