#!/usr/bin/env python3
"""Prova da guarda de BD D1 (camada 3): protege a producao (--remote / MCP escrita),
deixa passar o D1 local e as leituras. Nao precisa de git (a guarda so le a config)."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = "/Users/arogus/Desktop/Claude_Playground/bulletproof-plugin"
GUARD = os.path.join(PLUGIN, "scripts", "db-guard.py")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FALHA", name))

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

print("\n[B] wrangler d1 execute --remote SELECT -> passa (leitura)")
check("passa", not run_bash(repo, "npx wrangler d1 execute DB --remote --command \"SELECT * FROM t\""))

print("\n[C] wrangler d1 execute (sem --remote, local) INSERT -> passa")
check("passa (local)", not run_bash(repo, "npx wrangler d1 execute DB --local --command \"INSERT INTO t VALUES (1)\""))

print("\n[D] wrangler d1 migrations apply --remote -> ask")
check("ask", run_bash(repo, "npx wrangler d1 migrations apply DB --remote"))

print("\n[E] wrangler d1 execute --remote --file x.sql -> ask (nao classificavel)")
check("ask", run_bash(repo, "npx wrangler d1 execute DB --remote --file ./seed.sql"))

print("\n[F] wrangler d1 execute --remote sem --command -> ask (fail-closed)")
check("ask", run_bash(repo, "npx wrangler d1 execute DB --remote"))

print("\n[G] MCP d1 query com INSERT -> ask")
check("ask", run_mcp(repo, "mcp__cloudflare__d1_database_query", {"sql": "INSERT INTO t VALUES (1)"}))

print("\n[H] MCP d1 query com SELECT -> passa")
check("passa", not run_mcp(repo, "mcp__cloudflare__d1_database_query", {"sql": "SELECT * FROM t"}))

print("\n[I] MCP d1_databases_list -> passa (listagem)")
check("passa", not run_mcp(repo, "mcp__cloudflare__d1_databases_list", {}))

print("\n[J] git commit normal (nao toca a BD) -> passa")
check("passa", not run_bash(repo, "git -C %s commit -m x" % repo))

print("\n[K] camada 3 desligada (layers [1,2]) -> passa")
r2 = mk_repo("nolayer3", layers=[1, 2])
check("passa (camada 3 off)", not run_bash(r2, "npx wrangler d1 execute DB --remote --command \"DELETE FROM t\""))

print("\n[L] sem prod_db na config -> passa")
r3 = mk_repo("nodb", prod_db=False)
check("passa (sem prod_db)", not run_bash(r3, "npx wrangler d1 execute DB --remote --command \"DROP TABLE t\""))

print("\n[M] nao gerido -> passa")
r4 = mk_repo("legado", managed=False)
check("passa (nao gerido)", not run_bash(r4, "npx wrangler d1 execute DB --remote --command \"DELETE FROM t\""))

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
