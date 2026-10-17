# Parte 2 — Ferramentas do PC (`aris_agent.tools.pc`)

22 ferramentas de sistema/arquivo/Windows para o agente. Cada uma é um `FunctionTool`
(`FunctionTool(spec, fn)` via `@guarded`), **sem** política nem confirmação: isso é papel da
Parte 5. Todo resultado passa por `out()` (trunca em `ctx.config.max_tool_chars`, quebra
`wrap_untrusted` quando `untrusted_output=True`).

## Registro

```python
from aris_agent.tools import pc
pc.register(registry)          # adiciona as 22 ferramentas
```

## Ferramentas (nomes fixos)

| Ferramenta | Risco | path_args / command_arg | Notas |
|---|---|---|---|
| `pc_system_info` | READ | — | psutil: CPU, RAM, disco, bateria, uptime |
| `pc_list_processes` | READ | — | limite, filtro `name`, ordenação por mem/cpu |
| `pc_list_windows` | READ | — | hwnd, título, pid, processo, ativa (win32gui) |
| `pc_list_dir` | READ | `path` | tamanho, data, limite de itens |
| `pc_read_file` | READ | `path` | **`untrusted_output`**; offset/limit, BOM/cp1252/utf-16, binário recusado, 4 MB por varredura |
| `pc_search_files` | READ | `root` | **`untrusted_output`**; glob ou `contains` no nome/conteúdo, com limites |
| `pc_write_file` | WRITE | `path` | salva `.bak` timestampado antes de sobrescrever |
| `pc_move_file` | WRITE | `source`, `destination` | não sobrescreve sem avisar |
| `pc_delete_file` | DESTRUCTIVE | `path` | Lixeira (`send2trash`); recusa apagar a própria raiz |
| `pc_open_app` | EXEC | — (recebe **nome**) | mapa `section("pc")["apps"]` → caminho/URI/loja; nunca executa string arbitrária |
| `pc_focus_window` | EXEC | — | por título/hwnd (win32gui + truque do ALT) |
| `pc_run_command` | EXEC | `cwd` (arg: `command`) | `cmd` (string) ou `powershell` (argv), `timeout_s`, mata a árvore de processos |
| `pc_python_run` | EXEC | — (arg: `code`) | `python -I -B -X utf8`, pasta temporária `aris_py_*`, sem herdar variáveis sensíveis (`*_KEY`, `*TOKEN*`, `*SECRET*`, ...) |
| `calc` | READ | — | AST restrito (+ - * / // % ** e funções seguras), sem `eval`, limite de 4300 dígitos |
| `pc_clipboard_get` | READ | — | **`untrusted_output`** + `wrap_untrusted` |
| `pc_clipboard_set` | WRITE | — | texto str (win32clipboard; fallback tkinter) |
| `pc_screenshot` | READ | `filename` | PNG no `workspace_dir` (sem `filename`) ou em caminho resolvido; devolve só o caminho |
| `pc_ui_find` | READ | — | **`untrusted_output`**; filtra por `control_type`/`name`/`auto_id`/`class_name` |
| `pc_ui_click` | EXEC | — | clica no controle (invoke primário, senão posição) |
| `pc_ui_type` | EXEC | — | `SendInput` com `KEYEVENTF_UNICODE`; `\n` vira Enter |
| `pc_keys` | EXEC | — | atalhos `ctrl+shift+s` validados contra `pyautogui.KEYBOARD_KEYS` (máx. 8 teclas/atalho, 8 atalhos) |
| `pc_mouse` | EXEC | — | move/click/dblclick/rightclick/scroll dentro da tela; `FAILSAFE` ligado |

## Segurança de caminho (todas com `path_args`)

`resolve_path()` (em `helpers.py`) recusa, sempre com `PathRefusedError`:
UNC (`\\...`), unidade relativa (`C:foo`), escape das raízes (`allowed_roots` ∪ `ctx.workdir`),
inexistente (`must_exist=True`) ou ser pasta quando se pediu arquivo. Caminho relativo
resolve em `ctx.workdir`. O `@guarded` converte `PathRefusedError`/`OSError` em `ToolResult(ok=False)`.

## Dependências

`requirements/parte2.txt`: psutil, pyautogui, pywinauto, send2trash, pywin32, Pillow.
Todas são importadas com try/except no topo do módulo: se faltar (ou não houver área gráfica),
a ferramenta devolve `ok=False` explicando o que instalar — nada quebra no import do pacote.

## Como testar

```bash
python -m pytest tests/aris_agent/parte2 -q -p no:cacheprovider --tb=short   # comuns (padrão)
set ARIS_TEST_WINDOWS=1 && python -m pytest tests/aris_agent/parte2 -q       # + janelas/UIA/clipboard/mouse
python -m ruff check aris_agent/tools/pc tests/aris_agent/parte2
```

- `tests/aris_agent/parte2/test_parte2_windows.py` usa o marcador `windows` (pulado por padrão;
  abre o Bloco de Notas de verdade, digita, copia com `ctrl+c` e move o mouse — restaura tudo ao final).
- Os 9 testes `windows` passaram nesta máquina com `ARIS_TEST_WINDOWS=1`.

## Limitações conhecidas

- **PowerShell está bloqueado por política nesta máquina** (`WinError 5`): `pc_run_command`
  com `shell="powershell"` devolve erro amigável; o caminho de comando foi testado com `shell="cmd"`.
- Teclado/mouse reais, UIA e clipboard dependem de sessão interativa no Windows (testes `windows`).
- `pc_mouse`/`pc_screenshot` falham sem área gráfica (RDP/headless sem desktop).
- A política de risco, confirmações e negações NÃO fica aqui: a Parte 5 consome `ToolSpec.risk`.
