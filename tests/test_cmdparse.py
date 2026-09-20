#!/usr/bin/env python3
"""Proof of cmdparse: the shell command line reading that the three guards rely on.
If this reads badly, the guards go blind (or bark for no reason) all at the same time."""
import json
import os
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo: parent of tests/
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
import cmdparse as cp

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FAIL", name))

def cmds(line, cwd="/p"):
    return [(text, d) for text, _toks, d in cp.effective_commands(line, cwd)]

def texts(line, cwd="/p"):
    return [t for t, _d in cmds(line, cwd)]

print("\n[A] splits the line into simple commands")
check("&&", texts("git add -A && git commit -m x && git push") == ["git add -A", "git commit -m x", "git push"])
check("; | || &", texts("a; b | c || d & e") == ["a", "b", "c", "d", "e"])
check("new lines", texts("a\nb") == ["a", "b"])

print("\n[B] separators inside quotes do not split")
check("double quotes", texts('git commit -m "fix; push && deploy" && git push') ==
      ['git commit -m "fix; push && deploy"', "git push"])
check("single quotes", texts("echo 'a && b' ; ls") == ["echo 'a && b'", "ls"])

print("\n[C] a heredoc's body is data, not commands")
line = "git commit -m \"$(cat <<'EOF'\nfeat: x\n\ngit push origin main; wrangler deploy \"quotes\"\nEOF\n)\" && git status"
got = texts(line)
check("only the commit and the status remain", len(got) == 2 and got[1] == "git status")
check("the message text did not turn into a command", not any("wrangler" in t or "push" in t for t in got))

print("\n[D] follows the effective directory")
check("relative cd joins to the cwd", cmds("cd dashboard/api && npx wrangler deploy") ==
      [("npx wrangler deploy", "/p/dashboard/api")])
check("absolute cd", cmds("cd /x/y && ls") == [("ls", "/x/y")])
check("chained cd", cmds("cd a && cd b && ls") == [("ls", "/p/a/b")])
check("cd ..", cmds("cd a/b && cd .. && ls") == [("ls", "/p/a")])
check("subshell restores the directory", cmds("(cd /elsewhere && ls) && git push") ==
      [("ls", "/elsewhere"), ("git push", "/p")])
check("git -C", cmds("git -C sub/dir push")[0][1] == "/p/sub/dir")
check("absolute git -C", cmds("git -C /abs push")[0][1] == "/abs")

print("\n[E] the real program behind wrappers and assignments")
check("npx -y wrangler@4", cp.program(cp.tokens("npx -y wrangler@4 deploy")) == ("wrangler", ["deploy"]))
check("FOO=1 sudo -u x git", cp.git_parts(cp.tokens("FOO=1 BAR=2 sudo -u x git -C d push origin main"))[0] == "push")
check("binary path", cp.program(cp.tokens("./node_modules/.bin/wrangler deploy"))[0] == "wrangler")
check("git -c k=v push", cp.git_parts(cp.tokens("git -c user.name=x push origin main"))[:2] == ("push", ["origin", "main"]))
check("is not git", cp.git_parts(cp.tokens("echo git push"))[0] is None)

print("\n[F] has_sequence compares tokens, not text")
T = cp.tokens
check("direct", cp.has_sequence(T("wrangler deploy"), ["wrangler", "deploy"]))
check("with wrapper, version and flags after", cp.has_sequence(T("npx -y wrangler@4 deploy --minify"), ["wrangler", "deploy"]))
check("three words", cp.has_sequence(T("npx wrangler pages deploy ./dist"), ["wrangler", "pages", "deploy"]))
check("pages deploy is NOT `wrangler deploy`", not cp.has_sequence(T("npx wrangler pages deploy ./dist"), ["wrangler", "deploy"]))
check("a quoted phrase is a single token", not cp.has_sequence(T('git commit -m "how to run wrangler deploy"'), ["wrangler", "deploy"]))
check("grep for the phrase", not cp.has_sequence(T('grep -rn "wrangler deploy" docs/'), ["wrangler", "deploy"]))

print("\n[G] opens bash -c and eval")
check("bash -c", "git push origin main" in texts('bash -c "git push origin main"'))
check("sh -c with cd inside it", ("npx wrangler deploy", "/p/api") in cmds("sh -c 'cd api && npx wrangler deploy'"))
check("eval", "git push" in texts('eval "git push"'))

print("\n[H] expands package.json scripts")
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
    check("from inside a subfolder (climbs up to the package.json)",
          ("wrangler deploy", api) in expanded("npm run deploy", os.path.join(api, "src")))
    check("script that calls another script", ("wrangler deploy", api) in expanded("npm run release", api))
    check("npm test (shortcut)", ("vitest run", api) in expanded("npm test", api))
    check("pnpm deploy (direct form)", ("wrangler deploy", api) in expanded("pnpm deploy", api))
    check("yarn dev", ("wrangler dev --remote", api) in expanded("yarn dev", api))
    check("bun run deploy", ("wrangler deploy", api) in expanded("bun run deploy", api))
    check("npm install is NOT a script", expanded("npm install", api) == [("npm install", api)])
    check("nonexistent script does not blow up", expanded("npm run nope", api) == [("npm run nope", api)])
    check("recursive script stops (limited depth)", len(expanded("npm run loop", api)) <= 6)
    check("no package.json does not blow up", expanded("npm run deploy", "/nonexistent/dir") == [("npm run deploy", "/nonexistent/dir")])

print("\n[I] weird inputs never blow up")
for weird in ["", "   ", '"unclosed quote', "&&", ";;;", "(((", "cd", "git", "npm run", "bash -c"]:
    try:
        list(cp.effective_commands(weird, "/p"))
        ok = True
    except Exception:
        ok = False
    check("survives %r" % weird, ok)

n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
