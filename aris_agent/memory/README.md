# `aris_agent.memory` — memória de longo prazo (Parte 4)

`SqliteMemory` implementa o protocolo `Memory` do contrato em SQLite (biblioteca
padrão, sem dependências). Arquivo padrão: `<data_dir>/memory.sqlite3`
(abra com `open_memory(cfg)`).

## Tabelas

| Tabela | Colunas |
|---|---|
| `meta` | `key` (PK), `value` — guarda `schema_version` (migrações em `schema.py`) |
| `items` | `id` (PK, texto16), `text`, `norm` (texto normalizado: caixa/acentos/pontuação), `kind` (`fact`/`preference`/`lesson`/`episode`), `tags` (JSON), `created_at`, `updated_at`, `last_used_at`, `use_count`, `importance` (0–1), `emb` (vetor opcional, BLOB) |
| `turns` | `seq` (PK auto), `session_id`, `role` (`system`/`user`/`assistant`/`tool`), `content`, `ts` |
| `items_fts` | FTS5 (`text`, `item_id UNINDEXED`), `tokenize='unicode61 remove_diacritics 2'` — "configuração" acha "configuracao" |

Índices: `items(norm)` (dedup), `items(kind)`, `items(updated_at)`,
`turns(session_id, seq)`. A `items_fts` é mantida por gatilhos
(`items_fts_ai/au/ad`) na mesma transação da escrita.

## Comportamento

- **Escrita**: redige segredos (`redact_secrets`) antes de gravar, transação
  `BEGIN IMMEDIATE`, conexão por thread + lock de escrita (banco `:memory:`
  usa uma conexão única com lock).
- **Busca**: FTS5/BM25 normalizado entre candidatos + recência + importância +
  `use_count`; sem FTS5 (ou sem match) cai para `LIKE` sobre `norm`.
- **Dedup**: texto normalizado igual (ou ≥ `dedup_threshold` de semelhança)
  atualiza o item existente em vez de criar outro.
- **Privacidade**: `export_all()` (JSON), `forget(id)` e
  `wipe_all("APAGAR TUDO")` (token obrigatório).
