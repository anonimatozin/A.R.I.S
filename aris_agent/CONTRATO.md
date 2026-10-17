# CONTRATO do `aris_agent`

Versão humana do contrato. **A interface é lei**: as partes só se comunicam por aqui
(`aris_agent/contract/`, `config.py`, `fakes.py`, `tools/registry.py`). Quem achar um
defeito registra em `docs/agent/pedidos/parteN.md` e contorna dentro da própria parte.

## O fluxo

```
usuário → Agent (Parte 7)
            ├─ Memory (Parte 4)        histórico + recall
            ├─ SkillCatalog (Parte 6)  skills relevantes entram no prompt
            ├─ LLMClient (Parte 1)     planeja / decide / responde
            │      └─ LLMRouter escolhe provedor:modelo por difficulty
            └─ ToolExecutor (Parte 5)  ÚNICO ponto que executa ferramenta
                   ├─ política: risco, raízes permitidas, prompt injection, taint
                   ├─ confirmação (ConfirmFn) para risco alto / hard_confirm
                   └─ Tool.run(args, ctx)  → ToolResult
```

Regra inegociável: **toda chamada de ferramenta passa pelo `ToolExecutor`**.
O agente (Parte 7) nunca chama `tool.run()` direto. Ferramentas nunca decidem
se devem rodar; elas só declaram o risco no `ToolSpec`.

## Tipos (`contract/types.py`)

| Tipo | O que é |
|---|---|
| `Risk` | `READ(0)` < `WRITE(1)` < `EXEC(2)` < `DESTRUCTIVE(3)`. Usado pela Parte 5 para decidir confirmação. |
| `ToolSpec` | Identidade da ferramenta: `name`, `description`, `parameters` (JSON Schema `object`), `risk`, `untrusted_output`, `timeout_s`, `tags`, `path_args`, `url_args`, `command_arg`. Os três últimos campos de caminho/comando são **instruções de segurança** para a Parte 5. |
| `ToolResult` | `ok`, `content` (o que o LLM vê, use `truncate_text`; padrão `""` para `ToolResult(ok=False, error=...)`), `data` (estruturado, não vai ao LLM), `error`, `artifacts`. Ferramenta **nunca** lança exceção para o laço: devolve `ok=False`. |
| `ToolCall` | `id`, `name`, `arguments` (`dict`). Vem do LLM. |
| `ChatMessage` | `role` (`system/user/assistant/tool`), `content`, `tool_calls`, `tool_call_id`, `name`. |
| `Usage` / `LLMResponse` | Tokens usados e resposta do provedor (`message`, `usage`, `provider`, `model`, `finish_reason`). |
| `ConfirmRequest` / `ConfirmFn` | O que é pedido ao usuário e a função que responde `bool`. `hard_confirm=True` exige confirmação forte (ação em lote/destrutiva). |
| `ToolContext` | `session_id`, `workdir`, `config`, `cancel` (`threading.Event`: setado = abortar), `taint` (já passou conteúdo não confiável). |
| `MemoryItem` | Item da memória: `id`, `text`, `kind`, `score`, `created_at`, `tags`. |
| `AgentEvent` / `EventSink` | Eventos do laço (`plan`, `tool_call`, `tool_result`, `confirm`, `final`, `error`) para UI/log. |
| `AgentResult` | Resposta final: `text`, `steps`, `tool_calls`, `ok`, `stopped_reason`, `usage`, `trace_id`. |

## Interfaces (`contract/protocols.py`)

| Protocol | Implementado por | Método principal |
|---|---|---|
| `Tool` | qualquer parte | `run(args, ctx) -> ToolResult` (sempre com `spec`) |
| `LLMClient` | Parte 1 | `chat(messages, tools=None, *, difficulty, max_tokens, temperature) -> LLMResponse` |
| `ToolExecutor` | Parte 5 | `execute(call, ctx, confirm) -> ToolResult` |
| `Memory` | Parte 4 | `remember`, `recall`, `forget`, `add_turn`, `recent_turns` |
| `SkillCatalog` | Parte 6 | `names`, `catalog_prompt`, `load` |
| `Agent` | Parte 7 | `run(user_text, session_id, confirm, events=None) -> AgentResult` |

## Erros (`contract/errors.py`)

`ArisAgentError` é a base. `ToolError` (problema de ferramenta/registro),
`PolicyDenied` (política da Parte 5 barrou) e `ProviderError` (falha de LLM, com
`kind` ∈ `rate_limit|auth|bad_request|server|network|tool_format` e `retry_after_s`).
O laço do agente não deixa exceção vazar: `ProviderError` vira `stopped_reason="error"`
e erro de ferramenta vira `ToolResult(ok=False)`.

## Utilitários (`contract/utils.py`)

- `redact_secrets(text)` — troca credenciais por `[REDACTED]`. Passe **antes** de gravar
  em log, memória ou arquivo.
- `truncate_text(text, max_chars=8000)` — corta no meio com marcador.
- `wrap_untrusted(text, source)` — envolve conteúdo da web/arquivo desconhecido e avisa
  que instruções dentro dele devem ser ignoradas. Obrigatório em toda saída com
  `untrusted_output=True`.

## Registro de ferramentas

```python
# aris_agent/tools/<subpacote>/__init__.py  (arquivo daquele dono)
def register(registry: ToolRegistry) -> None:
    registry.register(minha_ferramenta)
```

`aris_agent.tools.discover(registry)` importa os subpacotes com `pkgutil` e chama
`register`. Subpacote que falhar ao importar gera **aviso em log e é pulado** — uma
parte quebrada não derruba as outras. Nomes de ferramenta são únicos; duplicidade
levanta `ToolError`. `function_tool(spec)` transforma uma função `(args, ctx) -> ToolResult`
em ferramenta e converte qualquer exceção em `ToolResult(ok=False)`.

## Configuração (`config.py`)

`load_config()` lê padrões → `aris_agent.json` (raiz do projeto ou `data_dir`) →
variáveis `ARIS_AGENT_*`. **`sections` vem só do JSON**, então cada parte lê a sua:

```python
cfg = load_config()
meu = cfg.section("llm")     # ou "pc" | "web" | "memory" | "safety" | "skills" | "core"
```

Nada de credencial no JSON: chaves suspeas são removidas com aviso. Credenciais
vivem em variáveis de ambiente (ex.: `GROQ_API_KEY`).

## Dublês (`fakes.py`)

`FakeLLM(roteiro)`, `FakeMemory`, `FakeSkills`, `EchoTool`, `AutoConfirm(answer)`,
`PassthroughExecutor(registry)`. Nos testes use só isso e a interface do contrato.

## Testes e limites

- Testes em `tests/aris_agent/parteN/`; sem internet/chave/GUI por padrão.
- Marcadores: `@pytest.mark.live` (precisa de rede/chave) e `@pytest.mark.windows`
  (precisa da API do Windows) são pulados por padrão; ative com `ARIS_TEST_LIVE=1` /
  `ARIS_TEST_WINDOWS=1` ou `-m live` / `-m windows`.
- Dependências declaradas só em `requirements/parteN.txt`.
