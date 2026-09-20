#!/usr/bin/env python3
"""cmdparse.py -- reads a shell command line well enough that the guards are not blind.

The guards get the whole Bash command, exactly as the agent wrote it. An agent rarely
writes `git push` on its own: it writes `git add -A && git commit -m x && git push`,
`cd dashboard/api && npx wrangler deploy`, or `npm run deploy` (which HIDES the
`wrangler deploy` inside package.json). Looking at the command line as a block of text,
or only at the first command, lets exactly those shapes through.

This module gives the guards an honest view:
  - it splits the line into simple commands (&&, ||, ;, |, &, newlines), respecting
    quotes and skipping heredoc bodies (a commit message is not a command);
  - it follows the effective directory: `cd <p>`, subshells `( ... )`, `git -C <p>`,
    `npm --prefix <p>`, `pnpm -C <p>`, `yarn --cwd <p>`;
  - it expands package.json scripts (`npm run x`, `npm test`, `pnpm x`, `yarn x`,
    `bun run x`), recursively, so the guard sees the real command;
  - it opens up `bash -c "..."`, `sh -c '...'` and `eval "..."`: the line inside is
    read as a line.

The guards compare TOKENS, not text: `git commit -m "how to run wrangler deploy"` and
`grep -rn "wrangler deploy" docs/` mention the command without running it, and do not
get in the way.

It is not a complete shell parser, and does not try to be. When in doubt it returns the
text as it is, and the guard decides (inside the perimeter, the layer 3 guards are
fail-closed).
"""
import json
import os
import re
import shlex

MAX_SCRIPT_DEPTH = 3
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# prefixes that run ANOTHER program: the real program comes next
_WRAPPERS = {"sudo", "env", "command", "exec", "time", "nohup", "npx", "bunx", "pnpx"}
_NPM_LIFECYCLE = {"start", "stop", "restart", "test"}
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
_WRAPPER_VALUE_FLAGS = {
    "sudo": ("-u", "-g", "-h", "-p", "-C", "-r", "-t", "-T", "-U", "--user", "--group"),
    "env": ("-u", "-C", "-S", "--unset", "--chdir"),
    "npx": ("-p", "--package", "-c", "--call"),
}


def strip_heredocs(cmd):
    """Removes the body of each heredoc (`<<EOF ... EOF`). The body is DATA (typically the
    commit message), not commands; leaving it in would make the guard read prose as shell."""
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
            i += 1  # skip the delimiter line
    return "\n".join(out)


def split_segments(cmd):
    """List of (text, opens, closes): the simple commands on the line, in order, with the
    number of subshells each one opens and closes. Separators inside quotes do not count."""
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
    """Tokens of the simple command, without the leading environment assignments
    (FOO=bar cmd)."""
    try:
        toks = shlex.split(text, posix=True)
    except ValueError:  # unbalanced quotes: approximate tokens beat no tokens at all
        toks = text.split()
    while toks and _ASSIGN.match(toks[0]):
        toks = toks[1:]
    return toks


def program(toks):
    """(program, args) skipping wrappers (`npx -y wrangler@4 deploy` -> wrangler, [deploy]).
    The program comes without a version (`wrangler@4` -> `wrangler`) and without a path."""
    i = 0
    while i < len(toks):
        t = toks[i]
        base = os.path.basename(t)
        if base in _WRAPPERS:
            i += 1
            # wrapper flags (npx -y, env -i, sudo -u x ...), with or without a value
            takes_value = _WRAPPER_VALUE_FLAGS.get(base, ())
            while i < len(toks) and (toks[i].startswith("-") or _ASSIGN.match(toks[i])):
                i += 2 if toks[i] in takes_value else 1
            continue
        return base.split("@")[0] if not base.startswith("@") else base, toks[i + 1:]
    return None, []


def has_sequence(toks, words):
    """True if `words` appear as CONSECUTIVE tokens in `toks`. The first one is compared
    without a path and without a version (`./node_modules/.bin/wrangler@4` == `wrangler`).
    That is how `npx -y wrangler@4 deploy --minify` counts as `wrangler deploy`, and a
    quoted phrase (which is ONE token) does not."""
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
    """The shell line that this command will run inside it (`bash -c "..."`, `eval "..."`),
    or None."""
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
    """Value of a flag `--x <v>` or `--x=<v>` (the first one that appears), or None."""
    for i, a in enumerate(args):
        for nm in names:
            if a == nm and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(nm + "="):
                return a.split("=", 1)[1]
    return None


def git_parts(toks):
    """(subcommand, args, [-C paths]) of a git command, skipping the global options
    (-C <p>, -c <x>, --git-dir ...). (None, [], []) if it is not git."""
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
    """If the command runs a package.json script, returns (body, package_dir).
    Covers `npm run x`, `npm test|start|...`, `pnpm [run] x`, `yarn [run] x`, `bun run x`."""
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
        return None  # `npm install`, `npm ci`, `bun add`... are not scripts

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
    """Yields (text, tokens, dir) for each simple command the line will actually run, in
    order, already with the effective directory and with package.json scripts expanded."""
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
