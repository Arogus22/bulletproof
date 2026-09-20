#!/usr/bin/env python3
"""fv.py -- the "gate" of the Bulletproof plugin.

Reads the project's .framework-version and decides whether THIS project is managed
by the plugin. It is the root invariant: the packaged hooks are global by nature
(registered through ${CLAUDE_PLUGIN_ROOT}), but they only act where the gate opens.
A legacy .framework-version (a v0.1 one, without the "plugin": "bulletproof"
marker) closes the gate, and the hook ignores the project completely.

Used as a module (`import fv; fv.managed_project(cwd)`) and standalone (debug:
`python3 fv.py [path]`). Fail-safe: any doubt -> gate CLOSED (None).
"""
import json
import os

PLUGIN_ID = "bulletproof"
FRAMEWORK_FILE = ".framework-version"


def find_framework_file(start):
    """Walks up from `start` looking for the .framework-version.

    The subdirectory case (git repo in platform/, control file one level up) is
    why we climb the tree instead of only looking at `start`.
    """
    cur = os.path.abspath(start)
    while True:
        cand = os.path.join(cur, FRAMEWORK_FILE)
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:  # reached the root of the filesystem
            return None
        cur = parent


def read_fv(start):
    """Returns the dict of the nearest .framework-version (walking up), or None."""
    path = find_framework_file(start)
    if not path:
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def managed_project(start):
    """THE GATE. Returns the .framework-version dict if this project is managed by
    the plugin ("plugin" marker == PLUGIN_ID); otherwise None (gate closed).
    """
    fv = read_fv(start)
    if fv is None:
        return None
    if fv.get("plugin") != PLUGIN_ID:
        return None
    return fv


def root_of(start):
    """The root of the managed project: the directory that holds the .framework-version."""
    path = find_framework_file(start)
    return os.path.dirname(path) if path else None


def layers_of(fvdata):
    """The active layers of a managed project. v0.3 uses the `layers` field; a legacy
    v0.2 (only `tiers`, or no field at all) maps to [1, 2] (what a managed project
    actually had). Makes sure 2 never shows up without 1 (layer 2 depends on layer 1)."""
    if not isinstance(fvdata, dict):
        return [1, 2]
    raw = fvdata.get("layers")
    if isinstance(raw, list) and raw:
        layers = set()
        for x in raw:
            try:
                layers.add(int(x))
            except (ValueError, TypeError):
                pass
        if 2 in layers:
            layers.add(1)
        return sorted(layers) if layers else [1, 2]
    return [1, 2]


if __name__ == "__main__":
    import sys
    where = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    data = managed_project(where)
    if data is None:
        print("gate CLOSED (not managed by the plugin): %s" % os.path.abspath(where))
        raise SystemExit(1)
    print("gate OPEN (%s): %s" % (root_of(where), json.dumps(data)))
    raise SystemExit(0)
