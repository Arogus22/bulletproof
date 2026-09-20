#!/usr/bin/env python3
"""stacks.py -- stack detection from the manifests present in the project (at the root
or a few levels below, because the code can live in a subdir: a real monorepo keeps its
package.json files in dashboard/api/ and dashboard/frontend/). Shared by the Guide (drift
warning) and by framework-init, so the two never disagree on what counts as a stack."""
import os

STACK_MANIFESTS = {
    "node": ["package.json"],
    "python": ["pyproject.toml", "requirements.txt", "setup.py"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
    "ruby": ["Gemfile"],
}

SKIP_DIRS = {"node_modules", ".git", ".wrangler", "dist", "build", ".svelte-kit", ".next"}


def detect(root, depth=3):
    """Sorted list of the stacks whose manifests exist in `root` or down to `depth`
    levels below (ignores node_modules/.git/etc.)."""
    found = set()
    root = os.path.abspath(root)
    for dirpath, dirs, files in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        d = 0 if rel == "." else rel.count(os.sep) + 1
        if d >= depth:
            dirs[:] = []
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for stack, manifests in STACK_MANIFESTS.items():
            if any(m in files for m in manifests):
                found.add(stack)
    return sorted(found)
