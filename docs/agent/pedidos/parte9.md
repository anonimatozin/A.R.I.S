# Pedido de mudança / observações — Parte 9

**Status:** nenhuma mudança de contrato é necessária. Observações feitas ao
rodar os 96 cenários (`aris_agent/evals/scenarios/`), com o cenário que as
revelou. Quem dona cada arquivo decide se incorpora.

## 1. Parte 2 — `pc_move_file` com destino inexistente devolve erro cru

**Cenário:** `arq-005` (mover `notas.txt` para `arquivo/notas.txt` sem a pasta
`arquivo/` existir).

**Obs:** o resultado é
`erro de sistema: No such file or directory (…/arquivo/notas.txt)` — o
`shutil.move` estoura `FileNotFoundError` e o texto vaza o caminho absoluto do
ambiente temporário. Duas melhorias possíveis:

- criar as pastas do destino automaticamente (comportamento do `shutil` com
  `makedirs`), **ou** devolver mensagem acionável:
  `destino não existe: crie a pasta 'arquivo' primeiro`;
- não ecoar caminho absoluto temporário na mensagem.

(Contornado no cenário criando `arquivo/.keep` no `ambiente`.)

## 2. Partes 4/5 — `memory_remember` sempre pede confirmação

**Cenários:** `mem-001`, `mem-004`, `mem-006`, `rec-002`, `rec-003`, `sec-025`.

**Obs:** `memory_remember` é `Risk.WRITE` sem caminho verificável → a política
cai em `"escrita sem caminho verificável"` e pergunta **toda vez**. Para um
assistente de voz que anota recados à beira da fala, isso é atrito real (e
custa um passo do laço). Como a memória é reversível (`memory_forget`) e não
toca disco do usuário, um `allow` no modo `balanced` — ou risco novo
`MEMORY` entre READ e WRITE — resolveria sem abrir brecha.

## 3. Parte 3 + 5 — taint derruba a segunda chamada de URL sem avisar

**Cenários:** `psc-004` e `psc-007` (duas leituras de página na mesma tarefa).

**Obs:** depois do primeiro `web_fetch`, o executor marca `ctx.taint=True` e a
política força confirmação forte em qualquer ferramenta com `url_args`
(comportamento correto e desejável — é o que segura `sec-021`). Só que a
*descrição da ferramenta* não avisa, então o LLM insiste e leva `ok=False`
sem entender o porquê. Sugestão: acrescentar à descrição de `web_fetch` /
`web_extract_links` algo como “a partir da segunda leitura na mesma tarefa,
o executor vai pedir confirmação”.

## 4. Parte 2 — `pc_run_command` no Linux (mudança aplicada)

Registrado em `docs/agent/pedidos/parte2.md`: a ferramenta agora usa
`sh`/`bash` fora do Windows (padrão `sh`, enum estendido). Sem isso nenhum
cenário de `codigo-*` funcionava em Linux.
