# Pedido de mudança no contrato — Parte 5

**Status:** não bloqueante. O `SafeExecutor` funciona com o contrato atual;
nenhuma mudança é obrigatória. Abaixo, sugestões para a Parte 0 (dona de
`contract/`) que melhorariam a segurança — com o contorno que a Parte 5 usa hoje.

## 1. `ToolSpec` não distingue envio de dados (GET vs POST) (sugestão)

**Problema:** "envia dados para fora" (item 5 da especificação) não é
declarável. A Parte 5 usa `url_args` como proxy: qualquer ferramenta com
`url_args` depois de `ctx.taint=True` exige confirmação forte. Isso pune
`web_fetch` (GET) igual a um POST de fato — pesquisas longas na web viram uma
sequência de confirmações.

**Sugestão:** campo novo em `ToolSpec`:

```python
egress: bool = False   # True = envia dados do usuário para fora (POST/upload)
```

Com isso, `url_args` deixaria de ser interpretado como envio e o taint só
forçaria confirmação forte em `EXEC`, `DESTRUCTIVE` e `egress=True`.

## 2. Declaração de alvo destrutivo para comandos (sugestão)

**Problema:** `pc_run_command` tem `risk=EXEC`, mas o comando pode conter
`del`/`rd /s`. A Parte 5 faz *bump* de risco detectando marcadores no texto
(`del`, `rd`, `Remove-Item`, `Stop-Process`...). É heurística: um `del`
disfarçado de script escapa ao *bump* (continua exigindo confirmação de EXEC,
mas não a confirmação forte).

**Sugestão:** manter como está (a heurística é o melhor que dá para fazer sem
parser de shell), ou acrescentar ao contrato um helper oficial de classificação
de comando em `contract/utils.py` para as ferramentas declararem o risco real
antes de chegar aqui.

## 3. `ConfirmFn` sem contexto de sessão (sugestão)

**Problema:** `ConfirmRequest` não tem `session_id`/`trace_id`. A Parte 8
(por voz) pode querer amarrar a confirmação à sessão ativa (ex.: mostrar "na
conversa X").

**Sugestão:** `ConfirmRequest.session_id: str = ""` (campo opcional com
padrão vazio não quebra construtores existentes das partes 5/7).

## 4. Observação: `ToolContext.taint` mutável é suficiente

A contaminação funciona bem com `ctx.taint` (a Parte 5 seta após qualquer
`untrusted_output=True`). Registro aqui só para confirmar: nenhum pedido.
