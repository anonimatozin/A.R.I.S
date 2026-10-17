# Pedido de mudança / registro — Parte 2

**Status:** mudança **já aplicada** (adaptada ao Linux, 2026-10-09) e registrada
aqui para a Parte 2 (dona de `aris_agent/tools/pc/`) saber na próxima revisão.

## 1. `pc_run_command` adaptada a POSIX (aplicado)

**Problema:** a ferramenta só sabia executar `powershell`/`cmd`. No Linux ela
morria sempre com *“não consegui iniciar o powershell (No such file or
directory)”* — ou seja, o shell do PC ficava inteiro inutilizável fora do
Windows, e os cenários de avaliação da Parte 9 marcavam `pc_run_command` como
ferramenta quebrada.

**Mudança aplicada em `aris_agent/tools/pc/shell.py`:**

- padrão do argumento `shell`: `powershell` no Windows (`os.name == "nt"`),
  `sh` fora dele;
- enum do schema ganhou `sh` e `bash` (mantendo `powershell` e `cmd`);
- em POSIX a linha de comando roda como `[which(shell) or /bin/sh, "-c", cmd]`;
- pedir `powershell`/`cmd` num sistema não-Windows (ou `sh`/`bash` no Windows)
  devolve erro claro em vez de `OSError`;
- no Windows **nada mudou**: mesmos shells, mesmos argumentos, mesmos testes.

**Testes afetados:** os testes da Parte 2 que escrevem `shell="cmd"` com sintaxe
de Windows (`%CD%`, `1>&2`, `cmd.exe`) são de plataforma, não regressão da
mudança. Aplicado junto (2026-10-09): a marcação **`pytest.mark.windows`** —
mecanismo já suportado pelo `tests/aris_agent/conftest.py` — nos 7 testes
Windows-only da Parte 2 (`test_run_command_echo_cmd`,
`test_run_command_codigo_de_saida_diferente`, `test_run_command_usa_cwd`,
`test_run_command_captura_stderr`, `test_run_command_timeout_mata_arvore_de_processos`,
`test_run_command_cancelado`, `test_caminho_relativo_a_unidade_recusado`), e o
exemplo de shell desconhecido em `test_run_command_shell_desconhecido` mudou de
`"bash"` para `"xilsh"` (bash é válido em POSIX). No Windows rodam normalmente;
fora dele pulam por padrão e ativam com `ARIS_TEST_WINDOWS=1` ou `-m windows`.

**Como validar:** `venv-linux/bin/python -m pytest tests/aris_agent/parte2 -q`
e os cenários `codigo-*` / `seg-*` da Parte 9
(`python -m aris_agent.evals.run --filter categoria=codigo`).
