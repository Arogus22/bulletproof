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

# ---------------------------------------------------------------------------
# Regressoes de 2026-09 (prova de aceitacao no Dashboard). Cada caso abaixo passava calado
# (ou ladrava a' toa) antes da correcao.
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

print("\n[N] comandos SEMPRE remotos (nao tem flag --remote) -> ask")
check("wrangler d1 delete apaga a producao inteira", run_bash(repo, "npx wrangler d1 delete DB -y"))
check("wrangler d1 time-travel restore sobrescreve a producao",
      run_bash(repo, "npx wrangler d1 time-travel restore DB --timestamp=1700000000"))
check("time-travel info -> passa (leitura)", not run_bash(repo, "npx wrangler d1 time-travel info DB"))
check("d1 list / info -> passa", not run_bash(repo, "npx wrangler d1 list && npx wrangler d1 info DB"))

print("\n[O] wrangler dev --remote liga o servidor local a' D1 de producao -> ask")
check("wrangler dev --remote", run_bash(repo, "cd dashboard/api && npx wrangler dev --remote"))
check("wrangler dev --local -> passa", not run_bash(repo, "cd dashboard/api && npx wrangler dev --local --port 8787"))
check("wrangler dev -> passa", not run_bash(repo, "cd dashboard/api && npx wrangler dev"))

print("\n[P] o comando real escondido num script do package.json")
check("npm run db:migrate:remote -> ask", run_bash(repo, "cd dashboard/api && npm run db:migrate:remote"))
check("npm run dev (= wrangler dev --remote) -> ask", run_bash(repo, "cd dashboard/api && npm run dev"))
check("npm --prefix ... run db:migrate:remote -> ask", run_bash(repo, "npm --prefix dashboard/api run db:migrate:remote"))
check("npm run db:migrate:local -> passa", not run_bash(repo, "cd dashboard/api && npm run db:migrate:local"))
check("npm run db:status (leitura) -> passa", not run_bash(repo, "cd dashboard/api && npm run db:status"))
check("npm test -> passa", not run_bash(repo, "cd dashboard/api && npm test"))

print("\n[Q] `cd` e sessao FORA do projeto nao cegam a guarda")
write = 'npx wrangler d1 execute DB --remote --command "DELETE FROM t"'
check("cd dashboard/api && escrita remota", run_bash(repo, "cd dashboard/api && " + write))
outside = os.path.join(root, "outro-sitio")
os.makedirs(outside, exist_ok=True)
def run_bash_from(cwd, cmd):
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}
    p = subprocess.run(["python3", GUARD], input=json.dumps(payload), capture_output=True, text=True)
    return "ask" in p.stdout
check("sessao fora: cd <abs>/dashboard/api && escrita remota", run_bash_from(outside, "cd %s && %s" % (api, write)))
check("sessao fora, sem entrar no projeto -> passa", not run_bash_from(outside, write))

print("\n[R] formas de escrever o mesmo")
check("--command='...'", run_bash(repo, "npx wrangler d1 execute DB --remote --command='DELETE FROM t'"))
check("--remote sem SQL (nao classificavel) -> ask", run_bash(repo, "npx wrangler d1 execute DB --remote"))
check("bash -c", run_bash(repo, 'bash -c "cd dashboard/api && npx wrangler d1 migrations apply DB --remote"'))
check("wrangler@4", run_bash(repo, "npx -y wrangler@4 d1 migrations apply DB --remote"))

print("\n[S] mencionar nao e' correr -> nao incomoda")
check("grep", not run_bash(repo, 'grep -rn "wrangler d1 execute --remote" .'))
check("echo", not run_bash(repo, 'echo "wrangler d1 delete DB"'))
check("mensagem de commit", not run_bash(repo, 'git commit -m "docs: wrangler d1 migrations apply DB --remote"'))

print("\n[T] tool MCP generica da Cloudflare (corre chamadas a' API): julgada pelo input")
GEN = "mcp__cloudflare__execute"
def code(s):
    return {"code": s}
check("escrita em D1 -> ask", run_mcp(repo, GEN, code(
    "await cloudflare.request({method:'POST', path:'/accounts/x/d1/database/y/query', body:{sql:'DELETE FROM t'}})")))
check("apagar a BD -> ask", run_mcp(repo, GEN, code(
    "await cloudflare.request({method:'DELETE', path:'/accounts/x/d1/database/y'})")))
check("leitura de D1 -> passa", not run_mcp(repo, GEN, code(
    "await cloudflare.request({method:'POST', path:'/accounts/x/d1/database/y/query', body:{sql:'SELECT 1'}})")))
check("nao toca em D1 -> passa (fora do perimetro desta guarda)", not run_mcp(repo, GEN, code(
    "await cloudflare.request({method:'DELETE', path:'/accounts/x/workers/scripts/y'})")))
check("pesquisa de documentacao sobre D1 -> passa",
      not run_mcp(repo, "mcp__cloudflare__search", {"query": "how to delete a d1 database"}))

print("\n[U] drizzle-kit com o driver d1-http fala com a D1 remota sem passar pelo wrangler")
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
check("config encontrado a partir de uma subpasta", run_bash(repo, "cd dashboard/api/src && npx drizzle-kit push"))
check("drizzle-kit generate (so' escreve ficheiros) -> passa", not run_bash(repo, "cd dashboard/api && npm run db:generate"))
check("drizzle-kit pull (leitura) -> passa", not run_bash(repo, "cd dashboard/api && npm run db:pull"))
with open(os.path.join(api, "drizzle.config.ts"), "w") as f:
    f.write("export default defineConfig({ dialect: 'sqlite', dbCredentials: { url: './local.db' } })\n")
check("driver local (sem d1-http) -> passa", not run_bash(repo, "cd dashboard/api && npx drizzle-kit push"))
os.remove(os.path.join(api, "drizzle.config.ts"))
check("sem drizzle.config -> passa", not run_bash(repo, "cd dashboard/api && npx drizzle-kit push"))

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
