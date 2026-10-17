---
name: relatorio-comparativo
description: Montar relatório comparativo — coletar dados de cada opção com fonte e data, padronizar critérios, montar tabela, destacar diferenças e entregar resumo falado curto mais detalhes em arquivo. Use quando o usuário pedir para comparar opções, produtos, planos, ferramentas ou serviços.
---

## Objetivo

Dar ao usuário uma decisão clara: qual opção serve para o caso dele, com base em
critérios explícitos e dados com fonte.

## Quando usar

- "Qual é melhor, X ou Y?", "compara os planos", "me dá um parecer sobre A, B e C".
- Qualquer escolha entre 2+ alternativas com diferença de preço, desempenho ou recurso.

## Passo a passo

1. **Feche os critérios antes dos dados**: 4 a 7 critérios que importam para *este*
   usuário (orçamento, uso, prazo, compatibilidade). Pergunte se não souber.
2. **Defina as opções**: no máximo 3–4; se houver mais, elimine as fora do escopo.
3. **Colete dados iguais para todos**: mesma fonte/tipo de dado para cada opção,
   sempre com URL e data (use a skill `pesquisa-web` para nada ficar inventado).
4. **Monte a tabela**: linhas = critérios, colunas = opções, uma fonte por célula de
   dado. Marque `?` para dado não encontrado — nunca chute célula vazia.
5. **Destaque o que diferencia**: separo "igual em todas" do que decide a escolha.
6. **Recomende com ressalva**: 1 parágrafo falado (qual e porquê) + detalhe no arquivo.
7. **Salve o detalhe** em `workspace_dir` (`.md`) e informe o caminho no final.

## Formato da resposta

- **Falado (curto):** "Recomendo X porque <2 motivos>; vai Y se <condição>."
- **Arquivo (detalhe):** objetivo, critérios, tabela comparativa com fontes,
  prós/contras de cada, recomendação e limitações do que não foi possível verificar.

## Regras

- Critério sem dado vira `?`, não opinião disfarçada.
- Dado de marketing conta como alegação da própria empresa, marque como tal.
- Preço sempre com data e condição (anual? mensal? promocional?).
- Se as opções empatarem, diga isso e sugira o critério desempate.
- Nada de fabricar número; sem fonte, não entra na tabela.
- Tabela de 4 opções × 7 critérios é o limite legível; acima disso, corte opção.

## Exemplo de tabela

| Critério | Opção A | Opção B |
|---|---|---|
| Preço (mensal) | R$ 30 (2026-10-04, site) | R$ 25 (2026-10-04, site) |
| Suporte em pt-BR | sim | `?` não achei fonte |
| Uso seu (5 h/dia) | sobra | aperto |
