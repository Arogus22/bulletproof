---
description: Adota o projeto atual no Bulletproof (cria/estende o .framework-version com o marcador do plugin). Versao mecanica, nao gera ainda a camada de testes.
argument-hint: [stacks opcionais, ex: python node]
disable-model-invocation: true
allowed-tools: Bash(python3 *)
---

# Framework Init (Bulletproof)

Adota o projeto atual (o diretorio de trabalho) no plugin Bulletproof, correndo o
script deterministico de adocao. Stacks pedidos pelo utilizador (opcional, podem vir
vazios): $ARGUMENTS

Passos:

1. Corre o script de adocao no diretorio atual. Se $ARGUMENTS trouxer stacks, passa
   cada um com `--stack`; se vier vazio, corre sem (o script deteta pelos manifestos):

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/framework-init.py .
   ```

   Exemplo com stacks: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/framework-init.py . --stack python --stack node`

2. Mostra ao utilizador, em linguagem simples, o que o script reportou: o caminho do
   `.framework-version`, o `status`, os `stacks` e os `tiers`.

3. Explica em 1-2 frases o proximo passo: o framework fica adotado em modo
   "bootstrapping" (o Guia orienta em cada arranque; o Exit Lock fica em ESPERA ate
   haver uma camada de testes verdes). A geracao dessa camada e' o passo seguinte.

Regras:
- NAO modifiques codigo da aplicacao.
- Se o script recusar (ja existe um `.framework-version` legado, sem o marcador do
  plugin), NAO forces: reporta ao utilizador o que o script disse e para.
