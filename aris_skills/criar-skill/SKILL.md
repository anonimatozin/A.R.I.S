---
name: criar-skill
description: Propor e escrever uma nova skill em data_dir/skills — escolher nome e descrição que digam quando usar, manter o SKILL.md objetivo com passo a passo, e sempre pedir confirmação do usuário antes de salvar. Use quando surgir conhecimento novo e recorrente durante uma tarefa.
---

## Objetivo

Transformar um procedimento que deu certo em skill reutilizável, sem poluir o
catálogo e **sem salvar nada sem o usuário autorizar**.

## Quando usar

- O usuário ensinou um jeito de fazer algo e vai repetir (correções dele são ouro).
- Uma sequência de passos funcionou e provavelmente será pedida de novo.
- O usuário pede explicitamente "cria uma skill".

## Passo a passo

1. **Confirme que é skill**: procedimento novo, recorrente e instrucional. Se é
   apenas um fato, use `memory_remember` (kind=`lesson`), não skill.
2. **Escolha o nome**: minúsculas, números e hífens, igual à pasta (ex.:
   `backup-documentos`). Máximo de 64 caracteres.
3. **Escreva a descrição**: o que faz **e quando usar**, com as palavras que o
   usuário diria. É o que o agente lê no catálogo — é metade do valor da skill.
4. **Monte o corpo**: objetivo, quando usar, passo a passo numerado, regras,
   um exemplo curto. Menos de 150 linhas; detalhe grande vai em `references/`.
5. **Proponha o pacote completo** ao usuário: nome, descrição, resumo dos passos e
   onde vai ser salvo (`data_dir/skills/<nome>/SKILL.md`).
6. **PARE e espere o "sim"** — salvar sem confirmação é proibido (mesmo que pareça
   inofensivo). Se ele pedir mudanças, ajuste e peça de novo.
7. **Salve só depois do sim**: crie a pasta, grave o `SKILL.md` em UTF-8.
8. **Valide**: recarregue o catálogo (`reload()`) e confirme que a skill aparece
   em `names()` e que `load(nome)` abre sem erro.

## Regras

- **Sempre peça confirmação antes de gravar qualquer arquivo da skill.**
- Uma skill = um procedimento; se virou duas, faça duas pastas.
- Não copie texto da web inteiro dentro da skill; deixe URL e resumo.
- Nunca inclua chave de API, senha, token ou caminho pessoal com dado privado.
- Nome da pasta == `name` do frontmatter (senão a skill é ignorada).
- Descrição de 1 a 1024 caracteres; diga **quando** usar, não só o que faz.
- Se já existir skill com o nome, pergunte se quer atualizar ou criar outro.

## Erros comuns (evite)

| Ruim | Bom |
|---|---|
| `description: Ajuda com PDFs` | `description: ... Use quando o usuário pedir para extrair texto, preencher ou juntar PDFs.` |
| passos vagos ("organize os arquivos") | passo com ação e critério ("liste antes; agrupe por extensão...") |
| 400 linhas no SKILL.md | corpo < 150 linhas + `references/` |

Modelo de estrutura em `references/modelo-skill.md`.
