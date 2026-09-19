#!/usr/bin/env python3
"""Prova do cmdparse: a leitura da linha de shell em que as tres guardas assentam.
Se isto le mal, as guardas ficam cegas (ou ladram a' toa) todas ao mesmo tempo."""
import json
import os
import sys
import tempfile

PLUGIN = "/Users/arogus/Desktop/Claude_Playground/bulletproof-plugin"
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
import cmdparse as cp

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FALHA", name))

def cmds(line, cwd="/p"):
    return [(text, d) for text, _toks, d in cp.effective_commands(line, cwd)]

def texts(line, cwd="/p"):
    return [t for t, _d in cmds(line, cwd)]

print("\n[A] parte a linha nos comandos simples")
check("&&", texts("git add -A && git commit -m x && git push") == ["git add -A", "git commit -m x", "git push"])
check("; | || &", texts("a; b | c || d & e") == ["a", "b", "c", "d", "e"])
check("novas linhas", texts("a\nb") == ["a", "b"])

print("\n[B] separadores dentro de aspas nao partem")
check("aspas duplas", texts('git commit -m "fix; push && deploy" && git push') ==
      ['git commit -m "fix; push && deploy"', "git push"])
check("aspas simples", texts("echo 'a && b' ; ls") == ["echo 'a && b'", "ls"])

print("\n[C] o corpo de um heredoc e' dados, nao comandos")
line = "git commit -m \"$(cat <<'EOF'\nfeat: x\n\ngit push origin main; wrangler deploy \"aspas\"\nEOF\n)\" && git status"
got = texts(line)
check("so' sobram o commit e o status", len(got) == 2 and got[1] == "git status")
check("o texto da mensagem nao virou comando", not any("wrangler" in t or "push" in t for t in got))

print("\n[D] segue o diretorio efetivo")
check("cd relativo junta ao cwd", cmds("cd dashboard/api && npx wrangler deploy") ==
      [("npx wrangler deploy", "/p/dashboard/api")])
check("cd absoluto", cmds("cd /x/y && ls") == [("ls", "/x/y")])
check("cd encadeado", cmds("cd a && cd b && ls") == [("ls", "/p/a/b")])
check("cd ..", cmds("cd a/b && cd .. && ls") == [("ls", "/p/a")])
check("subshell repoe o diretorio", cmds("(cd /elsewhere && ls) && git push") ==
      [("ls", "/elsewhere"), ("git push", "/p")])
check("git -C", cmds("git -C sub/dir push")[0][1] == "/p/sub/dir")
check("git -C absoluto", cmds("git -C /abs push")[0][1] == "/abs")

print("\n[E] programa real por tras de wrappers e atribuicoes")
check("npx -y wrangler@4", cp.program(cp.tokens("npx -y wrangler@4 deploy")) == ("wrangler", ["deploy"]))
check("FOO=1 sudo -u x git", cp.git_parts(cp.tokens("FOO=1 BAR=2 sudo -u x git -C d push origin main"))[0] == "push")
check("caminho do binario", cp.program(cp.tokens("./node_modules/.bin/wrangler deploy"))[0] == "wrangler")
check("git -c k=v push", cp.git_parts(cp.tokens("git -c user.name=x push origin main"))[:2] == ("push", ["origin", "main"]))
check("nao e' git", cp.git_parts(cp.tokens("echo git push"))[0] is None)

print("\n[F] has_sequence compara tokens, nao texto")
T = cp.tokens
check("direto", cp.has_sequence(T("wrangler deploy"), ["wrangler", "deploy"]))
check("com wrapper, versao e flags depois", cp.has_sequence(T("npx -y wrangler@4 deploy --minify"), ["wrangler", "deploy"]))
check("tres palavras", cp.has_sequence(T("npx wrangler pages deploy ./dist"), ["wrangler", "pages", "deploy"]))
check("pages deploy NAO e' `wrangler deploy`", not cp.has_sequence(T("npx wrangler pages deploy ./dist"), ["wrangler", "deploy"]))
check("frase entre aspas e' um so' token", not cp.has_sequence(T('git commit -m "como correr wrangler deploy"'), ["wrangler", "deploy"]))
check("grep pela frase", not cp.has_sequence(T('grep -rn "wrangler deploy" docs/'), ["wrangler", "deploy"]))

print("\n[G] abre bash -c e eval")
check("bash -c", "git push origin main" in texts('bash -c "git push origin main"'))
check("sh -c com cd la' dentro", ("npx wrangler deploy", "/p/api") in cmds("sh -c 'cd api && npx wrangler deploy'"))
check("eval", "git push" in texts('eval "git push"'))

print("\n[H] expande scripts do package.json")
with tempfile.TemporaryDirectory(prefix="bp-cmdparse-") as tmp:
    tmp = os.path.realpath(tmp)
    api = os.path.join(tmp, "api")
    os.makedirs(os.path.join(api, "src"))
    with open(os.path.join(api, "package.json"), "w") as f:
        json.dump({"scripts": {
            "deploy": "wrangler deploy",
            "release": "npm run build && npm run deploy",
            "build": "tsc -p .",
            "dev": "wrangler dev --remote",
            "test": "vitest run",
            "loop": "npm run loop",
        }}, f)

    def expanded(line, cwd):
        return [(t, d) for t, d in cmds(line, cwd)]

    check("npm run deploy", ("wrangler deploy", api) in expanded("npm run deploy", api))
    check("cd api && npm run deploy", ("wrangler deploy", api) in expanded("cd api && npm run deploy", tmp))
    check("npm --prefix api run deploy", ("wrangler deploy", api) in expanded("npm --prefix api run deploy", tmp))
    check("npm run deploy --prefix api", ("wrangler deploy", api) in expanded("npm run deploy --prefix api", tmp))
    check("a partir de uma subpasta (sobe ate' ao package.json)",
          ("wrangler deploy", api) in expanded("npm run deploy", os.path.join(api, "src")))
    check("script que chama outro script", ("wrangler deploy", api) in expanded("npm run release", api))
    check("npm test (atalho)", ("vitest run", api) in expanded("npm test", api))
    check("pnpm deploy (forma direta)", ("wrangler deploy", api) in expanded("pnpm deploy", api))
    check("yarn dev", ("wrangler dev --remote", api) in expanded("yarn dev", api))
    check("bun run deploy", ("wrangler deploy", api) in expanded("bun run deploy", api))
    check("npm install NAO e' um script", expanded("npm install", api) == [("npm install", api)])
    check("script inexistente nao rebenta", expanded("npm run nope", api) == [("npm run nope", api)])
    check("script recursivo para (profundidade limitada)", len(expanded("npm run loop", api)) <= 6)
    check("sem package.json nao rebenta", expanded("npm run deploy", "/nonexistent/dir") == [("npm run deploy", "/nonexistent/dir")])

print("\n[I] entradas estranhas nunca rebentam")
for weird in ["", "   ", '"aspas por fechar', "&&", ";;;", "(((", "cd", "git", "npm run", "bash -c"]:
    try:
        list(cp.effective_commands(weird, "/p"))
        ok = True
    except Exception:
        ok = False
    check("sobrevive a %r" % weird, ok)

n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
