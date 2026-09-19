---
description: Corre a camada de testes do projeto (Bulletproof), com auto-check de cobertura antes (Passo 0). Verde carimba e destranca o commit; vermelho regista a falha e mantem o Exit Lock.
allowed-tools: Bash(python3 *) Bash(git *) Read Grep Glob Edit Write
---

# Testar (Bulletproof)

Corre a camada de testes do projeto atual, com um auto-check de cobertura ANTES de correr.

## Passo 0 — auto-check de cobertura

1. Ve o que mudou: `git status --short` + `git diff HEAD`. Os ficheiros NOVOS por adicionar
   (`??` no status) contam como alteracao e o `git diff` nao mostra o conteudo deles: le-os.
   Se nao ha alteracoes, salta para o Passo 1.
2. Para cada alteracao de CODIGO (logica nova ou alterada, fluxo novo, escrita em BD
   nova), responde: ha um teste que exercita isto? se esta logica falhar, algum teste
   fica vermelho?
3. Se falta cobertura COM VALOR, escreve-a agora, antes de correr, com estas regras:
   - **Testa o que o codigo DEVIA fazer** (inferido do nome, contexto, tipos, docs);
     nao fotografes cegamente o output atual. Ancora cada teste ao que cobre
     (comentario `# cobre: ficheiro:linha`).
   - **O comportamento atual parece ERRADO?** Escreve o teste do comportamento correto,
     deixa-o vermelho, e reporta como CANDIDATO A BUG; o utilizador decide. (O vermelho
     fica registado no ledger; e' esse o objetivo: apanhar bugs, nao esconde-los sob um
     teste que fotografa o defeito.)
   - **Sem teatro:** nada de testes tautologicos ou asserts triviais para encher. Se a
     alteracao nao tem logica testavel (docs, config, estilo), di-lo numa linha e segue.
   - **Sem confianca no "devia ser"? Pergunta ao utilizador,** ou protege o comportamento
     atual marcando `# protege comportamento atual (nao verificado)`.
4. Resume o Passo 0 numa linha: "cobertura ok" / "escrevi N testes para X" /
   "candidato(s) a bug: ...".

## Passo 1 — correr a suite e carimbar

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/testar.py .
```

## Passo 2 — reportar

Em linguagem simples: **verde** (carimbado; se foi o primeiro verde, o projeto foi
promovido a "active" e o Exit Lock passou a policiar os commits) ou **vermelho** (que
camada falhou; se inclui candidatos a bug do Passo 0, lista-os separados). Corrige o
codigo ate ficar verde, em vez de contornar a guarda.
