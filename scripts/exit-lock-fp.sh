#!/bin/bash
# exit-lock-fp.sh -- imprime a impressao digital do CODIGO de um repo git.
# Ponto de entrada unico dos DOIS lados do Exit Lock (mark-green.sh que carimba,
# exit-lock-guard.py que verifica), para o calculo ser identico por construcao.
# O calculo vive no codefp.py (la' esta' o porque' de cada escolha): HEAD + manifesto por
# conteudo dos ficheiros de codigo que diferem do HEAD, incluindo os novos por adicionar.
here="$(cd "$(dirname "$0")" && pwd)"
repo="${1:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -z "$repo" ] && exit 1
python3 "$here/codefp.py" "$repo"
