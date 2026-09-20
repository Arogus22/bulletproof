#!/usr/bin/env python3
"""PreToolUse hook (Bash) -- production deploy guard (Bulletproof, layer 3).

Asks for APPROVAL ("ask") before PUBLISHING to production, in a project managed by the
plugin with layer 3 on. Publishing == a git push that touches the protected branch
(automatic deploy), a gh pr merge into it, or a manual deploy command
(config.deploy.deploy_cmds: `wrangler deploy`, `vercel`, ...). Passes: pushes to working
branches, dry-runs, and everything that does not publish.

The command line is read command by command (cmdparse): the `git push` at the end of
`git add -A && git commit -m x && git push`, the deploy behind a `cd dashboard/api &&`,
and the `wrangler deploy` hidden in an `npm run deploy` are seen for what they are.
Before this reading, those three shapes (the ones an agent really writes) went through
silently.

Config (from .framework-version): config.deploy.protected_branch, config.deploy.deploy_cmds.
Fail-CLOSED inside the perimeter (a push whose destination cannot be proven to be other
than the protected branch -> ask). Fail-open only on the payload parse and outside the
perimeter (not managed / layer 3 off / no config.deploy). Never "deny": the decision goes
back to the human.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fv as gate
import cmdparse

# `git push` flags that take a value next (so the value is not read as the remote)
PUSH_VALUE_FLAGS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec",
                    "--recurse-submodules", "--signed"}
# flags that push EVERY branch (so, the protected one as well)
PUSH_EVERYTHING = {"--all", "--mirror", "--branches"}


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "ask",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


def current_branch(directory):
    try:
        return subprocess.run(["git", "-C", directory, "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def deploy_config(directory):
    """The deploy config of the managed project that contains `directory`, or None
    (outside the perimeter)."""
    fvdata = gate.managed_project(directory)
    if fvdata is None or 3 not in gate.layers_of(fvdata):
        return None
    return (fvdata.get("config") or {}).get("deploy") or None


def check_push(args, directory, protected):
    if "--dry-run" in args or "-n" in args:
        return
    if any(a in PUSH_EVERYTHING for a in args):
        ask("This `git push` pushes every branch, including `%s`, which deploys to PRODUCTION. "
            "Approve publishing?" % protected)

    # git push [<repository> [<refspec>...]]: the first non-flag is the remote, the
    # rest are refspecs.
    positional, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a in PUSH_VALUE_FLAGS:
            skip = True
            continue
        if a.startswith("-"):
            continue
        positional.append(a)
    refspecs = positional[1:]

    if not refspecs:  # implicit push -> the current branch
        dst = current_branch(directory)
        if dst and dst != protected and dst != "HEAD":
            return
        ask("This `git push` goes (or may go) to `%s`, which deploys to PRODUCTION. "
            "Approve publishing?" % protected)

    for spec in refspecs:
        spec = spec.lstrip("+")
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        if dst in ("HEAD", "@", ""):
            dst = current_branch(directory)
        dst = re.sub(r"^refs/heads/", "", dst)
        if not dst or dst == protected:
            ask("This `git push` publishes to `%s`, which deploys to PRODUCTION. "
                "Approve publishing?" % protected)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # no payload -> does not step in

    if data.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = (data.get("tool_input") or {}).get("command") or data.get("command") or ""
    cwd = data.get("cwd") or os.getcwd()

    for text, toks, directory in cmdparse.effective_commands(cmd, cwd):
        dep = deploy_config(directory)
        if not dep:
            continue  # this command runs outside a managed project with layer 3
        protected = dep.get("protected_branch", "main")

        # Manual deploy (wrangler deploy, vercel, ...) -> ask.
        for dc in dep.get("deploy_cmds", []):
            if cmdparse.has_sequence(toks, dc.split()):
                ask("`%s` publishes straight to production. Project rule: nothing goes to "
                    "production without your approval. Approve publishing?" % dc)

        # gh pr merge may merge into the protected branch -> ask.
        prog, args = cmdparse.program(toks)
        if prog == "gh" and args[:2] == ["pr", "merge"]:
            ask("`gh pr merge` may merge into `%s`, which auto-deploys to production. "
                "Approve the merge?" % protected)

        sub, gargs, _dirs = cmdparse.git_parts(toks)
        if sub == "push":
            check_push(gargs, directory, protected)


if __name__ == "__main__":
    main()
