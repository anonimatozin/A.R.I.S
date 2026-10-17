# Como criar skills da A.R.I.S.

Skill = pasta com um `SKILL.md` (frontmatter + instruções). O agente vê só
`nome: descrição` no prompt e carrega o conteúdo completo **só quando precisa**
(divulgação progressiva) — por isso descrição boa é metade do valor.

## Estrutura

```
aris_skills/<nome-da-skill>/          # embutida no projeto (dono: Parte 6)
data_dir/skills/<nome-da-skill>/      # do usuário (~/.aris_agent/skills/), tem prioridade
  SKILL.md                            # obrigatório
  scripts/                            # opcional: scripts p/ rodar com as ferramentas do PC
  references/                         # opcional: docs lidos sob demanda (skill_read_resource)
  assets/                             # opcional: modelos, imagens, etc.
```

Prioridade em caso de nome igual: `sections.skills.dirs` do `aris_agent.json` →
`data_dir/skills/` → `aris_skills/` do projeto.

## Frontmatter

```markdown
---
name: pesquisa-web
description: Pesquisar na internet com rigor — ... Use quando a resposta depender de informação atual.
---
```

| Campo | Obrigatório | Regra |
|---|---|---|
| `name` | sim | 1–64 caracteres; só `a-z`, `0–9` e hífen; sem hífen no início/fim nem `--`; **igual ao nome da pasta** |
| `description` | sim | 1–1024 caracteres; diz **o que faz e quando usar** |
| outros (ex.: `license`, `metadata`) | não | preservados; blocos aninhados simples são aceitos |

O parser é próprio (sem PyYAML): aceita `chave: valor` sem aspas, aspas simples
ou duplas nas pontas, comentários (`#`) e blocos aninhados indentados. Skill
inválida é **ignorada com aviso no log** (`aris.agent.skills.library`), sem
derrubar as demais.

## Boa descrição: diga *quando*

| Boa | Ruim |
|---|---|
| `Use quando o usuário pedir para extrair texto de PDF ou juntar PDFs.` | `Ajuda com PDFs.` |
| `... Use quando pedirem para arrumar, mover ou apagar arquivos.` | `Organiza arquivos.` |
| Frase completa, com as palavras que o usuário diria | Slogan vago ou só o nome repetido |

## Corpo do SKILL.md

Seções recomendadas, nesta ordem: `## Objetivo`, `## Quando usar`,
`## Passo a passo` (numerado), `## Regras`, `## Exemplo rápido`. Menos de
**150 linhas**; se o assunto crescer, vá para `references/` e liste o arquivo no
final do corpo (o `skill_load` já devolve a lista de recursos).

## Recursos

- `references/` — documentos lidos com `skill_read_resource(name, relative_path)`.
  Caminho é sempre relativo à pasta da skill; `..`, caminho absoluto e links
  simbólicos são bloqueados.
- `scripts/` — executados pelas ferramentas do PC (Parte 2) pelo caminho que o
  `skill_load` mostra; passam pelo executor de segurança (Parte 5). Não coloque
  script destrutivo em skill.
- Tamanho do recurso lido: até `max_resource_bytes` (padrão 200.000 bytes,
  configurável em `sections.skills`).

## Depois de criar

1. **Confirme com o usuário antes de salvar** (regra da skill `criar-skill`).
2. Salve em `data_dir/skills/<nome>/SKILL.md` (UTF-8).
3. Recarregue: `SkillLibrary.reload()` devolve `+ <nome>`; teste:
   `python -m pytest tests/aris_agent/parte6 -q`.

## Configuração (`aris_agent.json`)

```json
{ "sections": { "skills": { "dirs": ["D:/minhas-skills"], "max_resource_bytes": 200000 } } }
```
