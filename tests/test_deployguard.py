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

# ---------------------------------------------------------------------------
# Regressoes de 2026-09 (prova de aceitacao no Dashboard). A guarda lia a linha como um
# bloco e so' olhava para o PRIMEIRO comando git; as formas que um agente realmente
# escreve passavam caladas. Cada caso abaixo passava (ou ladrava a' toa) antes da correcao.
# ---------------------------------------------------------------------------
print("\n[M] push encadeado depois de outro comando git -> pede aprovacao")
check("git add && git commit && git push", run(repo, 'git add -A && git commit -m "x" && git push'))
check("git commit; git push origin main", run(repo, 'git commit -am "x"; git push origin main'))
check("git status && git push", run(repo, "git status && git push"))

print("\n[N] `cd <subpasta> &&` relativo (a forma documentada de fazer deploy no Dashboard)")
os.makedirs(os.path.join(repo, "dashboard", "api"), exist_ok=True)
check("cd dashboard/api && npx wrangler deploy", run(repo, "cd dashboard/api && npx wrangler deploy"))
check("versao fixada: npx -y wrangler@4 deploy", run(repo, "cd dashboard/api && npx -y wrangler@4 deploy --minify"))
check("pnpm exec wrangler deploy", run(repo, "pnpm exec wrangler deploy"))

print("\n[O] deploy escondido num script do package.json -> pede aprovacao")
with open(os.path.join(repo, "dashboard", "api", "package.json"), "w") as f:
    json.dump({"scripts": {"deploy": "wrangler deploy", "release": "npm run build && npm run deploy",
                           "build": "tsc -p .", "test": "vitest run"}}, f)
check("cd dashboard/api && npm run deploy", run(repo, "cd dashboard/api && npm run deploy"))
check("npm --prefix dashboard/api run deploy", run(repo, "npm --prefix dashboard/api run deploy"))
check("script que chama outro script", run(repo, "cd dashboard/api && npm run release"))
check("npm run build -> passa (nao publica)", not run(repo, "cd dashboard/api && npm run build"))
check("npm test -> passa", not run(repo, "cd dashboard/api && npm test"))

print("\n[P] sessao aberta FORA do projeto -> a guarda segue o comando ate' ao projeto")
outside = os.path.join(root, "outro-sitio")
os.makedirs(outside, exist_ok=True)
check("git -C <repo> push origin main", run(repo, "git -C %s push origin main" % repo, cwd=outside))
check("cd <repo> && git push", run(repo, "cd %s && git push" % repo, cwd=outside))
check("cd <repo>/dashboard/api && npx wrangler deploy",
      run(repo, "cd %s/dashboard/api && npx wrangler deploy" % repo, cwd=outside))
check("fora do projeto, push de outro repo -> passa", not run(repo, "git push origin main", cwd=outside))

print("\n[Q] destinos do push")
check("remote desconhecido, push implicito em main", run(repo, "git push github"))
check("--all empurra tambem o protegido", run(repo, "git push --all origin"))
check("dois refspecs, um protegido", run(repo, "git push origin feat/x main"))
check("refs/heads/main", run(repo, "git push origin refs/heads/main"))
check("+main (force)", run(repo, "git push origin +main"))
check("--force-with-lease origin main", run(repo, "git push --force-with-lease origin main"))
check("--delete main", run(repo, "git push origin --delete main"))
check("-o com valor nao confunde o remote", run(repo, "git push -o ci.skip origin main"))
check("branch de trabalho com 'main' no nome -> passa", not run(repo, "git push origin feature/main-menu"))
check("-u origin feat/x -> passa", not run(repo, "git push -u origin feat/x"))

print("\n[R] bash -c / eval")
check('bash -c "git push origin main"', run(repo, 'bash -c "git push origin main"'))
check("sh -c com cd e deploy", run(repo, "sh -c 'cd dashboard/api && npx wrangler deploy'"))
check('eval "git push"', run(repo, 'eval "git push"'))

print("\n[S] mencionar nao e' correr -> nao incomoda")
check("mensagem de commit", not run(repo, 'git commit -m "docs: como correr wrangler deploy e git push origin main"'))
check("mensagem de commit em heredoc", not run(repo,
      "git commit -m \"$(cat <<'EOF'\ndocs: deploy\n\ngit push origin main; wrangler deploy\nEOF\n)\""))
check("grep", not run(repo, 'grep -rn "wrangler deploy" docs/'))
check("echo", not run(repo, 'echo "para publicar: git push origin main"'))
check("git fetch/pull/log de main", not run(repo, "git fetch origin main && git pull origin main && git log origin/main"))

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
