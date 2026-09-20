#!/usr/bin/env python3
"""SessionStart hook -- Bulletproof, layer 2 (the Guide), plugin version.

Injects context at session start ONLY in projects managed by the plugin (decided
by the gate, fv.py). In a project that is not managed (a legacy setup, or any
other project of the user's) it stays completely quiet (exit 0, no output). It
NEVER blocks: it is a guide, not a policeman. Fail-open: any error -> exit 0.

Reads the v0.2 schema of the .framework-version: `status` (bootstrapping|active)
and `stacks`. In bootstrapping (stack still undecided, no tests) it says to run
/bulletproof:framework-init; in active it confirms the Exit Lock and gives a
simple drift warning.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fv as gate  # the marker gate
import stacks as stackmod  # stack detection
import capabilities as capmod  # capability detection (layer drift)


def message(fvdata, root):
    status = fvdata.get("status", "active")
    stacks = fvdata.get("stacks", []) or []
    layers = gate.layers_of(fvdata)

    if status == "bootstrapping":
        return ("Framework adopted (layers %s), NO green yet. Run /bulletproof:testar; on the "
                "first green the project becomes 'active' and the Exit Lock arms itself. Until "
                "then code commits are not blocked. (Missing the stack or the tests? Run "
                "/bulletproof:framework-init.)" % layers)

    parts = ["Active layers: %s. Exit Lock policing: a 'git commit' that touches code needs "
             "a green from /bulletproof:testar." % layers]
    if 3 in layers:
        parts.append("Production guards (layer 3) are on: publishing and writing to the "
                     "production database ask for your approval.")
    if stacks:
        parts.append("Stacks: %s." % ", ".join(stacks))
    # stack drift: has a manifest of an undeclared stack shown up?
    sdrift = set(stackmod.detect(root)) - set(stacks)
    if sdrift and stacks:
        parts.append("Stack drift: %s appeared; run /bulletproof:framework-init." %
                     ", ".join(sorted(sdrift)))
    # capability drift: a new signal (database/deploy) not covered by the layers yet
    try:
        caps, _ = capmod.detect(root)
        new_layers = sorted(set(capmod.layers_for(caps)) - set(layers))
        if new_layers:
            parts.append("WARNING new capability detected (layer %s not switched on yet): run "
                         "/bulletproof:framework-init to switch the guards on." % new_layers)
    except Exception:
        pass
    return " ".join(parts)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    cwd = payload.get("cwd") or os.getcwd()
    try:
        fvdata = gate.managed_project(cwd)
        if fvdata is None:
            sys.exit(0)  # gate closed -> complete silence
        root = gate.root_of(cwd) or cwd
        out = {"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "[Bulletproof] %s" % message(fvdata, root),
        }}
        print(json.dumps(out))
    except Exception:
        sys.exit(0)  # fail-open


if __name__ == "__main__":
    main()
