#!/usr/bin/env python3
"""codefp.py -- a impressao digital do CODIGO de um repo git: o que o Exit Lock prova verde.

Implementacao unica, usada pelos dois lados do Exit Lock (o carimbo do /testar e a guarda
do commit) atraves do exit-lock-fp.sh, para o calculo ser identico por construcao.

fingerprint = sha256( HEAD + manifesto )
manifesto   = para cada ficheiro de CODIGO que difere do HEAD, o caminho e o sha256 do
              conteudo no disco (ou DELETED). "Difere do HEAD" inclui os ficheiros NOVOS,
              estejam ja' adicionados ou ainda por adicionar.

Porque' assim (as tres falhas que isto fecha, provadas no Dashboard em 2026-09):
  1. `git diff HEAD` nao ve ficheiros por adicionar. `git add -A && git commit` com codigo
     novo passava SEM verde: o hook corre antes do `add`, quando o ficheiro ainda nao existe
     para o git.
  2. Carimbar verde e so depois fazer `git add` de um ficheiro novo mudava a impressao
     digital sem o conteudo ter mudado: commit bloqueado sem razao. O manifesto por conteudo
     e' igual antes e depois do `add`.
  3. So' o codigo conta. Atualizar o CHANGELOG entre o /testar e o commit, ou um ficheiro
     de notas/outputs a aparecer na pasta, deixou de invalidar um verde que continua valido.
     Coerente com a regra que ja' existia: commits so' de docs/config nao sao policiados.
"""
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fv as gate

DEFAULT_CODE_RE = (r"\.(ts|tsx|js|jsx|mjs|cjs|svelte|vue|sql|py|go|rs|rb|java|kt|kts|"
                   r"c|cc|cpp|h|hpp|php|cs)$")


def code_regex(fvdata):
    """O regex de "isto e' codigo" do projeto (config.code_re), ou o default."""
    pat = ((fvdata or {}).get("config") or {}).get("code_re") if isinstance(fvdata, dict) else None
    if isinstance(pat, str) and pat:
        try:
            return re.compile(pat, re.I)
        except re.error:
            pass
    return re.compile(DEFAULT_CODE_RE, re.I)


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)


def _zsplit(out):
    return [p for p in out.split("\0") if p]


def has_head(repo):
    return _git(repo, "rev-parse", "--verify", "-q", "HEAD").returncode == 0


def tracked_changes(repo):
    """Caminhos que diferem do HEAD no indice ou no disco (inclui novos ja' adicionados)."""
    if not has_head(repo):  # repo sem commits: tudo o que esta' no indice e' novo
        return _zsplit(_git(repo, "ls-files", "-z").stdout)
    return _zsplit(_git(repo, "diff", "HEAD", "--name-only", "-z").stdout)


def untracked(repo):
    """Ficheiros por adicionar, respeitando o .gitignore."""
    return _zsplit(_git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout)


def changed_code(repo, regex, include_untracked=True):
    paths = set(tracked_changes(repo))
    if include_untracked:
        paths |= set(untracked(repo))
    return sorted(p for p in paths if regex.search(p))


def fingerprint(repo, regex=None):
    if regex is None:
        regex = code_regex(gate.read_fv(repo))
    head = _git(repo, "rev-parse", "HEAD").stdout.strip() if has_head(repo) else "(sem commits)"
    h = hashlib.sha256()
    h.update(("HEAD %s\n" % head).encode())
    for p in changed_code(repo, regex):
        full = os.path.join(repo, p)
        if os.path.isfile(full):
            with open(full, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
        else:
            digest = "DELETED"
        h.update(p.encode("utf-8", "surrogateescape") + b"\0" + digest.encode() + b"\n")
    return h.hexdigest()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    top = _git(target, "rev-parse", "--show-toplevel").stdout.strip()
    if not top:
        raise SystemExit(1)
    print(fingerprint(top))
