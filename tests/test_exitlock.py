#!/usr/bin/env python3
"""Prova isolada do Exit Lock (Fase 1, tijolo 2): porta + bloqueio + carimbo verde
+ ledger. Repos git reais em temp; ledger e estado ISOLADOS por env override, nunca
tocam no estado real. Imprime so o veredito por caso."""
import json
import os
import shutil
import subprocess
import tempfile

PLUGIN = "/Users/arogus/Desktop/Claude_Playground/bulletproof-plugin"
SCRIPTS = os.path.join(PLUGIN, "scripts")
GUARD = os.path.join(SCRIPTS, "exit-lock-guard.py")
MARKGREEN = os.path.join(SCRIPTS, "mark-green.sh")

results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print("  %s  %s" % ("PASS" if cond else "FALHA", name))

# realpath a' cabeca: em macOS o tempdir e' /var -> /private/var (symlink); resolver
# aqui garante que os caminhos batem com o que o git rev-parse devolve.
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
    """Repo git com app.py + README.md committed. Se nest, o .framework-version fica
    no dir PAI e o repo git e' o subdir (replica a topologia do FA)."""
    base = os.path.join(root, name)
    repo = os.path.join(base, nest) if nest else base
    os.makedirs(repo, exist_ok=True)
    fvdir = base if nest else repo
    if managed:
        fv = {"framework": "bulletproof", "version": "0.2", "plugin": "bulletproof",
              "status": status, "stacks": ["python"], "tiers": [1, 2]}
        if layers is not None:
            fv["layers"] = layers
    else:  # legado FA: v0.1 SEM o marcador "plugin"
        fv = {"framework": "bulletproof", "version": "0.1", "tiers": [1, 2]}
    with open(os.path.join(fvdir, ".framework-version"), "w") as f:
        json.dump(fv, f)
    with open(os.path.join(repo, "app.py"), "w") as f:
        f.write("def add(a, b):\n    return a + b\n")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("# projeto\n")
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

print("\n[A] commit de codigo nao-verde num projeto gerido -> BLOQUEIA")
r1 = mk_repo("managed1"); dirty_code(r1)
rc, err = run_guard(r1)
check("bloqueia (exit 2)", rc == 2)
check("stderr diz BLOQUEADO", "BLOQUEADO" in err)
blocks = [x for x in ledger_lines() if x["event"] == "block"]
check("ledger ganhou 1 block", len(blocks) == 1)
check("block com gate=exit_lock e project certo",
      blocks and blocks[-1]["gate"] == "exit_lock" and os.path.basename(blocks[-1]["project"]) == "managed1")

print("\n[E] retry do mesmo commit nao-verde -> agrupa por incidente")
run_guard(r1)  # segunda tentativa, estado inalterado
blocks = [x for x in ledger_lines() if x["event"] == "block"]
check("2 blocks registados", len(blocks) == 2)
check("mesmo incident nos dois (retries agrupam, nao inflacionam)",
      blocks[0]["incident"] == blocks[1]["incident"])

print("\n[B] /testar carimba verde -> destranca")
mg = sh(["bash", MARKGREEN, r1])
check("mark-green ok", mg.returncode == 0 and "verde carimbado" in mg.stdout)
rc, err = run_guard(r1)
check("agora passa (exit 0)", rc == 0)
check("ledger ganhou 1 test_green", len([x for x in ledger_lines() if x["event"] == "test_green"]) == 1)

print("\n[C] repo legado do FA (sem marca) -> Exit Lock ignora, passa sempre")
r2 = mk_repo("legacy1", managed=False); dirty_code(r2)
n_before = len(ledger_lines())
rc, err = run_guard(r2)
check("passa (exit 0), porta fechada", rc == 0)
check("ledger intacto (nao gerido -> nao regista)", len(ledger_lines()) == n_before)

print("\n[D] commit so de docs num projeto gerido -> nao morde")
r3 = mk_repo("managed_docs"); dirty_docs(r3)
rc, err = run_guard(r3)
check("passa (exit 0), so docs", rc == 0)

print("\n[G] topologia FA: git em platform/, .framework-version um nivel acima")
rG = mk_repo("fa_like", nest="platform"); dirty_code(rG)
rc, err = run_guard(rG, cmd=("git -C %s commit -m x" % rG), cwd=rG)
check("porta sobe a arvore e o Exit Lock morde (exit 2)", rc == 2)

