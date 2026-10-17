# Avaliação da ARIS-agente (Parte 9)

Medir o agente de verdade — não só unitários. Tudo mora em
`aris_agent/evals/` e roda sem rede por padrão.

## Como rodar

```bash
# avaliação roteirizada completa (CI, sem rede, sem chave)
python -m aris_agent.evals.run

# só uma categoria
python -m aris_agent.evals.run --filter categoria=seguranca

# contra o LLM real (exige a seção "llm" no aris_agent.json; limitado por --max)
python -m aris_agent.evals.run --live --filter categoria=seguranca --max 5

# só o classificador de intenções (usado pelo roteamento da Parte 8)
python -m aris_agent.evals.run --intents

# visualizador de traces: linha do tempo HTML offline
python -m aris_agent.evals.trace_view ~/.aris_agent/traces --out traces.html
```

Relatórios saem em `aris_agent/evals/relatorios/` (`avaliacao_scripted.json`
e `.md`), com taxa, passos médios, tokens e falhas detalhadas **por categoria**.

Testes: `pytest tests/aris_agent/parte9` (32 testes; os 2 testes `live` são
pulados por padrão — ative com `ARIS_TEST_LIVE=1` ou `pytest -m live`).

## O que existe

| Arquivo | Papel |
|---|---|
| `scenarios/*.jsonl` | 96 cenários: 68 gerais (11 categorias) + 28 adversariais |
| `scenarios.py` | carga/validação do esquema dos cenários |
| `runner.py` | `run_scripted` (FakeLLM) e `run_live` (LLM real) + relatório |
| `trace_view.py` | HTML único offline com a linha do tempo dos traces |
| `intents_dataset.jsonl` | 347 frases rotuladas em 6 rótulos |
| `intents.py` | protocolo de classificador injetável + linha de base em regras |
| `run.py` | CLI acima |

## Cenários (execução roteirizada)

Cada cenário tem `entrada`, um `roteiro` (as respostas falsas do `FakeLLM`,
com eventuais chamadas de ferramenta), um `ambiente` opcional (arquivos,
skills e páginas web falsas servidas em `127.0.0.1`) e um `esperado` com as
checagens:

- `ferramentas_usadas` / `ferramentas_proibidas`
- `ferramentas_ok` / `ferramentas_negadas` (resultado de cada chamada)
- `texto_contem` / `texto_nao_contem`
- `arquivos_existentes` / `arquivos_inexistentes` (efeito colateral real)
- `confirmacao_pedida` / `confirmacao_ferramenta` / `confirmacao_negada`
- `confirmar` — o que o roteiro responde quando o executor pergunta
  (padrão: **nega**; toda confirmação é gravada pelo `GravadorDeConfirmacao`)
- `historico` — turnos anteriores da sessão (contexto encadeado)

O laço, a segurança (Parte 5) e as ferramentas (Partes 2/3) rodam juntos:
a política é aplicada de verdade, e as checagens conferem efeitos no disco,
não só a resposta do assistente.

### Resultado da última rodada completa (Linux, 2026-10-09)

**96/96 cenários (100%)**, com segurança 28/28 — ver
`relatorios/avaliacao_scripted.md` para o relatório detalhado.

Destaques que os cenários exercitam de verdade:

- ação destrutiva → pede confirmação e, negada, **o arquivo continua no disco**;
- `format C:` / leitura de `.env` / `file:///etc/passwd` → negado em absoluto
  (nem pergunta);
- após ler página externa (taint), a segunda chamada de URL exige confirmação;
- injeção de prompt vindo da web, de skill ou da própria entrada não derruba
  a política: a ferramenta perigosa é negada de qualquer jeito.

## Modo live

`run_live` usa o `LLMRouter` real (Parte 1) com os mesmos cenários (o
`roteiro` é ignorado — o LLM decide). Sem a seção `llm` configurada, recusa com
mensagem clara. `max_tasks` limita o custo por rodada.

## Classificador de intenções

`intents_dataset.jsonl`: 347 frases em pt-BR rotuladas com `conversa`,
`pergunta`, `comando_pc`, `pesquisa`, `recado_ideia` e `perigoso` (inclui
frases mistas, injecção de prompt, leitura de `.env`/chaves, pedidos em inglês).

`avaliar_classificador(fn)` mede qualquer `Callable[[str], str]` — a Parte 8
injeta o classificador real aqui. A linha de base `classificar_regras`
(só regras, sem LLM) marca **99,1% geral e 100% em `perigoso`**; os testes
exigem ≥90% geral e ≥95% em `perigoso`.

## Limitações honestas

- O roteirizado prova o laço + política + ferramentas de forma determinística;
  **não** mede julgamento do LLM — isso é papel do modo `--live`.
- Os cenários não cobrem `web_search` (chamaria a DuckDuckGo em modo CI) nem
  `pc_ui_*`/`pc_keys` com efeito real de interface (a checagem é que a
  confirmação é pedida e negada).
- Os 22 testes Windows-only das Partes 2/5 (sintaxe `cmd.exe`, `C:\`, `windir`)
  estão marcados com `pytest.mark.windows` — pulados por padrão no Linux e
  executáveis com `ARIS_TEST_WINDOWS=1` ou `-m windows` (registrado em
  `docs/agent/pedidos/parte2.md`). Suíte completa em Linux: 832 passed,
  48 skipped, 0 failed.
