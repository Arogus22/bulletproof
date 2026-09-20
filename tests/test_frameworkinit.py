#!/usr/bin/env python3
"""Proof of /bulletproof:framework-init: creates/extends the .framework-version v0.3 with
layers derived from detected capabilities, idempotent/incremental, refuses a legacy setup."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo: parent of tests/
SCRIPTS = os.path.join(PLUGIN, "scripts")
INIT = os.path.join(SCRIPTS, "framework-init.py")
FV = os.path.join(SCRIPTS, "fv.py")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FAIL", name))

root = os.path.realpath(tempfile.mkdtemp(prefix="bp-init-"))

def run_init(d, *args):
    p = subprocess.run(["python3", INIT, d, *args], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr

def read_fv(d):
    with open(os.path.join(d, ".framework-version")) as f:
        return json.load(f)

def mkproj(name, files=()):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    if isinstance(files, dict):
        for rel, content in files.items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(content)
    else:
        for fn in files:
            open(os.path.join(d, fn), "w").close()
    return d

print("\n[1] empty project -> v0.3, bootstrapping, layers [1,2]")
d = mkproj("empty")
rc, out = run_init(d)
fv = read_fv(d)
check("exit 0", rc == 0)
check("plugin marker", fv.get("plugin") == "bulletproof")
check("version 0.3", fv.get("version") == "0.3")
check("status bootstrapping", fv.get("status") == "bootstrapping")
check("layers [1,2]", fv.get("layers") == [1, 2])
check("asks about what it did not see (CONFIRM)", "CONFIRM" in out)

print("\n[2] Cloudflare + D1 project -> layers [1,2,3] + config")
d = mkproj("cf", {"api/wrangler.toml": "[[d1_databases]]\nbinding='DB'\n"})
rc, out = run_init(d)
fv = read_fv(d)
check("layers [1,2,3]", fv.get("layers") == [1, 2, 3])
check("config.deploy present", "deploy" in fv.get("config", {}))
check("config.prod_db kind=d1", fv.get("config", {}).get("prod_db", {}).get("kind") == "d1")

print("\n[2a] a database the guard does not know: no prod_db block, and the report says so")
# covers: scripts/framework-init.py build_config/main -- it used to write prod_db {"kind": "d1"}
# for ANY database signal, so a Postgres project was told its database writes were guarded.
d = mkproj("pg", {"prisma/schema.prisma": "datasource db {}\n", "vercel.json": "{}\n"})
rc, out = run_init(d)
fvpg = read_fv(d)
check("layer 3 on (there is a deploy to guard)", fvpg.get("layers") == [1, 2, 3])
check("config.deploy written", "deploy" in fvpg.get("config", {}))
check("NO config.prod_db: nothing here would guard that database", "prod_db" not in fvpg.get("config", {}))
check("and the report says it out loud (NOT guarded)", "NOT guarded" in out)
check("the D1 project of [2] got no such warning", "NOT guarded" not in run_init(mkproj("cf2", {"api/wrangler.toml": "[[d1_databases]]\n"}))[1])

print("\n[2b] the code_re it writes is the Exit Lock's own default (one source of truth)")
# covers: scripts/framework-init.py build_config -- a second, narrower copy of the default
# used to be written here, and config.code_re overrides the guard's default.
import re as _re
import sys as _sys
_sys.path.insert(0, SCRIPTS)
import codefp as _codefp
written = fv.get("config", {}).get("code_re")
check("config.code_re == codefp.DEFAULT_CODE_RE", written == _codefp.DEFAULT_CODE_RE)
check("C, C++ headers and .kts count as code under the written config",
      all(_re.search(written or "$^", f, _re.I) for f in ("src/main.c", "lib/x.cpp", "include/x.hpp", "build.gradle.kts")))
check("docs and config still do not count as code",
      not any(_re.search(written or "", f, _re.I) for f in ("README.md", "package.json", "notes.txt")))

print("\n[3] detects stack + --stack forced")
d = mkproj("py", files=["pyproject.toml"])
run_init(d)
check("stack python", read_fv(d).get("stacks") == ["python"])
d = mkproj("forced")
run_init(d, "--stack", "node")
check("--stack node", read_fv(d).get("stacks") == ["node"])

print("\n[4] idempotent (running twice does not change it)")
d = mkproj("idem", files=["go.mod"])
run_init(d); a = read_fv(d)
run_init(d); b = read_fv(d)
check("stable across runs", a == b and b.get("stacks") == ["go"])

print("\n[5] incremental (a new manifest extends stacks)")
d = mkproj("incr", files=["pyproject.toml"])
run_init(d)
check("starts with [python]", read_fv(d).get("stacks") == ["python"])
open(os.path.join(d, "package.json"), "w").close()
run_init(d)
check("extends to [node, python]", read_fv(d).get("stacks") == ["node", "python"])

print("\n[5b] re-running init never weakens what a human confirmed")
# covers: scripts/framework-init.py plan() -- layers and config used to be re-derived from
# detection alone, so a confirmed layer 3 (and its deploy block) vanished on the next run.
d = mkproj("confirmed", {"app.py": "print(1)\n", "pyproject.toml": "[project]\nname = 'x'\n"})
run_init(d)
fv = read_fv(d)
check("starts with no production layer (nothing to detect)", fv.get("layers") == [1, 2])
fv["layers"] = [1, 2, 3]
fv["config"]["deploy"] = {"protected_branch": "production", "deploy_cmds": ["fly deploy"]}
fv["config"]["code_re"] = r"\.(py|ex)$"
with open(os.path.join(d, ".framework-version"), "w") as f:
    json.dump(fv, f)
open(os.path.join(d, "package.json"), "w").close()  # stack drift: the Guide says "run init again"
run_init(d)
after = read_fv(d)
check("confirmed layer 3 survives the re-run", after.get("layers") == [1, 2, 3])
check("confirmed deploy block survives verbatim",
      after.get("config", {}).get("deploy") == {"protected_branch": "production", "deploy_cmds": ["fly deploy"]})
check("custom code_re survives", after.get("config", {}).get("code_re") == r"\.(py|ex)$")
check("and the re-run still did its job (new stack added)", after.get("stacks") == ["node", "python"])

print("\n[5c] a capability that appears later is still added on the re-run")
with open(os.path.join(d, "wrangler.toml"), "w") as f:
    f.write("[[d1_databases]]\nbinding='DB'\n")
run_init(d)
after = read_fv(d)
check("prod_db block added", after.get("config", {}).get("prod_db", {}).get("kind") == "d1")
check("without touching the confirmed deploy block",
      after.get("config", {}).get("deploy", {}).get("protected_branch") == "production")

print("\n[6] the gate recognizes v0.3 as managed")
d = mkproj("gate")
run_init(d)
p = subprocess.run(["python3", FV, d], capture_output=True, text=True)
check("gate OPEN", p.returncode == 0 and "OPEN" in p.stdout)

print("\n[7] legacy (no marker) -> refuses, does not overwrite")
d = mkproj("legacy")
legacy = {"framework": "bulletproof", "version": "0.1", "tiers": [1, 2]}
with open(os.path.join(d, ".framework-version"), "w") as f:
    json.dump(legacy, f)
rc, out = run_init(d)
check("refuses (exit 2)", rc == 2)
check("legacy file untouched", read_fv(d) == legacy)

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