print("\n[H] projeto gerido mas em bootstrapping (sem testes ainda) -> Exit Lock EM ESPERA")
rH = mk_repo("boot1", status="bootstrapping"); dirty_code(rH)
rc, err = run_guard(rH)
check("codigo sujo mas passa (exit 0): em espera ate status active", rc == 0)

print("\n[I] projeto gerido active mas camada 2 fora das layers ([1]) -> nao morde")
rI = mk_repo("nolock", layers=[1])
dirty_code(rI)
rc, _ = run_guard(rI)
check("commit passa (exit 0): camada 2 desligada por layers", rc == 0)

print("\n[F] fail-open")
rc, _ = run_guard(r3, cmd="git status")
check("nao-commit (git status) -> passa (exit 0)", rc == 0)
p = subprocess.run(["python3", GUARD], input="isto nao e json",
                   capture_output=True, text=True, env=env())
check("payload invalido -> passa (exit 0)", p.returncode == 0)

# ---------------------------------------------------------------------------
# Regressoes de 2026-09 (prova de aceitacao no Dashboard): ficheiros NOVOS.
# A impressao digital era `git diff HEAD`, que nao ve ficheiros por adicionar, e o hook
# corre ANTES do comando. Resultado: codigo novo passava sem verde num `git add && git
# commit`, e um verde valido morria com um simples `git add`. Era o caso do primeiro
# commit de testes de qualquer projeto adotado.
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

print("\n[J] verde carimbado ANTES do `git add` de um ficheiro novo continua valido depois")
rJ = mk_repo("novo-add")
write(rJ, "tests/test_novo.py", "def test_x():\n    assert True\n")
before = fp_of(rJ)
green(rJ)
sh(["git", "-C", rJ, "add", "tests/test_novo.py"])
check("a impressao digital nao muda com o `git add` (o conteudo e' o mesmo)", fp_of(rJ) == before)
rc, _ = run_guard(rJ)
check("commit passa (exit 0)", rc == 0)

print("\n[K] codigo novo por adicionar, SEM verde, `git add -A && git commit` num so comando -> BLOQUEIA")
rK = mk_repo("novo-semverde")
write(rK, "feature.py", "def nunca_testado():\n    return 1\n")
rc, err = run_guard(rK, cmd='git add -A && git commit -m "feat"')
check("bloqueia (exit 2): o hook corre antes do add, mas a guarda le a linha", rc == 2)
rc, _ = run_guard(rK, cmd='git add . && git commit -m "feat"')
check("idem com `git add .`", rc == 2)
rc, _ = run_guard(rK, cmd='git add feature.py && git commit -m "feat"')
check("idem com o ficheiro explicito", rc == 2)

print("\n[L] verde, e so DEPOIS nasce codigo novo -> o verde deixa de valer")
rL = mk_repo("novo-depois"); dirty_code(rL); green(rL)
rc, _ = run_guard(rL)
check("(controlo) logo depois do verde passa", rc == 0)
write(rL, "depois.py", "def criado_depois_do_verde():\n    return 1\n")
rc, _ = run_guard(rL, cmd='git add -A && git commit -m "feat"')
check("bloqueia (exit 2)", rc == 2)
green(rL)
rc, _ = run_guard(rL, cmd='git add -A && git commit -m "feat"')
check("novo /testar verde destranca (exit 0)", rc == 0)

print("\n[M] codigo por adicionar que NAO entra neste commit nao o prende")
rM = mk_repo("rascunho")
write(rM, "rascunho.py", "print('experiencia')\n")
dirty_docs(rM)
rc, _ = run_guard(rM, cmd='git add README.md && git commit -m "docs"')
check("`git add README.md && git commit` passa (so docs entram)", rc == 0)
rc, _ = run_guard(rM, cmd='git commit -am "docs"')
check("`git commit -am` passa (-a nao apanha ficheiros por adicionar)", rc == 0)
rc, _ = run_guard(rM, cmd='git add -u && git commit -m "docs"')
check("`git add -u` idem", rc == 0)

