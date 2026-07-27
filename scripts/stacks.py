#!/usr/bin/env python3
"""stacks.py -- detecao de stacks pelos manifestos presentes no projeto (na raiz ou
ate alguns niveis abaixo, porque o codigo pode viver num subdir, ex.: o Dashboard tem
os package.json em dashboard/api/ e dashboard/frontend/). Partilhado pelo Guia (aviso de
drift) e pelo framework-init, para os dois nunca discordarem sobre o que conta como stack."""
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
    """Lista ordenada dos stacks cujos manifestos existem em `root` ou ate `depth`
    niveis abaixo (ignora node_modules/.git/etc.)."""
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
