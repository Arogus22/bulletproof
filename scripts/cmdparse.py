#!/usr/bin/env python3
"""cmdparse.py -- le uma linha de shell o suficiente para as guardas nao serem cegas.

As guardas recebem o comando Bash inteiro, tal como o agente o escreveu. Um agente
raramente escreve `git push` sozinho: escreve `git add -A && git commit -m x && git push`,
`cd dashboard/api && npx wrangler deploy`, ou `npm run deploy` (que ESCONDE o
`wrangler deploy` dentro do package.json). Olhar para a linha como um bloco de texto, ou
so para o primeiro comando, deixa passar exatamente essas formas.

Este modulo da' a's guardas uma vista honesta:
  - parte a linha nos comandos simples (&&, ||, ;, |, &, novas linhas), respeitando
    aspas e saltando o corpo de heredocs (a mensagem de commit nao e' um comando);
  - segue o diretorio efetivo: `cd <p>`, subshells `( ... )`, `git -C <p>`,
    `npm --prefix <p>`, `pnpm -C <p>`, `yarn --cwd <p>`;
  - expande scripts do package.json (`npm run x`, `npm test`, `pnpm x`, `yarn x`,
    `bun run x`), recursivamente, para a guarda ver o comando real;
  - abre `bash -c "..."`, `sh -c '...'` e `eval "..."`: a linha la' dentro e' lida como linha.

As guardas comparam TOKENS, nao texto: `git commit -m "como correr wrangler deploy"` e
`grep -rn "wrangler deploy" docs/` mencionam o comando sem o correr, e nao incomodam.

Nao e' um parser de shell completo, nem tenta ser. Na duvida devolve o texto tal como
esta', e cabe a' guarda decidir (dentro do perimetro, as guardas da camada 3 sao
fail-closed).
"""
import json
import os
import re
import shlex

MAX_SCRIPT_DEPTH = 3
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# prefixos que correm OUTRO programa: o programa real vem a seguir
_WRAPPERS = {"sudo", "env", "command", "exec", "time", "nohup", "npx", "bunx", "pnpx"}
_NPM_LIFECYCLE = {"start", "stop", "restart", "test"}
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
_WRAPPER_VALUE_FLAGS = {
    "sudo": ("-u", "-g", "-h", "-p", "-C", "-r", "-t", "-T", "-U", "--user", "--group"),
    "env": ("-u", "-C", "-S", "--unset", "--chdir"),
    "npx": ("-p", "--package", "-c", "--call"),
}


def strip_heredocs(cmd):
    """Remove o corpo de cada heredoc (`<<EOF ... EOF`). O corpo e' DADOS (tipicamente a
    mensagem de commit), nao comandos; deixa'-lo la' faria a guarda ler prosa como shell."""
    lines = cmd.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = _HEREDOC.search(line)
        i += 1
        if m:
            end = m.group(2)
            while i < len(lines) and lines[i].strip() != end:
                i += 1
            i += 1  # salta a linha do delimitador
    return "\n".join(out)


