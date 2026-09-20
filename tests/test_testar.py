#!/usr/bin/env python3
"""Prova do /testar (Fase 2, motor): corre a camada de testes, carimba verde (e
destranca o Exit Lock) ou regista test_red. Repos git reais; ledger/estado isolados.
Comandos de teste controlados (bash exit 0/1) para nao depender de runners instalados."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo: parent of tests/
SCRIPTS = os.path.join(PLUGIN, "scripts")
TESTAR = os.path.join(SCRIPTS, "testar.py")
GUARD = os.path.join(SCRIPTS, "exit-lock-guard.py")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FALHA", name))

root = os.path.realpath(tempfile.mkdtemp(prefix="bp-testar-"))
LEDGER = os.path.join(root, "ledger.jsonl")
STATE = os.path.join(root, "state")

def env():
    e = dict(os.environ)
    e["BULLETPROOF_LEDGER"] = LEDGER
    e["BULLETPROOF_STATE"] = STATE
    return e

def mk_repo(name, test_cmd, managed=True):
    repo = os.path.join(root, name)
    os.makedirs(repo, exist_ok=True)
    if managed:
        fv = {"framework": "bulletproof", "version": "0.2", "plugin": "bulletproof",
              "status": "active", "stacks": ["python"], "tiers": [1, 2],
              "tests": {"python": test_cmd}}
    else:
        fv = {"framework": "bulletproof", "version": "0.1", "tiers": [1, 2]}
    with open(os.path.join(repo, ".framework-version"), "w") as f:
        json.dump(fv, f)
    with open(os.path.join(repo, "app.py"), "w") as f:
        f.write("def add(a, b):\n    return a + b\n")
    for a in (["git", "init", "-q", repo], ["git", "-C", repo, "config", "user.email", "t@t"],
              ["git", "-C", repo, "config", "user.name", "t"], ["git", "-C", repo, "add", "-A"],
              ["git", "-C", repo, "commit", "-q", "-m", "init"]):
        subprocess.run(a, capture_output=True)
    return repo

def dirty(repo):
    with open(os.path.join(repo, "app.py"), "a") as f:
        f.write("\ndef sub(a, b):\n    return a - b\n")

def run_testar(repo):
    p = subprocess.run(["python3", TESTAR, repo], capture_output=True, text=True, env=env())
    return p.returncode, p.stdout + p.stderr

def run_guard(repo):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git -C %s commit -m x" % repo},
               "cwd": repo, "session_id": "s"}
    p = subprocess.run(["python3", GUARD], input=json.dumps(payload),
                       capture_output=True, text=True, env=env())
    return p.returncode, p.stderr

def ledger_lines():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER) as f:
        return [json.loads(l) for l in f if l.strip()]

print("\n[A] ciclo completo: codigo sujo -> bloqueia -> /testar verde -> destranca")
rA = mk_repo("green", "bash -c 'exit 0'")
dirty(rA)
rc, _ = run_guard(rA)
check("antes do testar: Exit Lock bloqueia (exit 2)", rc == 2)
rc, out = run_testar(rA)
check("/testar VERDE (rc0)", rc == 0 and "VERDE" in out)
check("ledger ganhou test_green", any(x["event"] == "test_green" for x in ledger_lines()))
rc, _ = run_guard(rA)
check("depois do testar: commit passa (exit 0)", rc == 0)

print("\n[B] testes falham -> VERMELHO, test_red, Exit Lock mantem-se")
rB = mk_repo("red", "bash -c 'exit 1'")
dirty(rB)
rc, out = run_testar(rB)
check("/testar VERMELHO (rc1)", rc == 1 and "VERMELHO" in out)
reds = [x for x in ledger_lines() if x["event"] == "test_red"]
check("ledger ganhou test_red (o bug apanhado), gate=testar", len(reds) == 1 and reds[0]["gate"] == "testar")
rc, _ = run_guard(rB)
check("Exit Lock continua a bloquear (nao carimbado) (exit 2)", rc == 2)

print("\n[C] projeto nao gerido -> /testar recusa")
rC = mk_repo("plain", "bash -c 'exit 0'", managed=False)
rc, out = run_testar(rC)
check("recusa (exit 2), manda correr framework-init", rc == 2 and "framework-init" in out)

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
