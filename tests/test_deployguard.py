#!/usr/bin/env python3
"""Proof of the deploy guard (layer 3): asks for approval before publishing to production,
lets normal work through. Real git repos."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo: parent of tests/
GUARD = os.path.join(PLUGIN, "scripts", "deploy-guard.py")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FAIL", name))

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

print("\n[A] git push origin main -> asks for approval")
check("ask", run(repo, "git -C %s push origin main" % repo))

print("\n[B] git push origin feature-x -> passes")
check("passes (working branch)", not run(repo, "git -C %s push origin feature-x" % repo))

print("\n[C] wrangler deploy -> asks for approval")
check("ask", run(repo, "npx wrangler deploy"))

print("\n[D] wrangler pages deploy -> asks for approval")
check("ask", run(repo, "npx wrangler pages deploy ./dist"))

print("\n[E] git status -> passes")
check("passes", not run(repo, "git -C %s status" % repo))

print("\n[F] git push --dry-run origin main -> passes")
check("passes (dry-run)", not run(repo, "git push --dry-run origin main"))

print("\n[G] git push origin HEAD:main -> asks for approval")
check("ask", run(repo, "git push origin HEAD:main"))

print("\n[H] implicit push on the main branch -> asks for approval")
check("ask (implicit on main)", run(repo, "git push"))

print("\n[I] implicit push on a working branch -> passes")
sh("git", "-C", repo, "checkout", "-q", "-b", "feat")
check("passes (implicit on feat)", not run(repo, "git push"))
sh("git", "-C", repo, "checkout", "-q", "main")

print("\n[J] gh pr merge -> asks for approval")
check("ask", run(repo, "gh pr merge 5"))

print("\n[K] project without layer 3 (layers [1,2]) -> passes")
r2 = mk_repo("nolayer3", layers=[1, 2])
check("passes (layer 3 off)", not run(r2, "git -C %s push origin main" % r2))

print("\n[L] legacy project (unmanaged) -> passes")
r3 = mk_repo("legacy", managed=False)
check("passes (unmanaged)", not run(r3, "npx wrangler deploy"))

# ---------------------------------------------------------------------------
# 2026-09 regressions (acceptance proof on the first project that adopted the plugin). The
# guard used to read the line as one block and only looked at the FIRST git command; the
# forms an agent actually writes went through silently. Each case below passed (or barked
# for no reason) before the fix.
# ---------------------------------------------------------------------------
print("\n[M] chained push after another git command -> asks for approval")
check("git add && git commit && git push", run(repo, 'git add -A && git commit -m "x" && git push'))
check("git commit; git push origin main", run(repo, 'git commit -am "x"; git push origin main'))
check("git status && git push", run(repo, "git status && git push"))

print("\n[N] relative `cd <subfolder> &&` (the documented way to deploy in that real project)")
os.makedirs(os.path.join(repo, "dashboard", "api"), exist_ok=True)
check("cd dashboard/api && npx wrangler deploy", run(repo, "cd dashboard/api && npx wrangler deploy"))
check("pinned version: npx -y wrangler@4 deploy", run(repo, "cd dashboard/api && npx -y wrangler@4 deploy --minify"))
check("pnpm exec wrangler deploy", run(repo, "pnpm exec wrangler deploy"))

print("\n[O] deploy hidden inside a package.json script -> asks for approval")
with open(os.path.join(repo, "dashboard", "api", "package.json"), "w") as f:
    json.dump({"scripts": {"deploy": "wrangler deploy", "release": "npm run build && npm run deploy",
                           "build": "tsc -p .", "test": "vitest run"}}, f)
check("cd dashboard/api && npm run deploy", run(repo, "cd dashboard/api && npm run deploy"))
check("npm --prefix dashboard/api run deploy", run(repo, "npm --prefix dashboard/api run deploy"))
check("script that calls another script", run(repo, "cd dashboard/api && npm run release"))
check("npm run build -> passes (does not publish)", not run(repo, "cd dashboard/api && npm run build"))
check("npm test -> passes", not run(repo, "cd dashboard/api && npm test"))

print("\n[P] session opened OUTSIDE the project -> the guard follows the command into the project")
outside = os.path.join(root, "outro-sitio")
os.makedirs(outside, exist_ok=True)
check("git -C <repo> push origin main", run(repo, "git -C %s push origin main" % repo, cwd=outside))
check("cd <repo> && git push", run(repo, "cd %s && git push" % repo, cwd=outside))
check("cd <repo>/dashboard/api && npx wrangler deploy",
      run(repo, "cd %s/dashboard/api && npx wrangler deploy" % repo, cwd=outside))
check("outside the project, push from another repo -> passes", not run(repo, "git push origin main", cwd=outside))

print("\n[Q] push destinations")
check("unknown remote, implicit push on main", run(repo, "git push github"))
check("--all also pushes the protected branch", run(repo, "git push --all origin"))
check("two refspecs, one protected", run(repo, "git push origin feat/x main"))
check("refs/heads/main", run(repo, "git push origin refs/heads/main"))
check("+main (force)", run(repo, "git push origin +main"))
check("--force-with-lease origin main", run(repo, "git push --force-with-lease origin main"))
check("--delete main", run(repo, "git push origin --delete main"))
check("-o with a value does not confuse the remote", run(repo, "git push -o ci.skip origin main"))
check("working branch with 'main' in the name -> passes", not run(repo, "git push origin feature/main-menu"))
check("-u origin feat/x -> passes", not run(repo, "git push -u origin feat/x"))

print("\n[R] bash -c / eval")
check('bash -c "git push origin main"', run(repo, 'bash -c "git push origin main"'))
check("sh -c with cd and deploy", run(repo, "sh -c 'cd dashboard/api && npx wrangler deploy'"))
check('eval "git push"', run(repo, 'eval "git push"'))

print("\n[S] mentioning is not running -> does not get in the way")
check("commit message", not run(repo, 'git commit -m "docs: how to run wrangler deploy and git push origin main"'))
check("commit message in a heredoc", not run(repo,
      "git commit -m \"$(cat <<'EOF'\ndocs: deploy\n\ngit push origin main; wrangler deploy\nEOF\n)\""))
check("grep", not run(repo, 'grep -rn "wrangler deploy" docs/'))
check("echo", not run(repo, 'echo "to publish: git push origin main"'))
check("git fetch/pull/log of main", not run(repo, "git fetch origin main && git pull origin main && git log origin/main"))

print("\n[Z] a quoted `<<EOF` on one line does not blind the guard to the push on the next")
# covers: scripts/cmdparse.py strip_heredocs, through the guard that depends on it
check("ask", run(repo, 'echo "usage: prog <<EOF to feed input"\ngit push origin main'))

shutil.rmtree(root, ignore_errors=True)

n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
