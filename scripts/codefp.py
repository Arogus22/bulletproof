#!/usr/bin/env python3
"""codefp.py -- the CODE fingerprint of a git repo: what the Exit Lock proves green.

Single implementation, used by both sides of the Exit Lock (the /testar stamp and the
commit guard) through exit-lock-fp.sh, so the calculation is identical by construction.

fingerprint = sha256( HEAD + manifest )
manifest    = for each CODE file that differs from HEAD, the path and the sha256 of the
              content on disk (or DELETED). "Differs from HEAD" includes NEW files,
              whether already added or still untracked.

Why this way (the three failures it closes, proven on a real project in 2026-09):
  1. `git diff HEAD` does not see untracked files. `git add -A && git commit` with new
     code went through silently WITHOUT a green: the hook runs before the `add`, when the
     file does not exist yet for git.
  2. Stamping green and only then running `git add` on a new file changed the fingerprint
     without the content having changed: commit blocked for no reason. The manifest by
     content is the same before and after the `add`.
  3. Only code counts. Updating the CHANGELOG between /testar and the commit, or a notes
     or output file appearing in the folder, no longer invalidates a green that is still
     valid. Consistent with the rule that already existed: commits of only docs/config
     are not policed.
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
    """The project's "this is code" regex (config.code_re), or the default one."""
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
    """Paths differing from HEAD in the index or on disk (includes new files already added)."""
    if not has_head(repo):  # repo with no commits: everything in the index is new
        return _zsplit(_git(repo, "ls-files", "-z").stdout)
    return _zsplit(_git(repo, "diff", "HEAD", "--name-only", "-z").stdout)


def untracked(repo):
    """Untracked files, respecting the .gitignore."""
    return _zsplit(_git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout)


def changed_code(repo, regex, include_untracked=True):
    paths = set(tracked_changes(repo))
    if include_untracked:
        paths |= set(untracked(repo))
    return sorted(p for p in paths if regex.search(p))


def fingerprint(repo, regex=None):
    if regex is None:
        regex = code_regex(gate.read_fv(repo))
    head = _git(repo, "rev-parse", "HEAD").stdout.strip() if has_head(repo) else "(no commits)"
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
