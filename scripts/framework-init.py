#!/usr/bin/env python3
"""framework-init.py -- adopts a project into Bulletproof: detects the capabilities
and proposes the layers.

Creates (or extends, idempotently) the v0.3 .framework-version at the project root,
with the plugin marker, the status, the active layers (derived from the detected
capabilities), the stacks, and the per-layer config. Reports the signals it detected
and the confirmation questions about what detection CANNOT see (the human closes the
false negatives).

Usage: python3 framework-init.py [dir] [--stack S ...]

Refuses to overwrite a LEGACY .framework-version (one without the plugin marker).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fv as gate
import stacks as stackmod
import capabilities as capmod
import codefp

SCHEMA_VERSION = "0.3"


def read_local(root):
    """Reads the .framework-version of THIS dir only (init works on the root given)."""
    path = os.path.join(root, ".framework-version")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def build_config(caps):
    """Per-layer config, according to the capabilities that were detected."""
    # One default for "this is code": the Exit Lock's own (codefp). A second copy here had
    # drifted narrower, and since config.code_re wins, every adopted C/C++/Kotlin-script
    # project was committing that code unpoliced.
    cfg = {"code_re": codefp.DEFAULT_CODE_RE}
    if caps.get("deploy_sensitive"):
        cfg["deploy"] = {"protected_branch": "main",
                         "deploy_cmds": ["wrangler deploy", "wrangler pages deploy", "vercel"]}
    if caps.get("db"):
        cfg["prod_db"] = {"kind": "d1", "guard_remote_only": True}
    return cfg


def plan(root, forced):
    """Returns (data, action, caps, signals). data=None => refused (legacy)."""
    stacks = sorted(set(forced) | set(stackmod.detect(root)))
    caps, signals = capmod.detect(root)
    layers = capmod.layers_for(caps)
    existing = read_local(root)

    if existing is not None and existing.get("plugin") != "bulletproof":
        return None, "LEGACY", caps, signals

    config = build_config(caps)
    if existing is not None:  # incremental: extends, never weakens
        stacks = sorted(set(existing.get("stacks", [])) | set(stacks))
        status = existing.get("status", "bootstrapping")
        tests = existing.get("tests", {}) if isinstance(existing.get("tests"), dict) else {}
        # A re-run only ADDS. Layers and config blocks already in the file stay as they are:
        # they may be what a human confirmed because detection could not see it (a deploy
        # with no trace in the repo, a custom protected branch). Re-deriving them from
        # detection alone silently switched those production guards off on the next run,
        # which is exactly the run the Guide asks for when it reports drift.
        layers = sorted(set(gate.layers_of(existing)) | set(layers))
        kept = existing.get("config") if isinstance(existing.get("config"), dict) else {}
        config = dict(config, **kept)
        action = "EXTENDED"
    else:
        status = "bootstrapping"
        tests = {}
        action = "CREATED"

    data = {"framework": "bulletproof", "version": SCHEMA_VERSION, "plugin": "bulletproof",
            "status": status, "layers": layers, "stacks": stacks, "tests": tests,
            "config": config}
    return data, action, caps, signals


def main(argv):
    p = argparse.ArgumentParser(description="adopt a project into Bulletproof")
    p.add_argument("dir", nargs="?", default=".")
    p.add_argument("--stack", action="append", default=[], dest="stacks")
    a = p.parse_args(argv)
    root = os.path.abspath(a.dir)

    if not os.path.isdir(root):
        print("framework-init: '%s' is not a directory." % root)
        return 2

    data, action, caps, signals = plan(root, a.stacks)
    path = os.path.join(root, ".framework-version")

    if data is None:  # legacy
        print("framework-init: there is already a .framework-version WITHOUT the plugin "
              "marker (legacy) at %s." % path)
        print("I will not overwrite a setup of your own. Back up or remove the current file "
              "first if you want this project adopted by the plugin.")
        return 2

    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("Bulletproof: project %s." % ("extended" if action == "EXTENDED" else "adopted"))
    print("  .framework-version: %s" % path)
    print("  proposed layers: %s" % data["layers"])
    print("  status:  %s" % data["status"])
    print("  stacks:  %s" % (", ".join(data["stacks"]) if data["stacks"] else "(none)"))
    if signals:
        print("  detected capabilities:")
        for s in signals:
            print("   + %s" % s)
    qs = capmod.confirm_questions(caps)
    if qs:
        print("  CONFIRM (what I cannot see from the repository):")
        for q in qs:
            print("   ? %s" % q)
    if data["status"] == "bootstrapping":
        print("  next: Guide active; Exit Lock on standby until the first green /bulletproof:testar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
