# `aris_agent/core` — núcleo do agente (Parte 7)

O laço que **entende → planeja → escolhe ferramenta → executa → avalia →
continua ou para → responde**, dependendo só das interfaces do contrato
(`LLMClient`, `ToolExecutor`, `Memory`, `SkillCatalog`, `ToolRegistry`).

```
run(user_text, session_id, confirm, events) ── lock por sessão
  │
  ├─ prompt = PromptBuilder (identidade, regras de ouro, skills,
  │            memórias lembradas, plano atual, reforço de correção)
  │   histórico = [system] + turnos recentes + [user]
  │
  └─ LAÇO ──────────────────────────────────────────────────────────────
     │  cancel?  max_steps?  orçamento de tokens?   ── sim ─▶ parar
     │  ContextManager.fit (compacta 1x, resume com LLM easy)
     │  ToolSelector.select (núcleo + grupos por tags + usadas)
     │  difficulty = easy | normal | hard
     │  LLM.chat ── texto sem tool_calls ─▶ resposta final ─┐
     │        └─ tool_calls (uma por vez):                  │
     │             valida args → executor.execute → msg     │
     │             tool (truncada) → repete                 │
     │   limites: max_steps | budget | cancel | laço        │
     │   erros de argumento: 2 correções por ferramenta ◀───┘
     │
     ├─ verificação (1 passada, easy): 3+ ferramentas ou pedido de conferir
     ├─ memória: add_turn(user) + add_turn(assistant)  [segredos redigidos]
     ├─ eventos: plan | tool_call | tool_result | confirm | final | error
     └─ trace JSONL: data_dir/traces/<trace_id>.jsonl
```

## Módulos

| Módulo | Papel |
|---|---|
| `agent.py` | `ArisAgent` (protocolo `Agent`): o laço, limites, confirmação, verificação |
| `prompts.py` | `PromptBuilder` + mensagens de verificação e de resumo de contexto |
| `selector.py` | `ToolSelector`: núcleo sempre + grupos por tags/palavras-chave |
| `plan.py` | `PlanState` + ferramenta interna `plan_update` (Risk.READ) |
| `context.py` | `ContextManager`: orçamento estimado e compactação de 1x por tarefa |
| `state.py` | `TaskState` por sessão + `Emitter` (eventos redigidos e à prova de erro) |
| `trace.py` | `TraceWriter`: JSONL por tarefa em `data_dir/traces/` |
| `validation.py` | `validate_args`: schema leve (required/tipo/enum) em pt-BR |
| `heuristics.py` | `looks_trivial`, `looks_like_correction`, `asks_to_verify`, `choose_difficulty` |
| `demo.py` | `python -m aris_agent.core.demo` (FakeLLM, sem rede) |

## Notas

- `plan_update` é registrada **nesta instância de registry** (se o nome já existir,
  o agente aproveita a ferramenta já registrada) — nunca em `aris_agent/tools/`.
- O system é **remontado a cada volta em que o plano muda de versão**, então a
  chamada seguinte já vê `Plano atual da tarefa: ...` atualizado.
- `validate_args` valida também objetos aninhados (required/properties/enum),
  por causa do `items[]` do `plan_update`.
- Cada `run` cria um `threading.Event` de cancelamento dentro do `ToolContext`;
  `ArisAgent.cancel(session_id)` seta esse evento de outra thread.
- Todo evento e o trace passam por `redact_secrets` antes de sair do laço.
