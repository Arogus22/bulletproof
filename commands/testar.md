---
description: Corre a camada de testes do projeto (Bulletproof). Verde carimba e destranca o commit; vermelho regista a falha e mantem o Exit Lock.
allowed-tools: Bash(python3 *)
---

# Testar (Bulletproof)

Corre a camada de testes do projeto atual e reporta o resultado.

1. Corre:

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/testar.py .
   ```

2. Reporta ao utilizador em linguagem simples: **verde** (carimbado, pode commitar) ou
   **vermelho** (que camada falhou). Se vermelho, resume as falhas e **NAO** tentes
   contornar o Exit Lock; o objetivo e' corrigir o codigo ate ficar verde, nao passar
   por cima da guarda.
