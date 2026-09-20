#!/usr/bin/env python3
"""Isolated proof of the Exit Lock: gate + block + green stamp + ledger. Real git
repos in temp; ledger and state are ISOLATED by env override, never touching real
state. Prints only the verdict per case."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo: parent of tests/
SCRIPTS = os.path.join(PLUGIN, "scripts")
GUARD = os.path.join(SCRIPTS, "exit-lock-guard.py")
MARKGREEN = os.path.join(SCRIPTS, "mark-green.sh")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FAIL", name))

# realpath up front: on macOS the tempdir is /var -> /private/var (symlink); resolving
# here ensures the paths match what git rev-parse returns.
root = os.path.realpath(tempfile.mkdtemp(prefix="bp-exitlock-"))
LEDGER = os.path.join(root, "ledger.jsonl")
STATE = os.path.join(root, "state")

def env():
    e = dict(os.environ)
    e["BULLETPROOF_LEDGER"] = LEDGER
    e["BULLETPROOF_STATE"] = STATE
    return e

def sh(args):
    return subprocess.run(args, capture_output=True, text=True, env=env())

def mk_repo(name, managed=True, nest=None, status="active", layers=None):
    """Git repo with app.py + README.md committed. If nest, .framework-version stays
    in the PARENT dir and the git repo is the subdir (replicates the subdirectory
    case: git repo in platform/, control file one level up)."""
    base = os.path.join(root, name)
    repo = os.path.join(base, nest) if nest else base
    os.makedirs(repo, exist_ok=True)
    fvdir = base if nest else repo
    if managed:
        fv = {"framework": "bulletproof", "version": "0.2", "plugin": "bulletproof",
              "status": status, "stacks": ["python"], "tiers": [1, 2]}
        if layers is not None:
            fv["layers"] = layers
    else:  # legacy setup: v0.1 WITHOUT the "plugin" marker
        fv = {"framework": "bulletproof", "version": "0.1", "tiers": [1, 2]}
    with open(os.path.join(fvdir, ".framework-version"), "w") as f:
        json.dump(fv, f)
    with open(os.path.join(repo, "app.py"), "w") as f:
        f.write("def add(a, b):\n    return a + b\n")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("# project\n")
    for args in (["git", "init", "-q", repo],
                 ["git", "-C", repo, "config", "user.email", "t@t"],
                 ["git", "-C", repo, "config", "user.name", "t"],
                 ["git", "-C", repo, "add", "-A"],
                 ["git", "-C", repo, "commit", "-q", "-m", "init"]):
        sh(args)
    return repo

def dirty_code(repo):
    with open(os.path.join(repo, "app.py"), "a") as f:
        f.write("\ndef sub(a, b):\n    return a - b\n")

def dirty_docs(repo):
    with open(os.path.join(repo, "README.md"), "a") as f:
        f.write("\nmais docs\n")

def run_guard(repo, cmd=None, cwd=None):
    cmd = cmd if cmd is not None else ("git -C %s commit -m x" % repo)
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd},
               "cwd": cwd or repo, "session_id": "test-sess"}
    p = subprocess.run(["python3", GUARD], input=json.dumps(payload),
                       capture_output=True, text=True, env=env())
    return p.returncode, p.stderr

def ledger_lines():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER) as f:
        return [json.loads(l) for l in f if l.strip()]

print("\n[A] non-green code commit in a managed project -> BLOCKS")
r1 = mk_repo("managed1"); dirty_code(r1)
rc, err = run_guard(r1)
check("blocks (exit 2)", rc == 2)
check("stderr says BLOCKED", "BLOCKED" in err)
blocks = [x for x in ledger_lines() if x["event"] == "block"]
check("ledger gained 1 block", len(blocks) == 1)
check("block with gate=exit_lock and the right project",
      blocks and blocks[-1]["gate"] == "exit_lock" and os.path.basename(blocks[-1]["project"]) == "managed1")

print("\n[E] retry of the same non-green commit -> groups by incident")
run_guard(r1)  # second attempt, state unchanged
blocks = [x for x in ledger_lines() if x["event"] == "block"]
check("2 blocks logged", len(blocks) == 2)
check("same incident in both (retries group, they don't inflate)",
      blocks[0]["incident"] == blocks[1]["incident"])

print("\n[B] /testar stamps green -> unlocks")
mg = sh(["bash", MARKGREEN, r1])
check("mark-green ok", mg.returncode == 0 and "green stamped" in mg.stdout)
rc, err = run_guard(r1)
check("now passes (exit 0)", rc == 0)
check("ledger gained 1 test_green", len([x for x in ledger_lines() if x["event"] == "test_green"]) == 1)

print("\n[C] legacy repo (no marker) -> Exit Lock ignores it, always passes")
r2 = mk_repo("legacy1", managed=False); dirty_code(r2)
n_before = len(ledger_lines())
rc, err = run_guard(r2)
check("passes (exit 0), gate closed", rc == 0)
check("ledger untouched (unmanaged -> doesn't log)", len(ledger_lines()) == n_before)

print("\n[D] docs-only commit in a managed project -> doesn't bite")
r3 = mk_repo("managed_docs"); dirty_docs(r3)
rc, err = run_guard(r3)
check("passes (exit 0), docs only", rc == 0)

print("\n[G] subdirectory case: git repo in platform/, .framework-version one level up")
rG = mk_repo("fa_like", nest="platform"); dirty_code(rG)
rc, err = run_guard(rG, cmd=("git -C %s commit -m x" % rG), cwd=rG)
check("the gate climbs the tree and the Exit Lock bites (exit 2)", rc == 2)

print("\n[H] managed project but bootstrapping (no tests yet) -> Exit Lock ON HOLD")
rH = mk_repo("boot1", status="bootstrapping"); dirty_code(rH)
rc, err = run_guard(rH)
check("dirty code but passes (exit 0): on hold until status is active", rc == 0)

print("\n[I] managed, active project but layer 2 outside the layers ([1]) -> doesn't bite")
rI = mk_repo("nolock", layers=[1])
dirty_code(rI)
rc, _ = run_guard(rI)
check("commit passes (exit 0): layer 2 turned off by layers", rc == 0)

print("\n[F] fail-open")
rc, _ = run_guard(r3, cmd="git status")
check("non-commit (git status) -> passes (exit 0)", rc == 0)
p = subprocess.run(["python3", GUARD], input="this is not json",
                   capture_output=True, text=True, env=env())
check("invalid payload -> passes (exit 0)", p.returncode == 0)

# ---------------------------------------------------------------------------
# Regressions from 2026-09 (acceptance proof on the first project that adopted the
# plugin): NEW files. The fingerprint was `git diff HEAD`, which doesn't see untracked
# files, and the hook runs BEFORE the command. Result: new code passed without a green
# stamp in a single `git add && git commit`, and a valid green stamp died with a plain
# `git add`. This was the case of the first test commit of any adopted project.
# ---------------------------------------------------------------------------
def write(repo, rel, text):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)

def green(repo):
    return sh(["bash", MARKGREEN, repo])

def fp_of(repo):
    return sh(["bash", os.path.join(SCRIPTS, "exit-lock-fp.sh"), repo]).stdout.strip()

print("\n[J] green stamped BEFORE the `git add` of a new file is still valid afterward")
rJ = mk_repo("novo-add")
write(rJ, "tests/test_novo.py", "def test_x():\n    assert True\n")
before = fp_of(rJ)
green(rJ)
sh(["git", "-C", rJ, "add", "tests/test_novo.py"])
check("the fingerprint doesn't change with `git add` (the content is the same)", fp_of(rJ) == before)
rc, _ = run_guard(rJ)
check("commit passes (exit 0)", rc == 0)

print("\n[K] new untracked code, WITHOUT a green stamp, `git add -A && git commit` in one command -> BLOCKS")
rK = mk_repo("novo-semverde")
write(rK, "feature.py", "def nunca_testado():\n    return 1\n")
rc, err = run_guard(rK, cmd='git add -A && git commit -m "feat"')
check("blocks (exit 2): the hook runs before the add, but the guard reads the command line", rc == 2)
rc, _ = run_guard(rK, cmd='git add . && git commit -m "feat"')
check("same with `git add .`", rc == 2)
rc, _ = run_guard(rK, cmd='git add feature.py && git commit -m "feat"')
check("same with the explicit file", rc == 2)

print("\n[L] green, and only AFTERWARD new code is born -> the green stamp stops being valid")
rL = mk_repo("novo-depois"); dirty_code(rL); green(rL)
rc, _ = run_guard(rL)
check("(control) right after green it passes", rc == 0)
write(rL, "depois.py", "def criado_depois_do_verde():\n    return 1\n")
rc, _ = run_guard(rL, cmd='git add -A && git commit -m "feat"')
check("blocks (exit 2)", rc == 2)
green(rL)
rc, _ = run_guard(rL, cmd='git add -A && git commit -m "feat"')
check("a new green /testar unlocks (exit 0)", rc == 0)

print("\n[M] untracked code that does NOT enter this commit doesn't hold it back")
rM = mk_repo("rascunho")
write(rM, "rascunho.py", "print('experiencia')\n")
dirty_docs(rM)
rc, _ = run_guard(rM, cmd='git add README.md && git commit -m "docs"')
check("`git add README.md && git commit` passes (only docs go in)", rc == 0)
rc, _ = run_guard(rM, cmd='git commit -am "docs"')
check("`git commit -am` passes (-a doesn't catch untracked files)", rc == 0)
rc, _ = run_guard(rM, cmd='git add -u && git commit -m "docs"')
check("`git add -u` same", rc == 0)

print("\n[N] only CODE counts toward the fingerprint")
rN = mk_repo("so-codigo"); dirty_code(rN); green(rN)
dirty_docs(rN)                                   # the CHANGELOG/README updated after /testar
write(rN, "store/output-grande.txt", "lixo\n")   # outputs/notes showing up in the folder
write(rN, "notas.md", "# ideias\n")
rc, _ = run_guard(rN, cmd='git add -A && git commit -m "feat + docs"')
check("docs and stray files after green don't invalidate it (exit 0)", rc == 0)
dirty_code(rN)
rc, _ = run_guard(rN, cmd='git add -A && git commit -m "feat + docs"')
check("but touching the code invalidates it (exit 2)", rc == 2)

print("\n[O] deleting a code file also counts as touching the code")
rO = mk_repo("apagar"); dirty_code(rO); green(rO)
write(rO, "extra.py", "x = 1\n"); sh(["git", "-C", rO, "add", "-A"]); green(rO)
os.remove(os.path.join(rO, "extra.py"))
rc, _ = run_guard(rO)
check("blocks (exit 2)", rc == 2)

print("\n[P] the project's code regex (config.code_re) rules")
rP = mk_repo("code-re")
fv_path = os.path.join(rP, ".framework-version")
with open(fv_path) as f:
    fvP = json.load(f)
fvP["config"] = {"code_re": r"\.(lua)$"}
with open(fv_path, "w") as f:
    json.dump(fvP, f)
dirty_code(rP)                                   # app.py: for THIS project it's not code
rc, _ = run_guard(rP)
check(".py outside code_re -> passes without a green stamp (exit 0)", rc == 0)
write(rP, "jogo.lua", "print('ola')\n")
rc, _ = run_guard(rP, cmd='git add -A && git commit -m "feat"')
check(".lua inside code_re -> blocks (exit 2)", rc == 2)
fvP["config"] = {"code_re": "(regex partido"}
with open(fv_path, "w") as f:
    json.dump(fvP, f)
rc, _ = run_guard(rP)
check("invalid code_re falls back to default, doesn't blow up: .py is code again (exit 2)", rc == 2)

print("\n[Q] the guard finds the commit in the middle of the line, and doesn't mistake it for text")
rQ = mk_repo("line"); dirty_code(rQ)
outside = os.path.join(root, "outro-sitio"); os.makedirs(outside, exist_ok=True)
rc, _ = run_guard(rQ, cmd='cd %s && git add -A && git commit -m "x" && git push' % rQ, cwd=outside)
check("session outside the project, cd + add + commit + push -> blocks (exit 2)", rc == 2)
rc, _ = run_guard(rQ, cmd="git commit -m \"$(cat <<'EOF'\nfeat: x\n\nmore text; with && separators\nEOF\n)\"")
check("commit message in a heredoc -> still blocks (exit 2)", rc == 2)
rc, _ = run_guard(rQ, cmd='echo "git commit -m x"')
check('`echo "git commit"` is not a commit (exit 0)', rc == 0)
rc, _ = run_guard(rQ, cmd='git log --grep="commit"')
check("`git log --grep=commit` is not a commit (exit 0)", rc == 0)

print("\n[R] repo with no commit yet (first commit of an adopted project)")
rR = os.path.join(root, "virgem"); os.makedirs(rR)
with open(os.path.join(rR, ".framework-version"), "w") as f:
    json.dump({"framework": "bulletproof", "version": "0.3", "plugin": "bulletproof",
               "status": "active", "layers": [1, 2], "stacks": ["python"]}, f)
write(rR, "app.py", "x = 1\n")
for args in (["git", "init", "-q", rR], ["git", "-C", rR, "config", "user.email", "t@t"],
             ["git", "-C", rR, "config", "user.name", "t"]):
    sh(args)
rc, _ = run_guard(rR, cmd='git add -A && git commit -m "init"')
check("no green stamp -> blocks (exit 2)", rc == 2)
green(rR)
rc, _ = run_guard(rR, cmd='git add -A && git commit -m "init"')
check("with a green stamp -> passes (exit 0)", rc == 0)

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
