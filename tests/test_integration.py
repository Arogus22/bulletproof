#!/usr/bin/env python3
"""Prova de INTEGRACAO da cablagem: simula o que o Claude Code faz ao carregar o
plugin -- le o hooks/hooks.json, resolve ${CLAUDE_PLUGIN_ROOT}, e invoca cada hook
com o payload que o CC enviaria (e CLAUDE_PLUGIN_ROOT no ambiente). Prova que a
config do hooks.json esta correta (caminhos resolvem, matchers filtram, scripts
respondem), sem precisar de correr o `claude` CLI. Ledger/estado isolados."""
import json
import os
import re
import shutil
import subprocess
import tempfile

PLUGIN = "/Users/arogus/Desktop/Claude_Playground/bulletproof-plugin"
HOOKS = os.path.join(PLUGIN, "hooks", "hooks.json")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FALHA", name))

root = os.path.realpath(tempfile.mkdtemp(prefix="bp-integ-"))
LEDGER = os.path.join(root, "ledger.jsonl")
STATE = os.path.join(root, "state")

def env():
    e = dict(os.environ)
    e["CLAUDE_PLUGIN_ROOT"] = PLUGIN  # como o CC exporta ao correr o hook
    e["BULLETPROOF_LEDGER"] = LEDGER
    e["BULLETPROOF_STATE"] = STATE
    return e

def resolve(tok):
    return tok.replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN)

def hooks_for(event, tool=None):
    """Extrai do hooks.json os comandos (command+args resolvidos) de um evento,
    filtrando pelo matcher como o CC faria."""
    cfg = json.load(open(HOOKS))["hooks"].get(event, [])
    out = []
    for group in cfg:
        matcher = group.get("matcher")
        if tool is not None and matcher not in (None, "", tool) and not re.search(matcher, tool):
            continue
        for h in group.get("hooks", []):
            out.append([h["command"]] + [resolve(a) for a in h.get("args", [])])
    return out

def run_event(event, payload, tool=None):
    argv = hooks_for(event, tool)[0]
    p = subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True, env=env())
    return p.returncode, p.stdout, p.stderr

def mk_managed_repo():
    d = os.path.join(root, "proj")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".framework-version"), "w") as f:
        json.dump({"framework": "bulletproof", "version": "0.2", "plugin": "bulletproof",
                   "status": "active", "stacks": ["python"], "tiers": [1, 2]}, f)
    with open(os.path.join(d, "app.py"), "w") as f:
        f.write("x = 1\n")
    for a in (["git", "init", "-q", d], ["git", "-C", d, "config", "user.email", "t@t"],
              ["git", "-C", d, "config", "user.name", "t"], ["git", "-C", d, "add", "-A"],
              ["git", "-C", d, "commit", "-q", "-m", "init"]):
        subprocess.run(a, capture_output=True)
    with open(os.path.join(d, "app.py"), "a") as f:
        f.write("y = 2\n")  # suja o codigo
    return d

print("\n[1] hooks.json bem formado, com os dois eventos e a variavel de caminho")
cfg = json.load(open(HOOKS))["hooks"]
check("SessionStart registado", "SessionStart" in cfg)
check("PreToolUse registado", "PreToolUse" in cfg)
check("caminhos via ${CLAUDE_PLUGIN_ROOT}", "${CLAUDE_PLUGIN_ROOT}" in open(HOOKS).read())
_raw = open(HOOKS).read()
check("guardas registadas (exit-lock + deploy + db)",
      all(s in _raw for s in ["exit-lock-guard", "deploy-guard", "db-guard"]))

proj = mk_managed_repo()

print("\n[2] SessionStart (Guia) pela cablagem -> resolve e injeta contexto")
rc, out, err = run_event("SessionStart", {"cwd": proj})
ctx = ""
try:
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
except Exception:
    pass
check("resolve o caminho e corre (rc0)", rc == 0)
check("injeta contexto Bulletproof (active)", "[Bulletproof]" in ctx and "policiar" in ctx)

print("\n[3] PreToolUse (Exit Lock) pela cablagem -> bloqueia commit nao-verde")
rc, out, err = run_event("PreToolUse",
    {"tool_name": "Bash", "tool_input": {"command": "git -C %s commit -m x" % proj},
     "cwd": proj, "session_id": "s"}, tool="Bash")
check("Exit Lock morde (exit 2)", rc == 2)
check("mensagem BLOQUEADO no stderr", "BLOQUEADO" in err)

print("\n[4] matcher: PreToolUse 'Bash' nao casa outra tool (ex.: Edit)")
check("um Edit nao dispararia o Exit Lock", hooks_for("PreToolUse", tool="Edit") == [])

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
