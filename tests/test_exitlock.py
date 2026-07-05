#!/usr/bin/env python3
"""Prova isolada do Exit Lock (Fase 1, tijolo 2): porta + bloqueio + carimbo verde
+ ledger. Repos git reais em temp; ledger e estado ISOLADOS por env override, nunca
tocam no estado real. Imprime so o veredito por caso."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = "/Users/arogus/Desktop/Claude_Playground/bulletproof-plugin"
SCRIPTS = os.path.join(PLUGIN, "scripts")
GUARD = os.path.join(SCRIPTS, "exit-lock-guard.py")
MARKGREEN = os.path.join(SCRIPTS, "mark-green.sh")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FALHA", name))

# realpath a' cabeca: em macOS o tempdir e' /var -> /private/var (symlink); resolver
# aqui garante que os caminhos batem com o que o git rev-parse devolve.
root = os.path.realpath(tempfile.mkdtemp(prefix="bp-exitlock-"))
LEDGER = os.path.join(root, "ledger.jsonl")
STATE = os.path.join(root, "state")

def env():
    e = dict(os.environ)
    e["BULLETPROOF_LEDGER"] = LEDGER
    e["BULLETPROOF_STATE"] = STATE
    return e

def sh(args):
    return subprocess.run(args, capture_output=True, text=True, env=env())

def mk_repo(name, managed=True, nest=None):
    """Repo git com app.py + README.md committed. Se nest, o .framework-version fica
    no dir PAI e o repo git e' o subdir (replica a topologia do FA)."""
    base = os.path.join(root, name)
    repo = os.path.join(base, nest) if nest else base
    os.makedirs(repo, exist_ok=True)
    fvdir = base if nest else repo
    if managed:
        fv = {"framework": "bulletproof", "version": "0.2", "plugin": "bulletproof",
              "status": "active", "stacks": ["python"], "tiers": [1, 2]}
    else:  # legado FA: v0.1 SEM o marcador "plugin"
        fv = {"framework": "bulletproof", "version": "0.1", "tiers": [1, 2]}
    with open(os.path.join(fvdir, ".framework-version"), "w") as f:
        json.dump(fv, f)
    with open(os.path.join(repo, "app.py"), "w") as f:
        f.write("def add(a, b):\n    return a + b\n")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("# projeto\n")
    for args in (["git", "init", "-q", repo],
                 ["git", "-C", repo, "config", "user.email", "t@t"],
                 ["git", "-C", repo, "config", "user.name", "t"],
                 ["git", "-C", repo, "add", "-A"],
                 ["git", "-C", repo, "commit", "-q", "-m", "init"]):
        sh(args)
    return repo

def dirty_code(repo):
    with open(os.path.join(repo, "app.py"), "a") as f:
        f.write("\ndef sub(a, b):\n    return a - b\n")

def dirty_docs(repo):
    with open(os.path.join(repo, "README.md"), "a") as f:
        f.write("\nmais docs\n")

def run_guard(repo, cmd=None, cwd=None):
    cmd = cmd if cmd is not None else ("git -C %s commit -m x" % repo)
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd},
               "cwd": cwd or repo, "session_id": "test-sess"}
    p = subprocess.run(["python3", GUARD], input=json.dumps(payload),
                       capture_output=True, text=True, env=env())
    return p.returncode, p.stderr

def ledger_lines():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER) as f:
        return [json.loads(l) for l in f if l.strip()]

print("\n[A] commit de codigo nao-verde num projeto gerido -> BLOQUEIA")
r1 = mk_repo("managed1"); dirty_code(r1)
rc, err = run_guard(r1)
check("bloqueia (exit 2)", rc == 2)
check("stderr diz BLOQUEADO", "BLOQUEADO" in err)
blocks = [x for x in ledger_lines() if x["event"] == "block"]
check("ledger ganhou 1 block", len(blocks) == 1)
check("block com gate=exit_lock e project certo",
      blocks and blocks[-1]["gate"] == "exit_lock" and os.path.basename(blocks[-1]["project"]) == "managed1")

print("\n[E] retry do mesmo commit nao-verde -> agrupa por incidente")
run_guard(r1)  # segunda tentativa, estado inalterado
blocks = [x for x in ledger_lines() if x["event"] == "block"]
check("2 blocks registados", len(blocks) == 2)
check("mesmo incident nos dois (retries agrupam, nao inflacionam)",
      blocks[0]["incident"] == blocks[1]["incident"])

print("\n[B] /testar carimba verde -> destranca")
mg = sh(["bash", MARKGREEN, r1])
check("mark-green ok", mg.returncode == 0 and "verde carimbado" in mg.stdout)
rc, err = run_guard(r1)
check("agora passa (exit 0)", rc == 0)
check("ledger ganhou 1 test_green", len([x for x in ledger_lines() if x["event"] == "test_green"]) == 1)

print("\n[C] repo legado do FA (sem marca) -> Exit Lock ignora, passa sempre")
r2 = mk_repo("legacy1", managed=False); dirty_code(r2)
n_before = len(ledger_lines())
rc, err = run_guard(r2)
check("passa (exit 0), porta fechada", rc == 0)
check("ledger intacto (nao gerido -> nao regista)", len(ledger_lines()) == n_before)

print("\n[D] commit so de docs num projeto gerido -> nao morde")
r3 = mk_repo("managed_docs"); dirty_docs(r3)
rc, err = run_guard(r3)
check("passa (exit 0), so docs", rc == 0)

print("\n[G] topologia FA: git em platform/, .framework-version um nivel acima")
rG = mk_repo("fa_like", nest="platform"); dirty_code(rG)
rc, err = run_guard(rG, cmd=("git -C %s commit -m x" % rG), cwd=rG)
check("porta sobe a arvore e o Exit Lock morde (exit 2)", rc == 2)

print("\n[F] fail-open")
rc, _ = run_guard(r3, cmd="git status")
check("nao-commit (git status) -> passa (exit 0)", rc == 0)
p = subprocess.run(["python3", GUARD], input="isto nao e json",
                   capture_output=True, text=True, env=env())
check("payload invalido -> passa (exit 0)", p.returncode == 0)

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
