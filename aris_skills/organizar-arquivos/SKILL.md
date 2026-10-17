---
name: organizar-arquivos
description: Organizar arquivos com segurança — sempre listar antes de mover ou apagar, propor um plano, agir só dentro do workspace, usar a Lixeira e confirmar lotes. Use quando pedirem para arrumar, renomear, mover, limpar ou apagar arquivos e pastas.
---

## Objetivo

Deixar pastas organizadas sem perda de nada: antes de qualquer mudança, mostrar o
que existe e o que será feito.

## Quando usar

- "Arruma meus downloads", "joga isso na pasta certa", "limpa a área de trabalho".
- Renomear em lote, mover projetos, apagar temporários ou duplicados.

## Passo a passo

1. **Liste primeiro**: `dir`/`ls` (ou a ferramenta de leitura) da pasta alvo, com
   tamanho e data. Sem lista, nada se move.
2. **Monte o plano**: para cada grupo, destino, critério e o que fica de fora.
   Ex.: "42 PDFs → `Documentos\faturas\2026\`, 7 ficam por serem pessoais".
3. **Confirme com o usuário** quando: apagar algo, mais de 10 arquivos, nome repetido
   com conteúdo diferente, ou pasta que ele marcou como importante.
4. **Aja dentro do workspace**: só mexa em `workspace_dir`/`allowed_roots`. Fora
   disso, mostre o plano e peça permissão explícita (a política da Parte 5 pode barrar).
5. **Apague pela Lixeira**: envie para a Lixeira em vez de `del`/`rm` definitivo.
   Destrutivo de verdade só com confirmação forte.
6. **Verifique depois**: liste o destino, conte arquivos, confirme que o total bate.

## Regras

- Nunca mova/apague sem ter listado antes.
- Não sobrescreva: se o destino tem arquivo com o mesmo nome, pergunte ou sufixe.
- Preserve extensão e data de modificação ao mover.
- Lote grande (> 100 arquivos ou > 1 GB) vira plano em etapas, uma etapa por vez.
- Duplicado só sai depois de conferir conteúdo (hash/tamanho), não só o nome.
- Caminho com acento/espaço: sempre entre aspas no comando.
- Nada de recursão apagando `..`, raiz do disco ou a pasta do usuário inteira.

## Plano-modelo de resposta

```
Vou fazer (em ARIS_workspace\Downloads):
1. listar tudo e mostrar o inventário
2. mover 42 *.pdf → faturas\2026\   [aguardo 'sim']
3. enviar 5 temporários para a Lixeira  [aguardo 'sim']
4. relistar e conferir contagem
Fora do plano: 3 arquivos .psd (ficam onde estão).
```

## Depois de agir

- Reliste o destino e o origem, e diga o resultado em uma frase.
- Se algo falhou no meio, pare, mostre o que já foi feito e o que falta.
