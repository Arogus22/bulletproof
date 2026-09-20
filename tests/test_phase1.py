#!/usr/bin/env python3
"""Isolated proof of Phase 1 (skeleton + gate + Guide). Builds fixtures in an isolated
temp dir and checks the gate (fv.py) and the Guide (framework-guide.py) without
installing the plugin. Prints only the verdict per case."""
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
    print("  %s  %s" % ("PASS" if cond else "FAIL", name))

# tempfile default (/var/folders) -> isolated, no .framework-version above, so the
# "climb the tree" proof doesn't pick up a framework from a parent project.
root = tempfile.mkdtemp(prefix="bp-phase1-")

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
legacy = mk("legacy-setup", {"framework": "bulletproof", "version": "0.1", "tiers": [1, 2]})
plain = mk("plain-project")  # no .framework-version
subdir = os.path.join(active, "platform")  # climb the tree from a subdir
os.makedirs(subdir, exist_ok=True)
# managed active with layers [1,2] but a new D1 signal -> capability drift
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

print("\n[1] Gate (fv.py)")
rc, out = run_fv(boot);    check("managed bootstrapping -> gate OPEN (rc0)", rc == 0 and "OPEN" in out)
rc, out = run_fv(active);  check("managed active -> gate OPEN (rc0)", rc == 0 and "OPEN" in out)
rc, out = run_fv(legacy);  check("legacy setup (v0.1, no marker) -> gate CLOSED (rc1)", rc == 1 and "CLOSED" in out)
rc, out = run_fv(plain);   check("no .framework-version -> gate CLOSED (rc1)", rc == 1 and "CLOSED" in out)
rc, out = run_fv(subdir);  check("subdir platform/ -> climbs the tree, gate OPEN (rc0)", rc == 0 and "OPEN" in out)

print("\n[2] Guide (framework-guide.py)")
rc, out = run_guide(boot)
ok = rc == 0 and out != "" and "green" in out and "framework-init" in out
check("bootstrapping -> warns to get the first green + framework-init", ok)
try:
    j = json.loads(out); has_ctx = "additionalContext" in j.get("hookSpecificOutput", {})
except Exception:
    has_ctx = False
check("bootstrapping -> output is valid SessionStart JSON", has_ctx)

rc, out = run_guide(active)
ok = (rc == 0 and "policing" in out and "python" in out and "drift" not in out
      and "new capability" not in out)
check("active (stack matches) -> Exit Lock policing, no warnings", ok)

rc, out = run_guide(drift)
ok = rc == 0 and "Stack drift" in out and "node" in out
check("active + undeclared stack manifest -> stack drift (node)", ok)

rc, out = run_guide(capdrift)
ok = rc == 0 and "new capability" in out and "3" in out
check("active + new capability (D1) -> warns layer 3 is not wired up", ok)

rc, out = run_guide(plain)
check("unmanaged (no marker) -> total SILENCE (no output, rc0)", rc == 0 and out == "")

rc, out = run_guide(legacy)
check("legacy setup -> total SILENCE (the plugin ignores it, rc0)", rc == 0 and out == "")

shutil.rmtree(root, ignore_errors=True)
n_pass = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n_pass, len(results)))
raise SystemExit(0 if n_pass == len(results) else 1)
