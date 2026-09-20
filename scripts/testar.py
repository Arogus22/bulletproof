#!/usr/bin/env python3
"""testar.py -- runs the project's test layer and stamps green if it passes.

Central piece of Bulletproof. It reads the stacks from .framework-version (or detects
them) and runs the test command of each one (override in
.framework-version["tests"][stack], otherwise a default per stack). Then:
  - all green    -> calls mark-green.sh (the Exit Lock now allows committing;
                    mark-green is the one that records the test_green in the ledger).
  - any one red  -> records test_red in the ledger (the failure/bug caught) and reports
                    it; does NOT stamp (the Exit Lock keeps blocking code commits).

Usage: python3 testar.py [dir]   (default: current directory)
It only acts on projects managed by the plugin (the gate, fv.py).
Env overrides (tests): BULLETPROOF_STATE, BULLETPROOF_LEDGER.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fv as gate
import stacks as stackmod

DEFAULT_TEST_CMD = {
    "python": "pytest -q",
    "node": "npm test",
    "go": "go test ./...",
    "rust": "cargo test",
    "ruby": "bundle exec rake test",
}


def fingerprint(root):
    try:
        return subprocess.run(["bash", os.path.join(HERE, "exit-lock-fp.sh"), root],
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def log_red(root, detail, seed):
    """Records the caught failure in the ledger. Best-effort, it never breaks."""
    try:
        import ledger
        ledger.record(event="test_red", gate="testar", project=root,
                      reason="tests_failed", incident_seed=seed, detail=detail)
    except Exception:
        pass


def promote_to_active(root):
    """On the first green, promotes the project from 'bootstrapping' to 'active' in the
    .framework-version, arming the Exit Lock. Idempotent (if already active, a no-op).
    Best-effort: if it fails, the green stamp happens all the same."""
    path = os.path.join(root, ".framework-version")
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("status") == "active":
            return False
        data["status"] = "active"
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return True
    except Exception:
        return False


def main(argv):
    # Claude Code runs this through a pipe, where Python would hold its own prints back
    # while the test command and mark-green.sh write straight through: the `>> [stack] cmd`
    # header landed after the output it announces. Line buffering keeps the order real.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    start = os.path.abspath(argv[0]) if argv else os.getcwd()
    fvdata = gate.managed_project(start)
    if fvdata is None:
        print("testar: this project is not adopted by Bulletproof. "
              "Run /bulletproof:framework-init first.")
        return 2

    root = gate.root_of(start) or start
    declared = fvdata.get("stacks") or stackmod.detect(root)
    overrides = fvdata.get("tests") if isinstance(fvdata.get("tests"), dict) else {}

    if not declared:
        print("testar: no stack declared or detected. Add one "
              "(/bulletproof:framework-init --stack <s>) or a manifest file.")
        return 2

    plan = []
    for s in declared:
        cmd = overrides.get(s) or DEFAULT_TEST_CMD.get(s)
        if cmd:
            plan.append((s, cmd))
        else:
            print("testar: warning, no test command for stack '%s' "
                  "(set one in .framework-version[\"tests\"][\"%s\"])." % (s, s))

    if not plan:
        print("testar: no test command to run.")
        return 2

    failures = []
    for s, cmd in plan:
        print(">> [%s] %s" % (s, cmd))
        if subprocess.run(cmd, shell=True, cwd=root).returncode != 0:
            failures.append({"stack": s, "cmd": cmd})

    if failures:
        log_red(root, {"failed": failures}, fingerprint(root))
        print("\ntestar: RED. %d of %d test suite(s) failed. Nothing stamped; the Exit "
              "Lock keeps blocking code commits. Fix it and run again."
              % (len(failures), len(plan)))
        return 1

    # green: promote to 'active' on the 1st green (arms the Exit Lock), stamp via mark-green
    promoted = promote_to_active(root)
    subprocess.run(["bash", os.path.join(HERE, "mark-green.sh"), root])
    print("\ntestar: GREEN. Every test suite passed. Green stamped; code commits are "
          "now allowed.")
    if promoted:
        print("  project promoted to 'active': the Exit Lock now polices code commits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
