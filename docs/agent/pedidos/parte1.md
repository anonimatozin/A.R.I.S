# Pedido de mudança no contrato — Parte 1

**Status:** opcional / não bloqueante. A Parte 1 funciona como está; os itens
abaixo são sugestões de melhoria para a Parte 0 (dona de `contract/`).

## 1. Cancelamento de chamada de LLM em andamento (sugestão)

**Problema:** `LLMClient.chat()` não recebe o `cancel` (`threading.Event` do
`ToolContext`). Quando o usuário manda parar, o laço da Parte 7 fica esperando
a resposta HTTP retornar — com `timeout_s` de 60 s e retries, uma chamada pode
levar minutos para perceber o cancelamento.

**Sugestão:** acrescentar um parâmetro keyword opcional à assinatura:

```python
def chat(
    self,
    messages: list[ChatMessage],
    tools: list[ToolSpec] | None = None,
    *,
    difficulty: Literal["easy", "normal", "hard"] = "normal",
    max_tokens: int = 1024,
    temperature: float = 0.3,
    cancel: threading.Event | None = None,   # novo, opcional
) -> LLMResponse: ...
```

Como é opcional com padrão `None`, dublês existentes (`FakeLLM`) continuariam
válidos por compatibilidade estrutural, mas a Parte 1 passaria a abortar
retry/loop assim que `cancel` fosse setado (levando `ProviderError` com
`kind="network"` ou um campo novo `cancelled=True`).

**Contorno atual (sem mudar o contrato):** a Parte 7 pode chamar
`router.chat(...)` numa thread separada e abandoná-la, ou configurar
`timeout_s`/`max_attempts` baixos na seção `llm` do `aris_agent.json`.

## 2. Observação: sem override de modelo por chamada

`LLMClient.chat()` não tem parâmetro de modelo — a escolha é só por
`difficulty` (cadeias da config). A Parte 1 manteve a assinatura exata e
resolve seleção pontual de provedor filtrando a cadeia (ex.: `--provider` na
CLI). Se um dia for útil, um `model: str | None = None` opcional atenderia
casos de teste/depuração sem quebrar ninguém.
