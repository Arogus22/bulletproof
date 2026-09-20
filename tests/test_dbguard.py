#!/usr/bin/env python3
"""Proof of the D1 database guard (layer 3): protects production (--remote / MCP write),
lets local D1 and reads through. Does not need git (the guard only reads the config)."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo: parent of tests/
GUARD = os.path.join(PLUGIN, "scripts", "db-guard.py")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FAIL", name))

root = os.path.realpath(tempfile.mkdtemp(prefix="bp-db-"))

def mk_repo(name, layers=None, prod_db=True, managed=True):
    layers = layers if layers is not None else [1, 2, 3]
    repo = os.path.join(root, name)
    os.makedirs(repo, exist_ok=True)
    if managed:
        fv = {"framework": "bulletproof", "version": "0.3", "plugin": "bulletproof",
              "status": "active", "layers": layers, "stacks": ["node"], "config": {}}
        if prod_db:
            fv["config"]["prod_db"] = {"kind": "d1", "guard_remote_only": True}
    else:
        fv = {"framework": "bulletproof", "version": "0.1"}
    with open(os.path.join(repo, ".framework-version"), "w") as f:
        json.dump(fv, f)
    return repo

def run_bash(repo, cmd):
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": repo}
    p = subprocess.run(["python3", GUARD], input=json.dumps(payload), capture_output=True, text=True)
    return "ask" in p.stdout

def run_mcp(repo, tool, tool_input):
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": repo}
    p = subprocess.run(["python3", GUARD], input=json.dumps(payload), capture_output=True, text=True)
    return "ask" in p.stdout

repo = mk_repo("proj")

print("\n[A] wrangler d1 execute --remote INSERT -> ask")
check("ask", run_bash(repo, "npx wrangler d1 execute DB --remote --command \"INSERT INTO t VALUES (1)\""))

print("\n[B] wrangler d1 execute --remote SELECT -> passes (read)")
check("passes", not run_bash(repo, "npx wrangler d1 execute DB --remote --command \"SELECT * FROM t\""))

print("\n[C] wrangler d1 execute (without --remote, local) INSERT -> passes")
check("passes (local)", not run_bash(repo, "npx wrangler d1 execute DB --local --command \"INSERT INTO t VALUES (1)\""))

print("\n[D] wrangler d1 migrations apply --remote -> ask")
check("ask", run_bash(repo, "npx wrangler d1 migrations apply DB --remote"))

print("\n[E] wrangler d1 execute --remote --file x.sql -> ask (not classifiable)")
check("ask", run_bash(repo, "npx wrangler d1 execute DB --remote --file ./seed.sql"))

print("\n[F] wrangler d1 execute --remote without --command -> ask (fail-closed)")
check("ask", run_bash(repo, "npx wrangler d1 execute DB --remote"))

print("\n[G] MCP d1 query with INSERT -> ask")
check("ask", run_mcp(repo, "mcp__cloudflare__d1_database_query", {"sql": "INSERT INTO t VALUES (1)"}))

print("\n[H] MCP d1 query with SELECT -> passes")
check("passes", not run_mcp(repo, "mcp__cloudflare__d1_database_query", {"sql": "SELECT * FROM t"}))

print("\n[I] MCP d1_databases_list -> passes (listing)")
check("passes", not run_mcp(repo, "mcp__cloudflare__d1_databases_list", {}))

print("\n[J] normal git commit (does not touch the DB) -> passes")
check("passes", not run_bash(repo, "git -C %s commit -m x" % repo))

print("\n[K] layer 3 off (layers [1,2]) -> passes")
r2 = mk_repo("nolayer3", layers=[1, 2])
check("passes (layer 3 off)", not run_bash(r2, "npx wrangler d1 execute DB --remote --command \"DELETE FROM t\""))

print("\n[L] no prod_db in the config -> passes")
r3 = mk_repo("nodb", prod_db=False)
check("passes (no prod_db)", not run_bash(r3, "npx wrangler d1 execute DB --remote --command \"DROP TABLE t\""))

print("\n[M] unmanaged -> passes")
r4 = mk_repo("legacy", managed=False)
check("passes (unmanaged)", not run_bash(r4, "npx wrangler d1 execute DB --remote --command \"DELETE FROM t\""))

# ---------------------------------------------------------------------------
# 2026-09 regressions (acceptance proof on the first project that adopted the plugin). Each
# case below went through silently (or barked for no reason) before the fix.
# ---------------------------------------------------------------------------
api = os.path.join(repo, "dashboard", "api")
os.makedirs(api, exist_ok=True)
with open(os.path.join(api, "package.json"), "w") as f:
    json.dump({"scripts": {
        "dev": "wrangler dev --remote",
        "db:migrate:remote": "wrangler d1 migrations apply DB --remote",
        "db:migrate:local": "wrangler d1 migrations apply DB --local",
        "db:status": "wrangler d1 migrations list DB --remote",
        "test": "vitest run",
    }}, f)

print("\n[N] commands that are ALWAYS remote (no --remote flag) -> ask")
check("wrangler d1 delete wipes all of production", run_bash(repo, "npx wrangler d1 delete DB -y"))
check("wrangler d1 time-travel restore overwrites production",
      run_bash(repo, "npx wrangler d1 time-travel restore DB --timestamp=1700000000"))
check("time-travel info -> passes (read)", not run_bash(repo, "npx wrangler d1 time-travel info DB"))
check("d1 list / info -> passes", not run_bash(repo, "npx wrangler d1 list && npx wrangler d1 info DB"))

print("\n[O] wrangler dev --remote connects the local server to production D1 -> ask")
check("wrangler dev --remote", run_bash(repo, "cd dashboard/api && npx wrangler dev --remote"))
check("wrangler dev --local -> passes", not run_bash(repo, "cd dashboard/api && npx wrangler dev --local --port 8787"))
check("wrangler dev -> passes", not run_bash(repo, "cd dashboard/api && npx wrangler dev"))

print("\n[P] the real command hidden inside a package.json script")
check("npm run db:migrate:remote -> ask", run_bash(repo, "cd dashboard/api && npm run db:migrate:remote"))
check("npm run dev (= wrangler dev --remote) -> ask", run_bash(repo, "cd dashboard/api && npm run dev"))
check("npm --prefix ... run db:migrate:remote -> ask", run_bash(repo, "npm --prefix dashboard/api run db:migrate:remote"))
check("npm run db:migrate:local -> passes", not run_bash(repo, "cd dashboard/api && npm run db:migrate:local"))
check("npm run db:status (read) -> passes", not run_bash(repo, "cd dashboard/api && npm run db:status"))
check("npm test -> passes", not run_bash(repo, "cd dashboard/api && npm test"))

print("\n[Q] `cd` and a session OUTSIDE the project do not blind the guard")
write = 'npx wrangler d1 execute DB --remote --command "DELETE FROM t"'
check("cd dashboard/api && remote write", run_bash(repo, "cd dashboard/api && " + write))
outside = os.path.join(root, "outro-sitio")
os.makedirs(outside, exist_ok=True)
def run_bash_from(cwd, cmd):
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}
    p = subprocess.run(["python3", GUARD], input=json.dumps(payload), capture_output=True, text=True)
    return "ask" in p.stdout
check("session outside: cd <abs>/dashboard/api && remote write", run_bash_from(outside, "cd %s && %s" % (api, write)))
check("session outside, without entering the project -> passes", not run_bash_from(outside, write))

print("\n[R] different ways of writing the same thing")
check("--command='...'", run_bash(repo, "npx wrangler d1 execute DB --remote --command='DELETE FROM t'"))
check("--remote without SQL (not classifiable) -> ask", run_bash(repo, "npx wrangler d1 execute DB --remote"))
check("bash -c", run_bash(repo, 'bash -c "cd dashboard/api && npx wrangler d1 migrations apply DB --remote"'))
check("wrangler@4", run_bash(repo, "npx -y wrangler@4 d1 migrations apply DB --remote"))

print("\n[S] mentioning is not running -> does not get in the way")
check("grep", not run_bash(repo, 'grep -rn "wrangler d1 execute --remote" .'))
check("echo", not run_bash(repo, 'echo "wrangler d1 delete DB"'))
check("commit message", not run_bash(repo, 'git commit -m "docs: wrangler d1 migrations apply DB --remote"'))

print("\n[T] generic Cloudflare MCP tool (runs API calls): judged by its input")
GEN = "mcp__cloudflare__execute"
def code(s):
    return {"code": s}
check("write to D1 -> ask", run_mcp(repo, GEN, code(
    "await cloudflare.request({method:'POST', path:'/accounts/x/d1/database/y/query', body:{sql:'DELETE FROM t'}})")))
check("delete the DB -> ask", run_mcp(repo, GEN, code(
    "await cloudflare.request({method:'DELETE', path:'/accounts/x/d1/database/y'})")))
check("read from D1 -> passes", not run_mcp(repo, GEN, code(
    "await cloudflare.request({method:'POST', path:'/accounts/x/d1/database/y/query', body:{sql:'SELECT 1'}})")))
check("does not touch D1 -> passes (outside this guard's perimeter)", not run_mcp(repo, GEN, code(
    "await cloudflare.request({method:'DELETE', path:'/accounts/x/workers/scripts/y'})")))
check("documentation search about D1 -> passes",
      not run_mcp(repo, "mcp__cloudflare__search", {"query": "how to delete a d1 database"}))

print("\n[U] drizzle-kit with the d1-http driver talks to remote D1 without going through wrangler")
with open(os.path.join(api, "drizzle.config.ts"), "w") as f:
    f.write("export default defineConfig({ dialect: 'sqlite', driver: 'd1-http', schema: './src/db/schema.ts' })\n")
with open(os.path.join(api, "package.json")) as f:
    pkg = json.load(f)
pkg["scripts"].update({"db:push": "drizzle-kit push", "db:generate": "drizzle-kit generate", "db:pull": "drizzle-kit pull"})
with open(os.path.join(api, "package.json"), "w") as f:
    json.dump(pkg, f)
check("drizzle-kit push -> ask", run_bash(repo, "cd dashboard/api && npx drizzle-kit push"))
check("drizzle-kit migrate -> ask", run_bash(repo, "cd dashboard/api && npx drizzle-kit migrate"))
check("drizzle-kit studio -> ask", run_bash(repo, "cd dashboard/api && npx drizzle-kit studio"))
check("npm run db:push -> ask", run_bash(repo, "cd dashboard/api && npm run db:push"))
check("config found from inside a subfolder", run_bash(repo, "cd dashboard/api/src && npx drizzle-kit push"))
check("drizzle-kit generate (only writes files) -> passes", not run_bash(repo, "cd dashboard/api && npm run db:generate"))
check("drizzle-kit pull (read) -> passes", not run_bash(repo, "cd dashboard/api && npm run db:pull"))
with open(os.path.join(api, "drizzle.config.ts"), "w") as f:
    f.write("export default defineConfig({ dialect: 'sqlite', dbCredentials: { url: './local.db' } })\n")
check("local driver (no d1-http) -> passes", not run_bash(repo, "cd dashboard/api && npx drizzle-kit push"))
os.remove(os.path.join(api, "drizzle.config.ts"))
check("no drizzle.config -> passes", not run_bash(repo, "cd dashboard/api && npx drizzle-kit push"))

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
