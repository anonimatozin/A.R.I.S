---
name: depuracao-de-codigo
description: Depurar erro de código de forma metódica — ler o erro inteiro, localizar o arquivo certo, reproduzir com o menor caso possível, corrigir com o menor diff e rodar os testes. Use quando o usuário relatar um erro, um teste falhar ou o código não fazer o esperado.
---

## Objetivo

Achar a causa real do erro e corrigi-lo com a menor mudança possível, sem quebrar
o resto.

## Quando usar

- Apareceu `Traceback`, mensagem de erro ou teste vermelho.
- O código roda mas faz algo errado (valor errado, trava, não responde).
- O usuário manda "conserta isso" apontando um comportamento.

## Passo a passo

1. **Leia o erro inteiro**: última linha diz o tipo (`KeyError`, `TypeError`), as
   linhas acima dizem onde. Anote arquivo, linha e mensagem completa.
2. **Localize o arquivo**: siga o `File "..."` do traceback até o seu código
   (não o traceback de biblioteca). Leia o contexto de 20–30 linhas ao redor.
3. **Reproduza**: monte o menor caso que falha (mesma entrada, sem interface se
   dá para chamar a função direto). Se não reproduzir, não adivinhe — peça o passo
   exato que gera o erro.
4. **Forme uma hipótese** e confirme com um log/`print` temporário ou depurador.
5. **Corrija com o menor diff**: a linha ou o bloco causador; nada de reescrever o
   módulo, renomear tudo ou "melhorar" o que não foi pedido.
6. **Rode os testes** do projeto (e um teste novo se faltar cobertura para o bug).
7. **Confirme a reprodução**: o caso que falhava agora passa e nada mais quebrou.

## Regras

- Nunca apague teste que falha para "passar"; conserte a causa.
- Se a correção grande demais para um diff, divida em partes e explique o plano.
- Não mude comportamento fora do pedido (formatação, nomes, estrutura).
- Erro de ambiente (dependência, permissão, caminho) é diferente de erro de lógica:
  diga qual dos dois é antes de mexer no código.
- Comando destrutivo (`git reset`, apagar pasta, reinstalar tudo) só com confirmação.
- Se o erro vier de biblioteca de terceiros, diga a versão e verifique se é bug conhecido.

## Exemplo rápido

> `TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'` em
> `conta.py:42` → `total` fica `None` quando a lista vem vazia (`sum([])` é 0, mas
> `total = None` depois `total + item` quebra). Correção mínima: inicializar
> `total = 0` e cobrir com um teste de lista vazia.

## Pergunte quando faltar

- "Qual comando exato você rodou?" / "Cole o traceback completo."
- "Isso começou depois de alguma mudança?"
