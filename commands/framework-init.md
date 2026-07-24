---
description: "Adota o projeto atual no Bulletproof: deteta as capacidades (BD, deploy), propoe as camadas e escreve o ficheiro de controlo. Confirma contigo o que nao consegue ver."
argument-hint: "[stacks opcionais, ex: python node]"
disable-model-invocation: true
allowed-tools: Bash(python3 *) Read Edit
---

# Framework Init (Bulletproof)

Adota o projeto atual no plugin: deteta as capacidades e propoe as camadas.

Passos:

1. Corre o script de adocao (se $ARGUMENTS trouxer stacks, passa cada um com `--stack`):

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/framework-init.py .
   ```

2. Mostra ao utilizador, em linguagem simples, o que o script reportou: as **camadas
   propostas**, as **capacidades detetadas** (os sinais), e o **status**.

3. Se o script imprimiu perguntas de "CONFIRMA" (o que nao consegue ver do repositorio),
   **faz essas perguntas ao utilizador** e espera a resposta. Exemplos: "este projeto
   publica em producao?", "escreve numa base de dados de producao?".

4. Se o utilizador confirmar uma capacidade que a detecao nao viu, atualiza o
   `.framework-version`: acrescenta a **camada 3** ao `layers` e o bloco de config
   correspondente (`config.deploy` com o branch protegido, e/ou `config.prod_db`). Se o
   utilizador nao confirmar nada novo, deixa como o script escreveu.

5. Explica o proximo passo em 1-2 frases: em `bootstrapping`, corre `/testar`; ao primeiro
   verde o projeto fica `active` e o Exit Lock arma-se. As guardas de producao (camada 3),
   se ligadas, passam a pedir a tua aprovacao antes de publicar ou escrever na BD de prod.

Regras:
- NAO modifiques codigo da aplicacao.
- Se o script recusar (ja existe um `.framework-version` legado, sem o marcador do plugin),
  NAO forces: reporta o que o script disse e para.
