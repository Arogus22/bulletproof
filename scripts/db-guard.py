#!/usr/bin/env python3
"""PreToolUse hook -- production database guard (Bulletproof, layer 3).

Asks for APPROVAL ("ask") before touching the PRODUCTION database, in a managed project
with layer 3 on and config.prod_db. Supports Cloudflare D1 (the stack of the first
project that adopted the plugin): it protects the REMOTE database (production) and lets
the LOCAL one (development) through.

Surface:
  - Bash, `wrangler d1 ...`:
      execute --remote that writes / --file, migrations apply --remote -> ask
      delete, time-travel restore (ALWAYS remote: they have no --remote flag) -> ask
      without --remote (local dev) -> passes; a pure SELECT --remote -> passes
  - Bash, `wrangler dev --remote`: the local server is connected to the PRODUCTION D1,
    and any write request made to that server is written to production -> ask
  - Bash, package.json scripts (`npm run db:migrate:remote`, `npm run dev`): the guard
    expands the script and judges the real command.
  - Bash, `drizzle-kit push|migrate|studio` when drizzle.config uses the `d1-http` driver:
    it talks to the remote D1 over HTTP, without going through wrangler -> ask.
  - MCP: D1 tools (mcp__*d1*) that write, or query with writes in them -> ask; listings
    and reads -> pass. Generic Cloudflare tools (for example `execute`, which runs API
    calls) are judged by their input: they only matter if they touch D1.

The Bash command line is read command by command, with the effective directory
(cmdparse), so a `cd dashboard/api && ...`, or a session opened outside the project, do
not blind the guard.

Fail-CLOSED inside the perimeter (--remote with SQL that cannot be classified, or --file,
asks for approval). Fail-open only on the payload parse and outside the perimeter (not
managed / layer 3 off / no prod_db).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fv as gate
import cmdparse
from approval_policy import ask, claude_main

WRITE_KW = re.compile(r"(?i)\b(insert|update|delete|alter|drop|create|truncate|replace|"
                      r"merge|grant|revoke|reindex|vacuum|attach)\b")
READ_START = re.compile(r"(?is)^\s*(select|with|explain|pragma)\b")
# in a generic API call: the methods that change things, on top of write SQL
API_WRITE = re.compile(r"(?i)\b(DELETE|PUT|PATCH)\b")
D1_IN_INPUT = re.compile(r"(?i)(/d1/|\bd1[_\s-]?database|\bd1\b)")


def is_write_sql(sql):
    """True if the SQL looks like a write OR cannot be classified as a pure read
    (fail-closed)."""
    sql = (sql or "").strip()
    if not sql:
        return True
    if READ_START.match(sql) and not WRITE_KW.search(sql):
        return False
    return True


def guards_prod_db(directory):
    fvdata = gate.managed_project(directory)
    if fvdata is None or 3 not in gate.layers_of(fvdata):
        return False
    return bool((fvdata.get("config") or {}).get("prod_db"))


def has_flag(args, name):
    return any(a == name or a.startswith(name + "=") for a in args)


def guard_wrangler(text, args):
    """`args` are the tokens that follow `wrangler`."""
    words = [a for a in args if not a.startswith("-")]
    remote = has_flag(args, "--remote")

    if words[:1] == ["dev"]:
        if remote:
            ask("`wrangler dev --remote` connects the local server to the PRODUCTION database "
                "(D1): any write made through that server is written to production. For local "
                "work use `wrangler dev --local`. Approve anyway?")
        return

    if words[:1] != ["d1"]:
        return
    sub = words[1:3]

    # Always remote (there is no local version): they destroy or overwrite production.
    if sub[:1] == ["delete"]:
        ask("`wrangler d1 delete` DELETES the entire PRODUCTION database (D1). Approve?")
    if sub[:2] == ["time-travel", "restore"]:
        ask("`wrangler d1 time-travel restore` rolls the PRODUCTION database (D1) back to an "
            "earlier point, overwriting its current state. Approve?")

    if not remote:
        return  # local D1 (dev) -> passes
    if sub[:2] == ["migrations", "apply"]:
        ask("`wrangler d1 migrations apply --remote` changes the PRODUCTION database (D1). Approve?")
    if sub[:1] == ["execute"]:
        if has_flag(args, "--file"):
            ask("`wrangler d1 execute --remote --file` runs SQL from a file against the "
                "PRODUCTION database (D1); the guard cannot tell what that SQL does. Approve?")
        sql = None
        for i, a in enumerate(args):
            if a == "--command" and i + 1 < len(args):
                sql = args[i + 1]
            elif a.startswith("--command="):
                sql = a.split("=", 1)[1]
        if sql is None:
            ask("`wrangler d1 execute --remote` runs against the PRODUCTION database (D1), and "
                "the guard could not find the SQL to check it. Approve?")
        if is_write_sql(sql):
            ask("This writes to the PRODUCTION database (D1, --remote). Approve this operation?")


def drizzle_targets_remote(directory):
    """True if the nearest drizzle.config uses the d1-http driver (remote D1 over HTTP),
    or if it exists and cannot be read. False if there is no config, or if it points
    somewhere else."""
    cur = directory
    while True:
        for name in ("drizzle.config.ts", "drizzle.config.js", "drizzle.config.mjs",
                     "drizzle.config.cjs", "drizzle.config.json"):
            cand = os.path.join(cur, name)
            if os.path.isfile(cand):
                try:
                    with open(cand, encoding="utf-8", errors="replace") as f:
                        return "d1-http" in f.read()
                except Exception:
                    return True  # present but unreadable: in the perimeter, doubt means ask
        parent = os.path.dirname(cur)
        if parent == cur or os.path.isfile(os.path.join(cur, gate.FRAMEWORK_FILE)):
            return False
        cur = parent


def guard_drizzle(args, directory):
    words = [a for a in args if not a.startswith("-")]
    if not words or words[0] not in ("push", "migrate", "studio"):
        return  # generate, pull, check, drop: local files or reads
    if not drizzle_targets_remote(directory):
        return
    if words[0] == "studio":
        ask("`drizzle-kit studio` opens an editor connected to the PRODUCTION database (D1, "
            "through the d1-http driver). Approve?")
    ask("`drizzle-kit %s` changes the PRODUCTION database (D1: the drizzle config uses the "
        "d1-http driver). Approve?" % words[0])


def guard_bash(cmd, cwd):
    for text, toks, directory in cmdparse.effective_commands(cmd, cwd):
        if not guards_prod_db(directory):
            continue
        prog, args = cmdparse.program(toks)
        if prog == "wrangler":
            guard_wrangler(text, args)
        elif prog == "drizzle-kit":
            guard_drizzle(args, directory)


def guard_mcp(tool, tool_input):
    low = tool.lower()
    op = tool.split("__")[-1]
    lop = op.lower()

    if "d1" not in low:
        # Generic tool (for example mcp__cloudflare__execute): it only matters if it RUNS
        # something (a docs search about "delete d1" touches nothing) and if the input
        # touches D1.
        if not any(k in lop for k in ("execut", "run", "request", "api", "call", "fetch", "invoke")):
            return
        blob = json.dumps(tool_input or {}, ensure_ascii=False)
        if not D1_IN_INPUT.search(blob):
            return
        if WRITE_KW.search(blob) or API_WRITE.search(blob):
            ask("'%s' is about to change the PRODUCTION database (D1) through the Cloudflare "
                "API. Approve?" % op)
        return  # reading D1 -> passes

    if "list" in lop or "get" in lop:
        return  # listings and reads
    if any(k in lop for k in ("quer", "execut", "sql", "raw")):
        sql = ((tool_input or {}).get("sql") or (tool_input or {}).get("query")
               or (tool_input or {}).get("command") or "")
        if not is_write_sql(sql):
            return
        ask("This writes to the PRODUCTION database (D1, through the MCP tool '%s'). Approve?" % op)
    ask("'%s' touches the PRODUCTION database (D1). Approve?" % op)


def evaluate(data):
    cwd = data.get("cwd") or os.getcwd()
    tool = data.get("tool_name", "") or ""

    if tool == "Bash":
        guard_bash((data.get("tool_input") or {}).get("command") or "", cwd)
    elif tool.startswith("mcp__"):
        if guards_prod_db(cwd):
            guard_mcp(tool, data.get("tool_input") or {})


if __name__ == "__main__":
    claude_main(evaluate)
