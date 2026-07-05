#!/usr/bin/env python3
"""stacks.py -- detecao de stacks pelos manifestos presentes na raiz do projeto.
Partilhado pelo Guia (aviso de drift) e pelo framework-init (marca os stacks
geridos), para os dois nunca discordarem sobre o que conta como stack."""
import os

STACK_MANIFESTS = {
    "node": ["package.json"],
    "python": ["pyproject.toml", "requirements.txt", "setup.py"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
    "ruby": ["Gemfile"],
}


def detect(root):
    """Lista ordenada dos stacks cujos manifestos existem em `root`."""
    found = set()
    for stack, files in STACK_MANIFESTS.items():
        if any(os.path.isfile(os.path.join(root, f)) for f in files):
            found.add(stack)
    return sorted(found)
