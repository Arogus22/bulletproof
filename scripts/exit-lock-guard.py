#!/usr/bin/env python3
"""PreToolUse hook (Bash) -- Exit Lock (Bulletproof, layer 2), plugin version.

Blocks `git commit` when the commit touches CODE that is not proven green (no marker,
stamped by mark-green.sh via /testar, matching the current state of the code). It only
acts on projects MANAGED by the plugin (the gate, fv.py): a repo without the marker, be
it a legacy setup or any other, ALWAYS goes through. Commits of only docs/config are not
blocked. Fail-open: any error or unexpected environment -> does NOT block (it exits with
a code other than 2).

NEW files count. The hook runs BEFORE the command, so in a `git add -A && git commit`
the new code is still untracked when the guard looks; `git diff HEAD` does not see it.
The guard reads the command line (cmdparse): if there is a `git add` before the commit,
it adds to what "this commit touches" the untracked code that this `add` will pick up.
And the fingerprint (codefp) always includes the untracked code, by content, so a green
stamped before the `git add` stays valid after it.

Env overrides (tests): BULLETPROOF_STATE (state base), BULLETPROOF_LEDGER.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fv as gate  # the marker gate
import cmdparse
import codefp
import runtime

STATE_BASE = runtime.state_base()


def git(args, cwd):
    return subprocess.run(["git", "-C", cwd] + args, capture_output=True, text=True).stdout


def find_commit(cmd, cwd):
    """(commit_dir, adds) of the first `git commit` on the command line, or (None, None).
    `adds` are the arguments of the `git add`/`git stage` that run BEFORE it, each with the
    directory where it runs: it is what will go into the commit and git does not see yet."""
    adds = []
    for _text, toks, directory in cmdparse.effective_commands(cmd, cwd):
        sub, args, _dirs = cmdparse.git_parts(toks)
        if sub in ("add", "stage"):
            adds.append((directory, args))
        elif sub == "commit":
            return directory, adds
    return None, None


def untracked_code_being_added(repo, adds, regex):
    """The untracked code that the `git add` on the command line will put into the commit.
    An explicit file path counts only that file; everything else (-A, ., folders, globs)
    counts all the untracked code: the guard does not guess on the permissive side."""
    if not adds:
        return []
    pending = [p for p in codefp.untracked(repo) if regex.search(p)]
    if not pending:
        return []
    picked, wide = set(), False
    root = os.path.realpath(repo)
    for directory, args in adds:
        flags = [a for a in args if a.startswith("-")]
        specs = [a for a in args if not a.startswith("-")]
        if any(f in ("-u", "--update") for f in flags):
            continue  # `add -u` only updates tracked files: it brings in no new code
        if not specs:
            if any(f in ("-A", "--all") for f in flags):
                wide = True
            continue
        for spec in specs:
            full = os.path.realpath(os.path.join(directory, spec))
            rel = os.path.relpath(full, root)
            if os.path.isfile(full):
                if rel in pending:
                    picked.add(rel)
            else:
                wide = True  # folder, ".", glob: no guessing on the permissive side
    return pending if wide else sorted(picked)


def log_block(repo, fp, cmd, session):
    """Writes the intervention to the ledger. Best-effort: it never breaks the hook."""
    try:
        import ledger
        ledger.record(event="block", gate="exit_lock", project=repo,
                      reason="no_green_stamp", incident_seed=fp,
                      session=session, detail={"cmd": cmd})
    except Exception:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = payload.get("tool_input", {}).get("command", "") or payload.get("command", "")
    # only bites on a git commit (not on status/push/merge)
    if not re.search(r"\bcommit\b", cmd):
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    work, adds = find_commit(cmd, cwd)
    if work is None:
        sys.exit(0)

    # THE GATE: only acts on projects managed by the plugin. No marker -> passes
    # (fail-open).
    fvdata = gate.managed_project(work)
    if fvdata is None:
        sys.exit(0)
    # The Exit Lock only bites when the project is "active" (there is a test layer that
    # stamps green). In "bootstrapping" (no tests yet) it waits -> passes.
    if fvdata.get("status") != "active":
        sys.exit(0)
    # Layer 2 only turns on if it is in the active layers (invariant: a layer turns on
    # only through layers). A v0.2 without layers maps to [1, 2], so 2 is in there.
    if 2 not in gate.layers_of(fvdata):
        sys.exit(0)

    try:
        repo = git(["rev-parse", "--show-toplevel"], work).strip()
        if not repo:
            sys.exit(0)  # not a repo -> fail-open

        code_re = codefp.code_regex(fvdata)
        touched = codefp.changed_code(repo, code_re, include_untracked=False)
        touched += untracked_code_being_added(repo, adds, code_re)
        if not touched:
            sys.exit(0)  # only docs/config -> does not bite

        fp = subprocess.run(
            ["bash", os.path.join(HERE, "exit-lock-fp.sh"), repo],
            capture_output=True, text=True,
        ).stdout.strip()
        if not fp:
            sys.exit(0)  # could not compute it -> fail-open

        key = hashlib.sha256(repo.encode()).hexdigest()
        marker = os.path.join(STATE_BASE, "exit-lock", key, "last-green")
        ok = os.path.exists(marker) and open(marker).read().strip() == fp
    except Exception:
        sys.exit(0)  # fail-open

    if not ok:
        log_block(repo, fp, cmd, payload.get("session_id"))
        sys.stderr.write(
            "BLOCKED (Exit Lock): this commit touches code that is not proven green. "
            "Run /bulletproof:testar; if it passes, it stamps the green and the commit goes "
            "through. If you already tested and changed the code afterwards, test again."
            .replace("/bulletproof:testar", runtime.workflow("testar"))
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
