#!/usr/bin/env python3
"""Prova da guarda de deploy (camada 3): pede aprovacao antes de publicar em producao,
deixa passar o trabalho normal. Repos git reais."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = "/Users/arogus/Desktop/Claude_Playground/bulletproof-plugin"
GUARD = os.path.join(PLUGIN, "scripts", "deploy-guard.py")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FALHA", name))

root = os.path.realpath(tempfile.mkdtemp(prefix="bp-deploy-"))

def sh(*a):
    subprocess.run(a, capture_output=True)

def mk_repo(name, layers=None, managed=True):
    layers = layers if layers is not None else [1, 2, 3]
    repo = os.path.join(root, name)
    os.makedirs(repo, exist_ok=True)
    if managed:
        fv = {"framework": "bulletproof", "version": "0.3", "plugin": "bulletproof",
              "status": "active", "layers": layers, "stacks": ["node"],
              "config": {"deploy": {"protected_branch": "main",
                                    "deploy_cmds": ["wrangler deploy", "wrangler pages deploy", "vercel"]}}}
    else:
        fv = {"framework": "bulletproof", "version": "0.1"}
    with open(os.path.join(repo, ".framework-version"), "w") as f:
        json.dump(fv, f)
    open(os.path.join(repo, "app.ts"), "w").close()
    sh("git", "init", "-q", repo)
    sh("git", "-C", repo, "config", "user.email", "t@t")
    sh("git", "-C", repo, "config", "user.name", "t")
    sh("git", "-C", repo, "add", "-A")
    sh("git", "-C", repo, "commit", "-q", "-m", "init")
    sh("git", "-C", repo, "branch", "-M", "main")
    return repo

def run(repo, cmd, cwd=None):
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd or repo}
    p = subprocess.run(["python3", GUARD], input=json.dumps(payload), capture_output=True, text=True)
    return "ask" in p.stdout

repo = mk_repo("proj")

print("\n[A] git push origin main -> pede aprovacao")
check("ask", run(repo, "git -C %s push origin main" % repo))

print("\n[B] git push origin feature-x -> passa")
check("passa (branch de trabalho)", not run(repo, "git -C %s push origin feature-x" % repo))

print("\n[C] wrangler deploy -> pede aprovacao")
check("ask", run(repo, "npx wrangler deploy"))

print("\n[D] wrangler pages deploy -> pede aprovacao")
check("ask", run(repo, "npx wrangler pages deploy ./dist"))

print("\n[E] git status -> passa")
check("passa", not run(repo, "git -C %s status" % repo))

print("\n[F] git push --dry-run origin main -> passa")
check("passa (dry-run)", not run(repo, "git push --dry-run origin main"))

print("\n[G] git push origin HEAD:main -> pede aprovacao")
check("ask", run(repo, "git push origin HEAD:main"))

print("\n[H] push implicito na branch main -> pede aprovacao")
check("ask (implicito em main)", run(repo, "git push"))

print("\n[I] push implicito numa branch de trabalho -> passa")
sh("git", "-C", repo, "checkout", "-q", "-b", "feat")
check("passa (implicito em feat)", not run(repo, "git push"))
sh("git", "-C", repo, "checkout", "-q", "main")

print("\n[J] gh pr merge -> pede aprovacao")
check("ask", run(repo, "gh pr merge 5"))

print("\n[K] projeto sem camada 3 (layers [1,2]) -> passa")
r2 = mk_repo("nolayer3", layers=[1, 2])
check("passa (camada 3 off)", not run(r2, "git -C %s push origin main" % r2))

print("\n[L] projeto legado (nao gerido) -> passa")
r3 = mk_repo("legado", managed=False)
check("passa (nao gerido)", not run(r3, "npx wrangler deploy"))

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
