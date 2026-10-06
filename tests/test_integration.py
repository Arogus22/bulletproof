#!/usr/bin/env python3
"""Proof of INTEGRATION of the wiring: simulates what Claude Code does when it loads
the plugin, reads hooks/hooks.json, resolves ${CLAUDE_PLUGIN_ROOT}, and invokes each
hook with the payload CC would send (and CLAUDE_PLUGIN_ROOT in the environment). Proves
the hooks.json config is correct (paths resolve, matchers filter, scripts respond),
without needing to run the `claude` CLI. Ledger and state isolated."""
import json
import os
import re
import shutil
import subprocess
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo: parent of tests/
HOOKS = os.path.join(PLUGIN, "hooks", "hooks.json")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FAIL", name))

root = os.path.realpath(tempfile.mkdtemp(prefix="bp-integ-"))
LEDGER = os.path.join(root, "ledger.jsonl")
STATE = os.path.join(root, "state")

def env():
    e = dict(os.environ)
    e["CLAUDE_PLUGIN_ROOT"] = PLUGIN  # how CC exports it when running the hook
    e["BULLETPROOF_LEDGER"] = LEDGER
    e["BULLETPROOF_STATE"] = STATE
    return e

def resolve(tok):
    return tok.replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN)

def hooks_for(event, tool=None):
    """Extracts from hooks.json the commands (shell command resolved) of an event,
    filtering by matcher the way CC would."""
    cfg = json.load(open(HOOKS))["hooks"].get(event, [])
    out = []
    for group in cfg:
        matcher = group.get("matcher")
        if tool is not None and matcher not in (None, "", tool) and not re.search(matcher, tool):
            continue
        for h in group.get("hooks", []):
            out.append(h["command"])
    return out

def run_event(event, payload, tool=None):
    argv = hooks_for(event, tool)[0]
    p = subprocess.run(argv, shell=True, input=json.dumps(payload), capture_output=True, text=True, env=env())
    return p.returncode, p.stdout, p.stderr

def mk_managed_repo():
    d = os.path.join(root, "proj")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".framework-version"), "w") as f:
        json.dump({"framework": "bulletproof", "version": "0.2", "plugin": "bulletproof",
                   "status": "active", "stacks": ["python"], "tiers": [1, 2]}, f)
    with open(os.path.join(d, "app.py"), "w") as f:
        f.write("x = 1\n")
    for a in (["git", "init", "-q", d], ["git", "-C", d, "config", "user.email", "t@t"],
              ["git", "-C", d, "config", "user.name", "t"], ["git", "-C", d, "add", "-A"],
              ["git", "-C", d, "commit", "-q", "-m", "init"]):
        subprocess.run(a, capture_output=True)
    with open(os.path.join(d, "app.py"), "a") as f:
        f.write("y = 2\n")  # dirties the code
    return d

print("\n[1] hooks.json well formed, with both events and the path variable")
cfg = json.load(open(HOOKS))["hooks"]
check("SessionStart registered", "SessionStart" in cfg)
check("PreToolUse registered", "PreToolUse" in cfg)
check("paths via ${CLAUDE_PLUGIN_ROOT}", "${CLAUDE_PLUGIN_ROOT}" in open(HOOKS).read())
_raw = open(HOOKS).read()
check("guards registered (exit-lock + deploy + db)",
      all(s in _raw for s in ["exit-lock-guard", "deploy-guard", "db-guard"]))

proj = mk_managed_repo()

print("\n[2] SessionStart (Guide) through the wiring -> resolves and injects context")
rc, out, err = run_event("SessionStart", {"cwd": proj})
ctx = ""
try:
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
except Exception:
    pass
check("resolves the path and runs (rc0)", rc == 0)
check("injects Bulletproof context (active)", "[Bulletproof]" in ctx and "policing" in ctx)

print("\n[3] PreToolUse (Exit Lock) through the wiring -> blocks non-green commit")
rc, out, err = run_event("PreToolUse",
    {"tool_name": "Bash", "tool_input": {"command": "git -C %s commit -m x" % proj},
     "cwd": proj, "session_id": "s"}, tool="Bash")
check("Exit Lock bites (exit 2)", rc == 2)
check("BLOCKED message in stderr", "BLOCKED" in err)

print("\n[4] matcher: PreToolUse 'Bash' doesn't match another tool (e.g. Edit)")
check("an Edit would not trigger the Exit Lock", hooks_for("PreToolUse", tool="Edit") == [])

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
