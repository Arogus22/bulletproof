#!/usr/bin/env python3
"""PreToolUse hook -- Guarda de BD de producao (Bulletproof, camada 3).

Pede APROVACAO ("ask") antes de ESCRITAS na base de dados de PRODUCAO, num projeto
gerido com a camada 3 ligada e config.prod_db. Suporta Cloudflare D1 (o stack do
Dashboard): protege a BD REMOTA (producao), deixa passar a LOCAL (desenvolvimento).

Superficie:
  - Bash: `wrangler d1 execute --remote` de escrita, `wrangler d1 migrations apply --remote`.
    Sem --remote (local de dev) -> passa. SELECT puro --remote -> passa.
  - MCP: tools de D1 (mcp__*d1*) de escrita/query-com-escrita -> ask; listagens/leituras -> passa.

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

WRITE_KW = re.compile(r"(?i)\b(insert|update|delete|alter|drop|create|truncate|replace|"
                      r"merge|grant|revoke|reindex|vacuum|attach)\b")
READ_START = re.compile(r"(?is)^\s*(select|with|explain|pragma)\b")


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


def guard_bash(cmd):
    if not re.search(r"\bwrangler\b.*\bd1\b", cmd):
        return
    if not re.search(r"--remote\b", cmd):
        return  # D1 local (dev) -> passa
    if re.search(r"\bmigrations\s+apply\b", cmd):
        ask("`wrangler d1 migrations apply --remote` altera a BD de PRODUCAO (D1). Autorizas?")
    if re.search(r"\bexecute\b", cmd):
        if re.search(r"--file\b", cmd):
            ask("`wrangler d1 execute --remote --file` corre SQL de um ficheiro na BD de "
                "PRODUCAO (D1, nao classificavel). Autorizas?")
        m = re.search(r"--command(?:=|\s+)(['\"])(.*?)\1", cmd, re.S)
        if m is None:
            ask("`wrangler d1 execute --remote` na BD de PRODUCAO (D1, SQL nao reconhecido). Autorizas?")
        if is_write_sql(m.group(2)):
            ask("Escrita na BD de PRODUCAO (D1, --remote). Autorizas esta operacao?")


def guard_mcp(tool, tool_input):
    low = tool.lower()
    if "d1" not in low:
        return
    op = tool.split("__")[-1]
    lop = op.lower()
    if "list" in lop or "get" in lop:
        return  # listagens/leituras
    if any(k in lop for k in ("quer", "execut", "sql", "raw")):
        sql = ((tool_input or {}).get("sql") or (tool_input or {}).get("query")
               or (tool_input or {}).get("command") or "")
        if not is_write_sql(sql):
            return
        ask("Escrita na BD de PRODUCAO (D1, via MCP '%s'). Autorizas?" % op)
    ask("'%s' toca a BD de PRODUCAO (D1). Autorizas?" % op)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    cwd = data.get("cwd") or os.getcwd()
    fvdata = gate.managed_project(cwd)
    if fvdata is None or 3 not in gate.layers_of(fvdata):
        sys.exit(0)
    if not (fvdata.get("config") or {}).get("prod_db"):
        sys.exit(0)

    tool = data.get("tool_name", "") or ""
    if tool == "Bash":
        guard_bash((data.get("tool_input") or {}).get("command") or "")
    elif tool.startswith("mcp__"):
        guard_mcp(tool, data.get("tool_input") or {})


if __name__ == "__main__":
    main()
