#!/usr/bin/env python3
"""PreToolUse hook -- Guarda de BD de producao (Bulletproof, camada 3).

Pede APROVACAO ("ask") antes de tocar na base de dados de PRODUCAO, num projeto gerido
com a camada 3 ligada e config.prod_db. Suporta Cloudflare D1 (o stack do Dashboard):
protege a BD REMOTA (producao), deixa passar a LOCAL (desenvolvimento).

Superficie:
  - Bash, `wrangler d1 ...`:
      execute --remote de escrita / --file, migrations apply --remote -> ask
      delete, time-travel restore (sao SEMPRE remotos: nao tem flag --remote) -> ask
      sem --remote (local de dev) -> passa; SELECT puro --remote -> passa
  - Bash, `wrangler dev --remote`: o servidor local fica ligado a' D1 de PRODUCAO, e
    qualquer pedido de escrita feito a esse servidor escreve em producao -> ask
  - Bash, scripts do package.json (`npm run db:migrate:remote`, `npm run dev`): a guarda
    expande o script e julga o comando real.
  - Bash, `drizzle-kit push|migrate|studio` quando o drizzle.config usa o driver `d1-http`:
    fala com a D1 remota por HTTP, sem passar pelo wrangler -> ask.
  - MCP: tools de D1 (mcp__*d1*) de escrita/query-com-escrita -> ask; listagens/leituras
    -> passa. Tools genericas da Cloudflare (ex.: `execute`, que corre chamadas a' API)
    sao julgadas pelo input: so interessam se tocarem em D1.

A linha Bash e' lida comando a comando, com o diretorio efetivo (cmdparse), por isso um
`cd dashboard/api && ...` ou uma sessao aberta fora do projeto nao cegam a guarda.

Fail-CLOSED no perimetro (--remote com SQL nao classificavel, ou --file, pede aprovacao).
Fail-open so no parse do payload e fora do perimetro (nao gerido / camada 3 off / sem prod_db).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fv as gate
import cmdparse

WRITE_KW = re.compile(r"(?i)\b(insert|update|delete|alter|drop|create|truncate|replace|"
                      r"merge|grant|revoke|reindex|vacuum|attach)\b")
READ_START = re.compile(r"(?is)^\s*(select|with|explain|pragma)\b")
# numa chamada generica a' API: metodos que alteram, para alem do SQL de escrita
API_WRITE = re.compile(r"(?i)\b(DELETE|PUT|PATCH)\b")
D1_IN_INPUT = re.compile(r"(?i)(/d1/|\bd1[_\s-]?database|\bd1\b)")


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "ask",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


def is_write_sql(sql):
    """True se o SQL parece escrita OU nao e' classificavel como leitura pura (fail-closed)."""
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
    """`args` sao os tokens a seguir a `wrangler`."""
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

    # Sempre remotos (nao existe versao local): destroem ou sobrescrevem a producao.
    if sub[:1] == ["delete"]:
        ask("`wrangler d1 delete` DELETES the entire PRODUCTION database (D1). Approve?")
    if sub[:2] == ["time-travel", "restore"]:
        ask("`wrangler d1 time-travel restore` rolls the PRODUCTION database (D1) back to an "
            "earlier point, overwriting its current state. Approve?")

    if not remote:
        return  # D1 local (dev) -> passa
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
    """True se o drizzle.config mais proximo usa o driver d1-http (D1 remota por HTTP), ou
    se existe e nao o consigo ler. False se nao ha' config ou se aponta para outro sitio."""
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
                    return True  # existe mas nao se le: no perimetro, a duvida pede aprovacao
        parent = os.path.dirname(cur)
        if parent == cur or os.path.isfile(os.path.join(cur, gate.FRAMEWORK_FILE)):
            return False
        cur = parent


def guard_drizzle(args, directory):
    words = [a for a in args if not a.startswith("-")]
    if not words or words[0] not in ("push", "migrate", "studio"):
        return  # generate, pull, check, drop: ficheiros locais ou leitura
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
        # Tool generica (ex.: mcp__cloudflare__execute): so' interessa se EXECUTA (uma
        # pesquisa de documentacao sobre "delete d1" nao toca em nada) e se o input tocar em D1.
        if not any(k in lop for k in ("execut", "run", "request", "api", "call", "fetch", "invoke")):
            return
        blob = json.dumps(tool_input or {}, ensure_ascii=False)
        if not D1_IN_INPUT.search(blob):
            return
        if WRITE_KW.search(blob) or API_WRITE.search(blob):
            ask("'%s' is about to change the PRODUCTION database (D1) through the Cloudflare "
                "API. Approve?" % op)
        return  # leitura de D1 -> passa

    if "list" in lop or "get" in lop:
        return  # listagens/leituras
    if any(k in lop for k in ("quer", "execut", "sql", "raw")):
        sql = ((tool_input or {}).get("sql") or (tool_input or {}).get("query")
               or (tool_input or {}).get("command") or "")
        if not is_write_sql(sql):
            return
        ask("This writes to the PRODUCTION database (D1, through the MCP tool '%s'). Approve?" % op)
    ask("'%s' touches the PRODUCTION database (D1). Approve?" % op)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    cwd = data.get("cwd") or os.getcwd()
    tool = data.get("tool_name", "") or ""

    if tool == "Bash":
        guard_bash((data.get("tool_input") or {}).get("command") or "", cwd)
    elif tool.startswith("mcp__"):
        if guards_prod_db(cwd):
            guard_mcp(tool, data.get("tool_input") or {})


if __name__ == "__main__":
    main()
