# Pedido de mudança no contrato — Parte 7

**Status:** não bloqueante. A Parte 7 funciona como o contrato está; os itens
abaixo são sugestões para a Parte 0 (dona de `contract/`).

## 1. Cancelamento faz parte da interface do `Agent` (sugestão)

**Problema:** o laço precisa parar quando o usuário manda ("pára!", botão de
cancelar da interface de voz). O cancelamento da Parte 7 é um
`threading.Event` observado no topo do laço e durante a execução de cada
ferramenta, exposto por `ArisAgent.cancel(session_id)`. Só que
`contract/protocols.py` define apenas `run(...)`: quem tem uma variável do
tipo `Agent` (o gateway/Parte 8) não pode cancelar sem importar a classe
concreta.

**Sugestão:** acrescentar ao protocolo:

```python
class Agent(Protocol):
    def run(self, user_text, session_id, confirm, events=None) -> AgentResult: ...
    def cancel(self, session_id: str | None = None) -> None: ...  # novo
```

Como `Agent` é `@runtime_checkable`, adicionar o método muda o que
`isinstance(x, Agent)` aceita — a Parte 0 pode preferir documentar o método
como "opcional" e checar com `getattr`.

**Contorno atual:** a Parte 7 publica `ArisAgent.cancel()` e a Parte 8 pode
chamar `getattr(agente, "cancel", None)`.

## 2. Cancelamento não alcança uma chamada de LLM em andamento (reforço do pedido da Parte 1)

A Parte 1 já pediu em `docs/agent/pedidos/parte1.md` um parâmetro
`cancel: threading.Event | None = None` em `LLMClient.chat`. A Parte 7 tem o
mesmo problema pelo lado do laço: entre o `chat()` e a resposta HTTP não há
nada para observar o `cancel`, então um `max_steps`/timeout do provedor pode
segurar a resposta por vários segundos.

**Sugestão (igual à da Parte 1):** `chat(..., cancel: threading.Event | None = None)`.
A Parte 7 já entrega o `Event` no `ToolContext`; repassaria o mesmo objeto ao
`chat`. Como o parâmetro seria opcional com padrão `None`, `FakeLLM` e os
clientes existentes continuam válidos estruturalmente.

**Contorno atual:** a Parte 7 verifica o cancelamento (a) antes de cada
chamada ao LLM, (b) antes de cada ferramenta e (c) no topo de cada volta do
laço; a chamada em si roda até o fim.

## 3. Observação: `AgentResult.stopped_reason` e o motivo interno

O contrato prevê `done | max_steps | budget | cancelled | error`. O laço tem
mais motivos internos (laço detectado, argumentos inválidos demais, falha de
provedor) e os dois últimos são agrupados em `error`, com o detalhe no texto
da resposta e no trace (`final.motivo` guarda o motivo interno). Se a Parte 9
querer distinguir na visualização, um campo extra `stopped_detail: str = ""`
em `AgentResult` evitaria ler o trace.
