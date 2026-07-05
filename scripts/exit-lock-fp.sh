#!/bin/bash
# exit-lock-fp.sh -- imprime um fingerprint do estado do codigo de um repo git.
# Usado pelos DOIS lados do Exit Lock (mark-green.sh que carimba, exit-lock-guard.py
# que verifica), para o calculo ser identico por construcao. Fingerprint = HEAD +
# diff vs HEAD. Estavel face a staging (git diff HEAD ve staged+unstaged); muda
# quando o conteudo muda.
repo="${1:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -z "$repo" ] && exit 1
{ git -C "$repo" rev-parse HEAD 2>/dev/null; git -C "$repo" diff HEAD 2>/dev/null; } \
  | shasum -a 256 | cut -d' ' -f1
