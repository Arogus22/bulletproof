#!/usr/bin/env python3
"""Proof of /testar: runs the test layer, stamps green (and unlocks the Exit Lock) or
logs test_red. Real git repos; ledger and state isolated. Controlled test commands
(bash exit 0/1) so it doesn't depend on installed runners."""
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
    print("  %s  %s" % ("PASS" if cond else "FAIL", name))

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

print("\n[A] full cycle: dirty code -> blocks -> /testar green -> unlocks")
rA = mk_repo("green", "bash -c 'exit 0'")
dirty(rA)
rc, _ = run_guard(rA)
check("before testar: Exit Lock blocks (exit 2)", rc == 2)
rc, out = run_testar(rA)
check("/testar GREEN (rc0)", rc == 0 and "GREEN" in out)
check("ledger gained test_green", any(x["event"] == "test_green" for x in ledger_lines()))
rc, _ = run_guard(rA)
check("after testar: commit passes (exit 0)", rc == 0)

print("\n[B] tests fail -> RED, test_red, Exit Lock stays in place")
rB = mk_repo("red", "bash -c 'exit 1'")
dirty(rB)
rc, out = run_testar(rB)
check("/testar RED (rc1)", rc == 1 and "RED" in out)
reds = [x for x in ledger_lines() if x["event"] == "test_red"]
check("ledger gained test_red (the caught bug), gate=testar", len(reds) == 1 and reds[0]["gate"] == "testar")
rc, _ = run_guard(rB)
check("Exit Lock keeps blocking (not stamped) (exit 2)", rc == 2)

print("\n[B2] piped output reads in the order things happened")
# covers: scripts/testar.py main -- Claude Code always runs this through a pipe, where
# Python buffers its own prints while the test command and mark-green.sh write straight
# through: the `>> [stack] cmd` header used to show up AFTER the output it announces.
rO = mk_repo("order", "bash -c 'echo SUITE-OUTPUT-MARKER'")
dirty(rO)
p = subprocess.run(["python3", TESTAR, rO], capture_output=True, text=True, env=env())
o = p.stdout
pos = [o.find(x) for x in (">> [python]", "SUITE-OUTPUT-MARKER", "green stamped", "testar: GREEN")]
check("header, then the suite's output, then the stamp, then the verdict",
      all(x >= 0 for x in pos) and pos == sorted(pos))

print("\n[C] unmanaged project -> /testar refuses")
rC = mk_repo("plain", "bash -c 'exit 0'", managed=False)
rc, out = run_testar(rC)
check("refuses (exit 2), tells you to run framework-init", rc == 2 and "framework-init" in out)

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