print("\n[N] so o CODIGO conta para a impressao digital")
rN = mk_repo("so-codigo"); dirty_code(rN); green(rN)
dirty_docs(rN)                                   # o CHANGELOG/README atualizado depois do /testar
write(rN, "store/output-grande.txt", "lixo\n")   # outputs/notas a aparecer na pasta
write(rN, "notas.md", "# ideias\n")
rc, _ = run_guard(rN, cmd='git add -A && git commit -m "feat + docs"')
check("docs e ficheiros soltos depois do verde nao o invalidam (exit 0)", rc == 0)
dirty_code(rN)
rc, _ = run_guard(rN, cmd='git add -A && git commit -m "feat + docs"')
check("mas mexer no codigo invalida (exit 2)", rc == 2)

print("\n[O] apagar um ficheiro de codigo tambem e' mexer no codigo")
rO = mk_repo("apagar"); dirty_code(rO); green(rO)
write(rO, "extra.py", "x = 1\n"); sh(["git", "-C", rO, "add", "-A"]); green(rO)
os.remove(os.path.join(rO, "extra.py"))
rc, _ = run_guard(rO)
check("bloqueia (exit 2)", rc == 2)

print("\n[P] o regex de codigo do projeto (config.code_re) manda")
rP = mk_repo("code-re")
fv_path = os.path.join(rP, ".framework-version")
with open(fv_path) as f:
    fvP = json.load(f)
fvP["config"] = {"code_re": r"\.(lua)$"}
with open(fv_path, "w") as f:
    json.dump(fvP, f)
dirty_code(rP)                                   # app.py: para ESTE projeto nao e' codigo
rc, _ = run_guard(rP)
check(".py fora do code_re -> passa sem verde (exit 0)", rc == 0)
write(rP, "jogo.lua", "print('ola')\n")
rc, _ = run_guard(rP, cmd='git add -A && git commit -m "feat"')
check(".lua dentro do code_re -> bloqueia (exit 2)", rc == 2)
fvP["config"] = {"code_re": "(regex partido"}
with open(fv_path, "w") as f:
    json.dump(fvP, f)
rc, _ = run_guard(rP)
check("code_re invalido cai no default, nao rebenta: .py volta a ser codigo (exit 2)", rc == 2)

print("\n[Q] a guarda encontra o commit no meio da linha, e nao o confunde com texto")
rQ = mk_repo("linha"); dirty_code(rQ)
outside = os.path.join(root, "outro-sitio"); os.makedirs(outside, exist_ok=True)
rc, _ = run_guard(rQ, cmd='cd %s && git add -A && git commit -m "x" && git push' % rQ, cwd=outside)
check("sessao fora do projeto, cd + add + commit + push -> bloqueia (exit 2)", rc == 2)
rc, _ = run_guard(rQ, cmd="git commit -m \"$(cat <<'EOF'\nfeat: x\n\nmais texto; com && separadores\nEOF\n)\"")
check("mensagem de commit em heredoc -> bloqueia na mesma (exit 2)", rc == 2)
rc, _ = run_guard(rQ, cmd='echo "git commit -m x"')
check('`echo "git commit"` nao e\' um commit (exit 0)', rc == 0)
rc, _ = run_guard(rQ, cmd='git log --grep="commit"')
check("`git log --grep=commit` nao e' um commit (exit 0)", rc == 0)

print("\n[R] repo sem nenhum commit ainda (primeiro commit de um projeto adotado)")
rR = os.path.join(root, "virgem"); os.makedirs(rR)
with open(os.path.join(rR, ".framework-version"), "w") as f:
    json.dump({"framework": "bulletproof", "version": "0.3", "plugin": "bulletproof",
               "status": "active", "layers": [1, 2], "stacks": ["python"]}, f)
write(rR, "app.py", "x = 1\n")
for args in (["git", "init", "-q", rR], ["git", "-C", rR, "config", "user.email", "t@t"],
             ["git", "-C", rR, "config", "user.name", "t"]):
    sh(args)
rc, _ = run_guard(rR, cmd='git add -A && git commit -m "init"')
check("sem verde -> bloqueia (exit 2)", rc == 2)
green(rR)
rc, _ = run_guard(rR, cmd='git add -A && git commit -m "init"')
check("com verde -> passa (exit 0)", rc == 0)

shutil.rmtree(root, ignore_errors=True)
n = sum(1 for _, c in results if c)
print("\n==> %d/%d PASS" % (n, len(results)))
raise SystemExit(0 if n == len(results) else 1)
