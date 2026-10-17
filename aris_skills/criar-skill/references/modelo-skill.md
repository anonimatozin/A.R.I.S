# Modelo de skill (copie e adapte)

Pasta: `data_dir/skills/<nome-da-skill>/SKILL.md`

```markdown
---
name: nome-da-skill
description: O que a skill faz — com detalhe. Use quando <situação concreta do
usuário>. Use também para <segunda situação>, se houver.
---

## Objetivo

<frase: o que a skill garante no final>

## Quando usar

- <sinal 1: palavra-chave do usuário>
- <sinal 2: contexto em que ela se aplica>

## Passo a passo

1. <ação concreta, com o critério>
2. <ação concreta, com o critério>
3. <verificação final: como saber que deu certo>

## Regras

- <limite de segurança: o que nunca fazer>
- <limite de escopo: o que fica de fora>
- <formato de resposta esperado>

## Exemplo rápido

> **Entrada:** ...
> **Saída:** ...
```

Checklist antes de salvar:

- [ ] nome em minúsculas com hífens, igual à pasta
- [ ] descrição diz **o que** e **quando** (1–1024 caracteres)
- [ ] corpo com menos de 150 linhas
- [ ] nenhum segredo, senha ou chave no texto
- [ ] usuário confirmou a gravação
