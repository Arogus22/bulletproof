#!/usr/bin/env python3
"""Proof of the FULL FLOW: framework-init (bootstrapping) -> a green /testar PROMOTES to
'active' and arms the Exit Lock -> touch the code -> commit BLOCKS -> green /testar ->
commit passes. No hand-editing .framework-version anywhere. Real git repos; ledger and
state isolated."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo: parent of tests/
SCRIPTS = os.path.join(PLUGIN, "scripts")
INIT = os.path.join(SCRIPTS, "framework-init.py")
TESTAR = os.path.join(SCRIPTS, "testar.py")
GUARD = os.path.join(SCRIPTS, "exit-lock-guard.py")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FAIL", name))

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

# setup: git repo with app.py committed, adopted by the real script (mechanical -> bootstrapping)
repo = os.path.join(root, "proj")
os.makedirs(repo)
with open(os.path.join(repo, "app.py"), "w") as f:
    f.write("def add(a, b):\n    return a + b\n")
for a in (["git", "init", "-q", repo], ["git", "-C", repo, "config", "user.email", "t@t"],
          ["git", "-C", repo, "config", "user.name", "t"], ["git", "-C", repo, "add", "-A"],
          ["git", "-C", repo, "commit", "-q", "-m", "init"]):
    sh(a)
sh(["python3", INIT, repo, "--stack", "python"])  # creates .framework-version bootstrapping
# the mechanical init doesn't configure the test command; we set a controlled one
# (simulates the test layer existing), so /testar can get a real green
fvpath = os.path.join(repo, ".framework-version")
with open(fvpath) as f:
    fv = json.load(f)
fv["tests"] = {"python": "bash -c 'exit 0'"}
with open(fvpath, "w") as f:
    json.dump(fv, f, indent=2)
    f.write("\n")

print("\n[1] after framework-init -> status bootstrapping")
check("status == bootstrapping", status_of(repo) == "bootstrapping")

print("\n[2] in bootstrapping, the Exit Lock is ON HOLD")
with open(os.path.join(repo, "app.py"), "a") as f:
    f.write("\ndef sub(a, b):\n    return a - b\n")  # dirties the code
rc, _ = run_guard(repo)
check("dirty code commit PASSES (exit 0): lock on hold", rc == 0)

print("\n[3] /testar green -> PROMOTES to active (no hand-edit) + stamps")
rc, out = run_testar(repo)
check("/testar green (rc0)", rc == 0 and "GREEN" in out)
check("status automatically promoted to 'active'", status_of(repo) == "active")
check("reports the promotion", "active" in out)

print("\n[4] now active: touching the code and the commit BLOCKS")
with open(os.path.join(repo, "app.py"), "a") as f:
    f.write("\ndef mul(a, b):\n    return a * b\n")  # dirties it again, invalidates the green
rc, err = run_guard(repo)
check("Exit Lock blocks (exit 2)", rc == 2 and "BLOCKED" in err)

print("\n[5] /testar green again -> stamps the new state -> commit passes")
rc, out = run_testar(repo)
check("/testar green (rc0)", rc == 0)
check("stays active, no re-promotion (idempotent)", status_of(repo) == "active")
rc, _ = run_guard(repo)
check("commit passes (exit 0)", rc == 0)

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