def split_segments(cmd):
    """Lista de (texto, abre, fecha): os comandos simples da linha, por ordem, com o
    numero de subshells que cada um abre e fecha. Separadores dentro de aspas nao contam."""
    cmd = strip_heredocs(cmd or "")
    segs, cur, quote, i, n = [], [], None, 0, len(cmd)

    def flush():
        raw = "".join(cur).strip()
        del cur[:]
        if not raw:
            return
        opens = len(raw) - len(raw.lstrip("({ \t"))
        opens = sum(1 for ch in raw[:opens] if ch == "(")
        tail = len(raw) - len(raw.rstrip(")} \t"))
        closes = sum(1 for ch in raw[len(raw) - tail:] if ch == ")") if tail else 0
        text = raw.lstrip("({ \t").rstrip(")} \t").strip()
        if text:
            segs.append((text, opens, closes))

    while i < n:
        ch = cmd[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                cur.append(cmd[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            cur.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            cur.append(ch)
            cur.append(cmd[i + 1])
            i += 2
            continue
        if cmd[i:i + 2] in ("&&", "||"):
            flush()
            i += 2
            continue
        if ch in ";|&\n":
            flush()
            i += 1
            continue
        cur.append(ch)
        i += 1
    flush()
    return segs


def tokens(text):
    """Tokens do comando simples, sem as atribuicoes de ambiente iniciais (FOO=bar cmd)."""
    try:
        toks = shlex.split(text, posix=True)
    except ValueError:  # aspas desequilibradas: melhor tokens aproximados do que nenhuns
        toks = text.split()
    while toks and _ASSIGN.match(toks[0]):
        toks = toks[1:]
    return toks


def program(toks):
    """(programa, args) saltando wrappers (`npx -y wrangler@4 deploy` -> wrangler, [deploy]).
    O programa vem sem versao (`wrangler@4` -> `wrangler`) e sem caminho."""
    i = 0
    while i < len(toks):
        t = toks[i]
        base = os.path.basename(t)
        if base in _WRAPPERS:
            i += 1
            # flags do wrapper (npx -y, env -i, sudo -u x ...), com ou sem valor
            takes_value = _WRAPPER_VALUE_FLAGS.get(base, ())
            while i < len(toks) and (toks[i].startswith("-") or _ASSIGN.match(toks[i])):
                i += 2 if toks[i] in takes_value else 1
            continue
        return base.split("@")[0] if not base.startswith("@") else base, toks[i + 1:]
    return None, []


def has_sequence(toks, words):
    """True se `words` aparecem como tokens CONSECUTIVOS em `toks`. O primeiro compara-se
    sem caminho e sem versao (`./node_modules/.bin/wrangler@4` == `wrangler`). E' assim que
    `npx -y wrangler@4 deploy --minify` conta como `wrangler deploy`, e uma frase entre aspas
    (que e' UM token) nao."""
    if not words:
        return False
    n = len(words)
    for i in range(len(toks) - n + 1):
        first = os.path.basename(toks[i])
        if not first.startswith("@"):
            first = first.split("@")[0]
        if first == words[0] and list(toks[i + 1:i + n]) == list(words[1:]):
            return True
    return False


def inline_script(toks):
    """A linha de shell que o comando vai correr por dentro (`bash -c "..."`, `eval "..."`),
    ou None."""
    prog, args = program(toks)
    if prog in _SHELLS:
        for i, a in enumerate(args):
            if a == "-c" or (a.startswith("-") and not a.startswith("--") and a.endswith("c")):
                return args[i + 1] if i + 1 < len(args) else None
        return None
    if prog == "eval" and args:
        return " ".join(args)
    return None


def _resolve(base, path):
    path = os.path.expanduser(path)
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(base, path))


def _flag_value(args, names):
    """Valor de uma flag `--x <v>` ou `--x=<v>` (a primeira que aparecer), ou None."""
    for i, a in enumerate(args):
        for nm in names:
            if a == nm and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(nm + "="):
                return a.split("=", 1)[1]
    return None


def git_parts(toks):
    """(subcomando, args, [caminhos de -C]) de um comando git, saltando as opcoes globais
    (-C <p>, -c <x>, --git-dir ...). (None, [], []) se nao for git."""
    prog, args = program(toks)
    if prog != "git":
        return None, [], []
    dirs, i = [], 0
    while i < len(args):
        t = args[i]
        if t == "-C" and i + 1 < len(args):
            dirs.append(args[i + 1])
            i += 2
            continue
        if t in ("-c", "--git-dir", "--work-tree", "--namespace", "--exec-path") and i + 1 < len(args):
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t, args[i + 1:], dirs
    return None, [], dirs


def _find_package_json(start):
    cur = start
    while True:
        cand = os.path.join(cur, "package.json")
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def package_script(toks, directory):
    """Se o comando corre um script de package.json, devolve (corpo, dir_do_package).
    Cobre `npm run x`, `npm test|start|...`, `pnpm [run] x`, `yarn [run] x`, `bun run x`."""
    prog, args = program(toks)
    if prog not in ("npm", "pnpm", "yarn", "bun"):
        return None
    where = _flag_value(args, ("--prefix", "-C", "--dir", "--cwd"))
    base = _resolve(directory, where) if where else directory

    words, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a in ("--prefix", "-C", "--dir", "--cwd", "--workspace", "-w", "--filter"):
            skip = True
            continue
        if a == "--":
            break
        if a.startswith("-"):
            continue
        words.append(a)
    if not words:
        return None
    if words[0] in ("run", "run-script"):
        name = words[1] if len(words) > 1 else None
        explicit = True
    else:
        name, explicit = words[0], False
    if not name:
        return None
    if not explicit and prog in ("npm", "bun") and name not in _NPM_LIFECYCLE:
        return None  # `npm install`, `npm ci`, `bun add`... nao sao scripts

    pkg = _find_package_json(base)
    if not pkg:
        return None
    try:
        with open(pkg) as f:
            scripts = (json.load(f) or {}).get("scripts") or {}
    except Exception:
        return None
    body = scripts.get(name)
    if not isinstance(body, str) or not body.strip():
        return None
    return body, os.path.dirname(pkg)


def effective_commands(cmd, cwd, _depth=0):
    """Gera (texto, tokens, dir) para cada comando simples que a linha vai mesmo correr,
    pela ordem, ja' com o diretorio efetivo e com os scripts de package.json expandidos."""
    cur, stack = cwd, []
    for text, opens, closes in split_segments(cmd):
        for _ in range(opens):
            stack.append(cur)
        toks = tokens(text)
        if toks:
            prog, args = program(toks)
            if prog in ("cd", "pushd") and args:
                target = next((a for a in args if not a.startswith("-")), None)
                if target:
                    cur = _resolve(cur, target)
            else:
                here = cur
                _sub, _args, cdirs = git_parts(toks)
                for d in cdirs:
                    here = _resolve(here, d)
                yield text, toks, here
                if _depth < MAX_SCRIPT_DEPTH:
                    inner = inline_script(toks)
                    if inner:
                        for item in effective_commands(inner, here, _depth + 1):
                            yield item
                    script = package_script(toks, here)
                    if script:
                        body, pkgdir = script
                        for item in effective_commands(body, pkgdir, _depth + 1):
                            yield item
        for _ in range(closes):
            if stack:
                cur = stack.pop()


if __name__ == "__main__":
    import sys
    for text, toks, d in effective_commands(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.getcwd()):
        print("%s\t%s" % (d, text))
